"""Public model-name parsing shared by configuration, routing, and adapters."""

from __future__ import annotations

import re

AUTO_MODEL = "subscription/auto"

# Public alias prefix -> provider name. The prefixes are disjoint.
PROVIDER_PREFIXES: dict[str, str] = {
    "codex/": "codex",
    "claude-code/": "claude",
}

PROVIDER_PREFIX_BY_NAME: dict[str, str] = {
    name: prefix for prefix, name in PROVIDER_PREFIXES.items()
}

# Conservative charset for a value handed to a CLI as the argument of --model.
# The first character may be neither '-' (clap and commander reject or misparse
# a hyphen-leading option value) nor '.'; the body allows the dotted, colon-
# qualified, and hyphenated shapes both CLIs actually accept.
PROVIDER_MODEL_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._:-]{0,127}")

# Aliases advertised by earlier releases. They still resolve, but they are not
# listed by /v1/models, so model pickers show the current names only.
LEGACY_ALIASES: dict[str, tuple[str, str]] = {
    "claude-code/opus-5": ("claude", "opus"),
}


def is_valid_provider_model(value: str) -> bool:
    return bool(PROVIDER_MODEL_PATTERN.fullmatch(value))


def split_prefixed(public_model: str) -> tuple[str, str] | None:
    """Return (provider_name, suffix) for a known provider prefix, else None."""

    for prefix, provider_name in PROVIDER_PREFIXES.items():
        if public_model.startswith(prefix):
            return provider_name, public_model[len(prefix) :]
    return None
