"""Reaping guarantees for the subprocess helper.

`run_process` promises that a timed-out or cancelled provider call leaves no
process behind. These tests hold it to that with real processes: a leaked
provider CLI is invisible to every other test in the suite.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from subscription_gateway.errors import GatewayError, ProviderError
from subscription_gateway.providers.process import classify_provider_failure, run_process

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="the process-group reaping path is POSIX-only"
)

# Records its own pid, then outlives any sane test timeout.
_SLEEPER = """
import os, sys, time
from pathlib import Path
Path(sys.argv[1]).write_text(str(os.getpid()))
time.sleep(30)
"""

# Same, but refuses SIGTERM, so only the SIGKILL escalation can stop it.
_IGNORES_SIGTERM = """
import os, signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).write_text(str(os.getpid()))
time.sleep(30)
"""

# Spawns a grandchild inside the same process group before sleeping.
_SPAWNS_GRANDCHILD = """
import os, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
Path(sys.argv[1]).write_text(f"{os.getpid()}\\n{child.pid}")
time.sleep(30)
"""


async def _wait_until_reaped(pid: int, *, deadline_seconds: float = 5.0) -> bool:
    """True once `pid` no longer exists, False if it outlives the deadline."""

    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        await asyncio.sleep(0.02)
    return False


def _recorded_pids(pidfile: Path) -> list[int]:
    return [int(line) for line in pidfile.read_text().splitlines() if line]


async def test_run_process_returns_streams_and_exit_code(tmp_path: Path) -> None:
    result = await run_process(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
        cwd=tmp_path,
        timeout_seconds=30,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"


async def test_run_process_writes_stdin_text_beyond_the_argv_limit(tmp_path: Path) -> None:
    text = "ä" * (200 * 1024)  # 400 KiB of UTF-8, over Linux's 128 KiB cap on one argv string

    result = await run_process(
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
        cwd=tmp_path,
        timeout_seconds=30,
        stdin_text=text,
    )

    assert result.returncode == 0
    assert result.stdout == text


async def test_run_process_rejects_invalid_unicode_before_spawning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def must_not_spawn(*args: object, **kwargs: object) -> None:
        raise AssertionError("a subprocess was started")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", must_not_spawn)

    with pytest.raises(GatewayError) as caught:
        await run_process(["cat"], cwd=tmp_path, timeout_seconds=30, stdin_text="hi \ud800")

    assert caught.value.status_code == 400
    assert caught.value.code == "request_validation_error"
    assert not isinstance(caught.value, ProviderError)  # never falls back


async def test_run_process_reports_a_failing_exit_code(tmp_path: Path) -> None:
    result = await run_process(
        [sys.executable, "-c", "raise SystemExit(3)"],
        cwd=tmp_path,
        timeout_seconds=30,
    )

    assert result.returncode == 3


async def test_run_process_decodes_invalid_utf8_without_raising(tmp_path: Path) -> None:
    result = await run_process(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff\\xfe')"],
        cwd=tmp_path,
        timeout_seconds=30,
    )

    assert result.returncode == 0
    assert result.stdout == "��"


async def test_run_process_runs_in_the_requested_directory(tmp_path: Path) -> None:
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    result = await run_process(
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        cwd=workdir,
        timeout_seconds=30,
    )

    assert Path(result.stdout.strip()).resolve() == workdir.resolve()


async def test_timeout_kills_the_child(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"

    with pytest.raises(TimeoutError):
        await run_process(
            [sys.executable, "-c", _SLEEPER, str(pidfile)],
            cwd=tmp_path,
            timeout_seconds=0.5,
        )

    (pid,) = _recorded_pids(pidfile)
    assert await _wait_until_reaped(pid), f"process {pid} survived the timeout"


async def test_timeout_escalates_to_sigkill_when_sigterm_is_ignored(tmp_path: Path) -> None:
    """The SIGTERM -> wait -> SIGKILL ladder, exercised end to end.

    Slow on purpose: `_terminate_process` allows the child two seconds to exit
    on its own before escalating, and that grace period is the behavior here.
    """

    pidfile = tmp_path / "pid"

    with pytest.raises(TimeoutError):
        await run_process(
            [sys.executable, "-c", _IGNORES_SIGTERM, str(pidfile)],
            cwd=tmp_path,
            timeout_seconds=0.5,
        )

    (pid,) = _recorded_pids(pidfile)
    assert await _wait_until_reaped(pid), f"process {pid} ignored SIGTERM and was never killed"


async def test_timeout_kills_the_whole_process_group(tmp_path: Path) -> None:
    """A provider CLI that spawns helpers must not leave them behind."""

    pidfile = tmp_path / "pids"

    with pytest.raises(TimeoutError):
        await run_process(
            [sys.executable, "-c", _SPAWNS_GRANDCHILD, str(pidfile)],
            cwd=tmp_path,
            timeout_seconds=1.0,
        )

    child_pid, grandchild_pid = _recorded_pids(pidfile)
    assert await _wait_until_reaped(child_pid), "the child survived"
    assert await _wait_until_reaped(grandchild_pid), "the grandchild was orphaned"


async def test_cancellation_kills_the_child_and_propagates(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    task = asyncio.create_task(
        run_process(
            [sys.executable, "-c", _SLEEPER, str(pidfile)],
            cwd=tmp_path,
            timeout_seconds=30,
        )
    )
    # Let the child start and record its pid before pulling the rug out.
    while not pidfile.exists():
        await asyncio.sleep(0.02)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    (pid,) = _recorded_pids(pidfile)
    assert await _wait_until_reaped(pid), f"process {pid} survived cancellation"


@pytest.mark.parametrize(
    ("diagnostic", "code", "status_code"),
    [
        ("Error: you are not logged in", "provider_not_authenticated", 503),
        ("invalid api key supplied", "provider_not_authenticated", 503),
        ("You have hit your usage limit for today", "provider_usage_limit", 429),
        ("The 'x' model is not supported when using Codex", "model_not_available", 404),
        ("There's an issue with the selected model (x)", "model_not_available", 404),
        ("upstream is overloaded", "provider_temporary_error", 503),
        ("segmentation fault", "provider_execution_failed", 502),
    ],
)
def test_classify_provider_failure(diagnostic: str, code: str, status_code: int) -> None:
    error = classify_provider_failure("codex", diagnostic)

    assert error.code == code
    assert error.status_code == status_code
    assert error.provider == "codex"


def test_classify_provider_failure_does_not_echo_the_diagnostic() -> None:
    """Stderr can carry paths, prompts, or tokens; none of it reaches the caller."""

    error = classify_provider_failure("claude", "boom: /home/someone/.claude/secret-token-abc")

    assert "secret-token-abc" not in str(error)
    assert "/home/someone" not in str(error)
