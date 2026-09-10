"""Entry point: run the TUI client (mock engine by default, Telethon for live)."""

from __future__ import annotations

import argparse
import sys

from .config import EXAMPLE_CONFIG, Config
from .engine import MockEngine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telegram-tui", description="Terminal Telegram client on Textual")
    parser.add_argument("--config", help="path to config.toml (default: ./config.toml or ~/.config/telegram-tui/config.toml)")
    parser.add_argument("--mode", choices=("mock", "live"), help="override startup mode (mock or live)")
    parser.add_argument("--no-traffic", action="store_true", help="run mock mode without background incoming traffic")
    parser.add_argument("--welcome", action="store_true", help="show welcome and mode selection screen")
    parser.add_argument("--print-config", action="store_true", help="print sample configuration and exit")
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
                'Error: mode = "live" requires api_id and api_hash '
                "(config.toml or TG_TUI_API_ID / TG_TUI_API_HASH env vars).",
                file=sys.stderr,
            )
            return 2

    if config.mode == "live":
        from .telethon_backend import TelethonBackend

        engine = TelethonBackend(config.api_id, config.api_hash, config.session)
    else:
        engine = MockEngine()

    from pathlib import Path
    from .app import TelegramTUI

    show_welcome = args.welcome
    if not args.mode and not args.config:
        has_cfg = Path("config.toml").exists() or (Path.home() / ".config" / "telegram-tui" / "config.toml").exists()
        if not has_cfg and not config.api_id:
            show_welcome = True

    app = TelegramTUI(
        engine=engine,
        live_traffic=not args.no_traffic,
        config=config,
        show_welcome=show_welcome,
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
