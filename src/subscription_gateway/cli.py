"""Local command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import socket
import sqlite3
import sys
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from subscription_gateway import __version__
from subscription_gateway.config import GatewayConfig, load_config
from subscription_gateway.main import create_app
from subscription_gateway.model_names import PROVIDER_PREFIX_BY_NAME
from subscription_gateway.providers.registry import ProviderRegistry
from subscription_gateway.sessions.storage import SQLiteSessionStorage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="subscription-gateway")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("serve", "status", "doctor"):
        command = subparsers.add_parser(name)
        command.add_argument("--config", type=Path)
        if name == "serve":
            command.add_argument("--host")
            command.add_argument("--port", type=int)
    return parser


def _load(args: argparse.Namespace) -> GatewayConfig:
    config = load_config(args.config)
    if getattr(args, "host", None) is None and getattr(args, "port", None) is None:
        return config
    data = config.model_dump(mode="python")
    if args.host is not None:
        data["server"]["host"] = args.host
    if args.port is not None:
        data["server"]["port"] = args.port
    return GatewayConfig.model_validate(data)


async def _status(config: GatewayConfig) -> int:
    statuses = await ProviderRegistry(config).statuses()
    print("Subscription LLM Gateway")
    print()
    print("Server:")
    print(f"  http://{config.server.host}:{config.server.port}/v1")
    print()
    print("Providers:")
    for provider in statuses:
        state = "ready" if provider.available else "unavailable"
        print()
        print(f"  {provider.display_name}")
        print(f"    installed: {_yes_no(provider.installed)}")
        print(f"    authenticated: {_yes_no(provider.authenticated)}")
        print(f"    status: {state}")
        print("    models:")
        for model in provider.models:
            print(f"      {model}")
        prefix = PROVIDER_PREFIX_BY_NAME.get(provider.name)
        if prefix:
            print(f"      (plus any other model the CLI accepts, as {prefix}<model>)")
    return 0


async def _doctor(config: GatewayConfig) -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(
        (
            "Python version",
            sys.version_info >= (3, 12),
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
    )
    checks.append(("Configuration", True, "valid"))

    statuses = await ProviderRegistry(config).statuses()
    for provider in statuses:
        checks.append(
            (
                f"{provider.display_name} installation",
                provider.installed,
                "found" if provider.installed else "not found (optional)",
            )
        )
        checks.append(
            (
                f"{provider.display_name} authentication",
                provider.authenticated,
                "ready" if provider.authenticated else "not detected (optional)",
            )
        )

    storage_ok, storage_detail = await _check_storage(config.storage.sqlite_path)
    checks.append(("SQLite storage", storage_ok, storage_detail))
    port_ok = _port_available(config.server.host, config.server.port)
    checks.append(
        (
            "Server port",
            port_ok,
            f"{config.server.host}:{config.server.port} "
            + ("available" if port_ok else "already in use"),
        )
    )

    print("Subscription LLM Gateway doctor")
    print()
    for name, ok, detail in checks:
        marker = "PASS" if ok else "WARN"
        print(f"[{marker}] {name}: {detail}")

    required_ok = checks[0][1] and storage_ok and port_ok
    if not any(provider.available for provider in statuses):
        print()
        print("No provider is currently ready; the server can still start and report health.")
    return 0 if required_ok else 1


async def _check_storage(path: Path) -> tuple[bool, str]:
    storage = SQLiteSessionStorage(path)
    try:
        await storage.initialize()
        await storage.close()
    except (OSError, sqlite3.Error) as exc:
        return False, f"not writable ({exc.__class__.__name__})"
    return True, str(path)


def _port_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
    except OSError:
        return False
    return True


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        config = _load(args)
    except (OSError, ValueError, ValidationError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if args.command == "serve":
        uvicorn.run(
            create_app(config),
            host=config.server.host,
            port=config.server.port,
            log_level=config.logging.level.lower(),
        )
        return
    exit_code = asyncio.run(_status(config) if args.command == "status" else _doctor(config))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
