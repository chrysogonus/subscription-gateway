from __future__ import annotations

import re
from pathlib import Path

from conftest import FakeProvider

from subscription_gateway import __version__
from subscription_gateway.config import GatewayConfig
from subscription_gateway.main import create_app

REPO_ROOT = Path(__file__).parents[1]


def test_version_is_reported() -> None:
    assert __version__
    assert __version__ != "0.0.0+unknown", "install the package (make dev) before running tests"


def test_app_version_matches_package(
    gateway_config: GatewayConfig, fake_codex: FakeProvider
) -> None:
    # Guards against the version being hardcoded in the FastAPI constructor again.
    app = create_app(gateway_config, providers={"codex": fake_codex})
    assert app.version == __version__


def test_current_version_has_a_dated_changelog_section() -> None:
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(
        rf"^## \[{re.escape(__version__)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M
    )
