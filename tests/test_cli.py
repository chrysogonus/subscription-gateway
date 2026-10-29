"""End-to-end behavior of the `subscription-gateway` command.

The CLI is the only entry point most users touch, so these drive `main()` the
way a shell does: real argv, real config files, real exit codes. Providers are
stubbed at the registry boundary because `status` and `doctor` must never
require an installed CLI, credentials, or a network.
"""

from __future__ import annotations

import dataclasses
import socket
from pathlib import Path
from typing import Any, ClassVar

import pytest
import uvicorn

from subscription_gateway import __version__, cli
from subscription_gateway.config import ClaudeSettings, GatewayConfig
from subscription_gateway.providers.base import Provider
from subscription_gateway.providers.claude import ClaudeProvider
from subscription_gateway.providers.registry import ProviderStatus

READY = ProviderStatus(
    name="codex",
    display_name="Codex",
    enabled=True,
    installed=True,
    authenticated=True,
    available=True,
    models=["codex/gpt-5.6-sol"],
)
MISSING = ProviderStatus(
    name="claude",
    display_name="Claude Code",
    enabled=True,
    installed=False,
    authenticated=False,
    available=False,
    models=[],
)


class StubRegistry:
    """Stands in for ProviderRegistry so no provider CLI is ever consulted."""

    statuses_to_return: ClassVar[list[ProviderStatus]] = [READY, MISSING]
    providers_to_return: ClassVar[dict[str, Provider]] = {}

    def __init__(self, config: GatewayConfig, providers: dict[str, Provider] | None = None) -> None:
        self.config = config

    async def statuses(self) -> list[ProviderStatus]:
        return list(self.statuses_to_return)

    def get(self, name: str) -> Provider | None:
        return self.providers_to_return.get(name)


@pytest.fixture(autouse=True)
def stub_registry(monkeypatch: pytest.MonkeyPatch) -> type[StubRegistry]:
    monkeypatch.setattr(cli, "ProviderRegistry", StubRegistry)
    monkeypatch.setattr(StubRegistry, "statuses_to_return", [READY, MISSING])
    monkeypatch.setattr(StubRegistry, "providers_to_return", {})
    return StubRegistry


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def write_config(
    tmp_path: Path, *, port: int | None = None, sqlite_path: Path | None = None
) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "server:\n"
        "  host: 127.0.0.1\n"
        f"  port: {port if port is not None else free_port()}\n"
        "storage:\n"
        f"  sqlite_path: {sqlite_path or tmp_path / 'gateway.db'}\n",
        encoding="utf-8",
    )
    return config_path


def test_version_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["--version"])

    assert caught.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_a_subcommand_is_required() -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main([])

    assert caught.value.code == 2


def test_status_reports_each_provider_and_the_passthrough_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["status", "--config", str(write_config(tmp_path))])

    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert "Codex" in out
    assert "status: ready" in out
    assert "status: unavailable" in out
    assert "codex/gpt-5.6-sol" in out
    # The catalog is not the limit; status has to say so.
    assert "as codex/<model>" in out


def test_doctor_passes_when_storage_and_port_are_available(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["doctor", "--config", str(write_config(tmp_path))])

    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert "[PASS] SQLite storage" in out
    assert "[PASS] Server port" in out
    assert "[PASS] Python version" in out


def test_doctor_fails_when_the_port_is_already_in_use(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        port = int(holder.getsockname()[1])

        with pytest.raises(SystemExit) as caught:
            cli.main(["doctor", "--config", str(write_config(tmp_path, port=port))])

    assert caught.value.code == 1
    assert "already in use" in capsys.readouterr().out


def test_doctor_fails_when_storage_is_not_writable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A regular file where the database directory should be: mkdir cannot win.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    config_path = write_config(tmp_path, sqlite_path=blocker / "gateway.db")

    with pytest.raises(SystemExit) as caught:
        cli.main(["doctor", "--config", str(config_path)])

    assert caught.value.code == 1
    assert "[WARN] SQLite storage: not writable" in capsys.readouterr().out


def test_doctor_says_so_when_no_provider_is_ready(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(StubRegistry, "statuses_to_return", [MISSING])

    with pytest.raises(SystemExit) as caught:
        cli.main(["doctor", "--config", str(write_config(tmp_path))])

    # An unusable provider is a warning, not a failed check: the server still starts.
    assert caught.value.code == 0
    assert "No provider is currently ready" in capsys.readouterr().out


def test_serve_hands_the_configured_host_and_port_to_uvicorn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: dict[str, Any] = {}
    monkeypatch.setattr(cli, "create_app", lambda config: "app")
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: recorded.update(kwargs, app=app))
    port = free_port()

    cli.main(["serve", "--config", str(write_config(tmp_path, port=port))])

    assert recorded == {"app": "app", "host": "127.0.0.1", "port": port, "log_level": "info"}


def test_serve_flags_override_the_configured_host_and_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: dict[str, Any] = {}
    monkeypatch.setattr(cli, "create_app", lambda config: "app")
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: recorded.update(kwargs, app=app))

    cli.main(["serve", "--config", str(write_config(tmp_path)), "--host", "::1", "--port", "9999"])

    assert recorded["host"] == "::1"
    assert recorded["port"] == 9999


def test_a_missing_config_file_is_a_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["status", "--config", str(tmp_path / "absent.yaml")])

    assert caught.value.code == 2
    assert "Configuration error" in capsys.readouterr().err


def test_an_override_that_violates_the_bind_policy_is_a_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--host 0.0.0.0` must not quietly bypass the allow_remote requirement."""

    with pytest.raises(SystemExit) as caught:
        cli.main(["serve", "--config", str(write_config(tmp_path)), "--host", "0.0.0.0"])

    assert caught.value.code == 2
    assert "allow_remote" in capsys.readouterr().err


SUBSCRIPTION_READY = dataclasses.replace(READY, subscription_auth=True)


def write_remote_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "server:\n"
        "  host: 0.0.0.0\n"
        f"  port: {free_port()}\n"
        "  api_key: local-secret\n"
        "  allow_remote: true\n"
        "storage:\n"
        f"  sqlite_path: {tmp_path / 'gateway.db'}\n",
        encoding="utf-8",
    )
    return config_path


def test_doctor_warns_when_a_reachable_bind_shares_a_subscription(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(StubRegistry, "statuses_to_return", [SUBSCRIPTION_READY])

    with pytest.raises(SystemExit) as caught:
        cli.main(["doctor", "--config", str(write_remote_config(tmp_path))])

    # A warning, not a failed check: keeping the port private is a valid setup.
    assert caught.value.code == 0
    assert (
        "[WARN] Subscription sharing: signed in with a subscription: Codex."
        in capsys.readouterr().out
    )


def test_doctor_does_not_warn_about_api_key_logins(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["doctor", "--config", str(write_remote_config(tmp_path))])

    assert "Subscription sharing" not in capsys.readouterr().out


def test_doctor_does_not_warn_on_loopback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(StubRegistry, "statuses_to_return", [SUBSCRIPTION_READY])

    with pytest.raises(SystemExit):
        cli.main(["doctor", "--config", str(write_config(tmp_path))])

    assert "Subscription sharing" not in capsys.readouterr().out


def test_serve_warns_before_sharing_a_subscription(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(StubRegistry, "statuses_to_return", [SUBSCRIPTION_READY])
    monkeypatch.setattr(cli, "create_app", lambda config: "app")
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: None)

    cli.main(["serve", "--config", str(write_remote_config(tmp_path))])

    assert "Warning: signed in with a subscription: Codex." in capsys.readouterr().err


def installed_claude(
    monkeypatch: pytest.MonkeyPatch, version: tuple[int, ...] | None
) -> ClaudeProvider:
    claude = ClaudeProvider(ClaudeSettings(command="/bin/echo"))

    async def installed_version() -> tuple[int, ...] | None:
        return version

    monkeypatch.setattr(claude, "version", installed_version)
    monkeypatch.setattr(StubRegistry, "providers_to_return", {"claude": claude})
    return claude


@pytest.mark.parametrize(
    ("version", "line"),
    [
        ((2, 1, 312), "[PASS] Claude Code agent support: version 2.1.312"),
        (
            (2, 1, 200),
            "[WARN] Claude Code agent support: version 2.1.200; "
            "/v1/agents/run needs 2.1.248 or newer (optional)",
        ),
        (
            None,
            "[WARN] Claude Code agent support: version unknown; "
            "/v1/agents/run needs 2.1.248 or newer (optional)",
        ),
    ],
)
def test_doctor_reports_whether_claude_code_can_run_agents(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    version: tuple[int, ...] | None,
    line: str,
) -> None:
    installed_claude(monkeypatch, version)

    with pytest.raises(SystemExit) as caught:
        cli.main(["doctor", "--config", str(write_config(tmp_path))])

    # Agent support is optional, like each provider, so an old CLI only warns.
    assert caught.value.code == 0
    assert line in capsys.readouterr().out


def test_doctor_skips_the_agent_check_without_claude_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["doctor", "--config", str(write_config(tmp_path))])

    assert "agent support" not in capsys.readouterr().out
