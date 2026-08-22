from __future__ import annotations

from conftest import FakeProvider

from subscription_gateway import __version__
from subscription_gateway.config import GatewayConfig
from subscription_gateway.main import create_app


def test_version_is_reported() -> None:
    assert __version__
    assert __version__ != "0.0.0+unknown", "install the package (make dev) before running tests"


def test_app_version_matches_package(
    gateway_config: GatewayConfig, fake_codex: FakeProvider
) -> None:
    # Guards against the version being hardcoded in the FastAPI constructor again.
    app = create_app(gateway_config, providers={"codex": fake_codex})
    assert app.version == __version__
