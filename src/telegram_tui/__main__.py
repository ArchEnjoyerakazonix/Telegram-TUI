"""Entry point: run the TUI client (mock engine by default, Telethon for live)."""

from __future__ import annotations

import argparse
import os
import sys

from .config import ENV_MODE, EXAMPLE_CONFIG, Config
from .engine import MockEngine


def _config_error(exc: Exception) -> str:
    """Readable one-liner out of a pydantic ValidationError or a plain error."""
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return str(exc)
    messages = []
    for err in errors():
        msg = str(err.get("msg", "")).removeprefix("Value error, ")
        loc = ".".join(str(part) for part in err.get("loc", ()))
        messages.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(messages) or str(exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telegram-tui", description="Terminal Telegram client on Textual")
    parser.add_argument("--config", help="path to config.toml (default: ./config.toml or ~/.config/telegram-tui/config.toml)")
    parser.add_argument("--mode", choices=("mock", "live"), help="override startup mode (mock or live)")
    parser.add_argument("--no-traffic", action="store_true", help="run mock mode without background incoming traffic")
    parser.add_argument("--welcome", action="store_true", help="show welcome and mode selection screen")
    parser.add_argument("--print-config", action="store_true", help="print sample configuration and exit")
    parser.add_argument("--reset", action="store_true", help="clear session files, media cache, and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    import tempfile
    from pathlib import Path

    args = build_parser().parse_args(argv)
    if args.print_config:
        print(EXAMPLE_CONFIG)
        return 0

    if args.reset:
        cleared = []
        # Only the two places this client ever writes a session. Sweeping all of
        # $HOME would take other Telethon apps' sessions down with it.
        session_dirs = [Path("."), Path.home() / ".config" / "telegram-tui"]
        for pattern in ("*.session", "*.session-journal"):
            for directory in session_dirs:
                if not directory.exists():
                    continue
                for p in directory.glob(pattern):
                    p.unlink(missing_ok=True)
                    cleared.append(str(p))
        media_dir = Path(tempfile.gettempdir()) / "telegram-tui-media"
        if media_dir.exists():
            import shutil
            shutil.rmtree(media_dir, ignore_errors=True)
            cleared.append(str(media_dir))
        print(f"Cache and sessions cleared successfully ({len(cleared)} items removed).")
        return 0

    # --mode goes in as an override *before* validation, so `--mode mock` can
    # still rescue a config file whose live settings are incomplete.
    environ = dict(os.environ)
    if args.mode:
        environ[ENV_MODE] = args.mode

    try:
        config = Config.load(path=args.config, environ=environ)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:  # ValidationError and TOMLDecodeError are both ValueError
        print(f"Error: invalid configuration — {_config_error(exc)}", file=sys.stderr)
        print(
            "Hint: start the offline demo with --mode mock, "
            "or print a sample config with --print-config.",
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
