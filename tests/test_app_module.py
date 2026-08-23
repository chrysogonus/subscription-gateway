"""The module-level ASGI app must stay lazy.

`subscription_gateway.main` is imported by the CLI, so anything it does at
import time happens on every `subscription-gateway --version`. Building the app
there loaded and validated the configuration, which crashed the container image
outright: its ENV asks for a non-loopback bind, and no API key exists until one
is supplied at run time.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI

from subscription_gateway import main as main_module


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    """create_app calls configure_logging, which replaces the root handlers."""

    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    try:
        yield
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)


def test_importing_main_does_not_build_an_app() -> None:
    assert "app" not in vars(main_module), (
        "subscription_gateway.main built an app at import time; "
        "importing it must stay free of configuration loading"
    )


def test_the_asgi_target_still_resolves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`uvicorn subscription_gateway.main:app` has to keep working."""

    monkeypatch.setenv("GATEWAY_SQLITE_PATH", str(tmp_path / "gateway.db"))

    assert isinstance(main_module.app, FastAPI)


def test_an_unknown_attribute_still_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(AttributeError):
        main_module.not_a_real_attribute  # noqa: B018


def test_the_asgi_target_reports_configuration_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deferring construction must not swallow a genuinely broken config."""

    monkeypatch.setenv("GATEWAY_HOST", "0.0.0.0")
    monkeypatch.setenv("GATEWAY_ALLOW_REMOTE", "true")
    monkeypatch.delenv("GATEWAY_API_KEY", raising=False)

    with pytest.raises(ValueError, match="requires a local gateway API key"):
        _ = main_module.app
