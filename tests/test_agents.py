from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeProvider
from fastapi.testclient import TestClient

from subscription_gateway.api.agents import validate_agent_cwd
from subscription_gateway.errors import GatewayError


def test_agent_path_validation(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    project = allowed / "project"
    project.mkdir(parents=True)
    assert validate_agent_cwd(project, [allowed], False) == project.resolve()


def test_agent_path_outside_allowed_is_rejected(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    with pytest.raises(GatewayError) as caught:
        validate_agent_cwd(outside, [allowed], False)
    assert caught.value.error_type == "agent_permission_error"


def test_agent_endpoint_defaults_to_read_only(
    client: TestClient, fake_codex: FakeProvider, tmp_path: Path
) -> None:
    response = client.post(
        "/v1/agents/run",
        json={
            "model": "codex/gpt-5.6-sol",
            "prompt": "Inspect tests",
            "cwd": str(tmp_path),
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert fake_codex.calls[0]["options"]["permissions"] == "read-only"
