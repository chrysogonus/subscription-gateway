"""Log formatting and the secret-redaction guarantee.

SECURITY.md treats "credentials or secrets appearing in logs" as an in-scope
vulnerability, so the redaction helper needs a test that fails when it stops
being applied.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest

from subscription_gateway import logging as logging_module
from subscription_gateway.config import LoggingSettings
from subscription_gateway.logging import (
    JsonFormatter,
    configure_logging,
    redact_mapping,
)


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    """configure_logging replaces the root handlers; give them back afterwards."""

    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    try:
        yield
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)


def make_record(**extra: Any) -> logging.LogRecord:
    record = logging.LogRecord(
        name="subscription_gateway.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


@pytest.mark.parametrize(
    "field",
    ["api_key", "API_KEY", "GATEWAY_API_KEY", "auth_token", "client_secret", "db_password"],
)
def test_redact_mapping_masks_secret_bearing_names(field: str) -> None:
    assert redact_mapping({field: "s3cret"}) == {field: "***"}


def test_redact_mapping_leaves_ordinary_fields_alone() -> None:
    values = {"model": "codex/gpt-5.6-sol", "duration_ms": 12.5, "status": 200}

    assert redact_mapping(values) == values


def test_json_formatter_emits_the_structured_fields() -> None:
    record = make_record(request_id="req-1", provider="codex", model="gpt-5.6-sol", status=200)

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "subscription_gateway.test"
    assert payload["message"] == "hello world"
    assert payload["request_id"] == "req-1"
    assert payload["provider"] == "codex"
    assert payload["status"] == 200
    assert "timestamp" in payload


def test_json_formatter_omits_fields_the_record_does_not_carry() -> None:
    payload = json.loads(JsonFormatter().format(make_record()))

    assert "request_id" not in payload
    assert "queue_delay_ms" not in payload


def test_json_formatter_applies_the_redaction_pass() -> None:
    """The formatter runs every payload through redact_mapping before serializing.

    No field in the current allowlist trips a marker, so this asserts the wiring
    rather than an observable mask: it fails if the pass is removed, which is
    what keeps the next secret-bearing field from shipping unmasked.
    """

    calls: list[dict[str, Any]] = []
    original = logging_module.redact_mapping

    def spy(values: Any) -> dict[str, Any]:
        result = original(values)
        calls.append(result)
        return result

    formatter = JsonFormatter()
    logging_module.redact_mapping = spy
    try:
        payload = json.loads(formatter.format(make_record(request_id="req-1")))
    finally:
        logging_module.redact_mapping = original

    assert calls, "JsonFormatter.format did not run the payload through redact_mapping"
    assert payload["request_id"] == "req-1"


def test_json_formatter_serializes_unserializable_values() -> None:
    payload = json.loads(JsonFormatter().format(make_record(model=object())))

    assert payload["model"].startswith("<object object at")


def test_configure_logging_installs_a_json_handler() -> None:
    configure_logging(LoggingSettings(level="DEBUG", json=True))

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


def test_configure_logging_defaults_to_plain_text() -> None:
    configure_logging(LoggingSettings())

    root = logging.getLogger()
    assert root.level == logging.INFO
    assert len(root.handlers) == 1
    assert not isinstance(root.handlers[0].formatter, JsonFormatter)
