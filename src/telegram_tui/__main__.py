"""Entry point: run the TUI client (mock engine by default, Telethon for live)."""

from __future__ import annotations

import argparse
import sys

from .config import EXAMPLE_CONFIG, Config
from .engine import MockEngine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telegram-tui", description="Terminal Telegram client on Textual")
    parser.add_argument("--config", help="путь к config.toml (по умолчанию ./config.toml или ~/.config/telegram-tui/config.toml)")
    parser.add_argument("--mode", choices=("mock", "live"), help="переопределить режим из конфига")
    parser.add_argument("--no-traffic", action="store_true", help="mock-режим без фонового входящего трафика")
    parser.add_argument("--print-config", action="store_true", help="показать пример конфигурации и выйти")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.print_config:
        print(EXAMPLE_CONFIG)
        return 0

    config = Config.load(path=args.config)
    if args.mode:
        config.mode = args.mode
        if config.mode == "live" and (not config.api_id or not config.api_hash):
            print(
                'Ошибка: mode = "live" требует api_id и api_hash '
                "(config.toml или переменные TG_TUI_API_ID / TG_TUI_API_HASH).",
                file=sys.stderr,
            )
            return 2

    if config.mode == "live":
        from .telethon_backend import TelethonBackend

        engine = TelethonBackend(config.api_id, config.api_hash, config.session)
    else:
        engine = MockEngine()

    from .app import TelegramTUI

    app = TelegramTUI(engine=engine, live_traffic=not args.no_traffic, config=config)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
