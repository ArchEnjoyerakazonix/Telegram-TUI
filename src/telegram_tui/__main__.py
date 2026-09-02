"""Entry point: run the TUI client with the mock engine."""

from __future__ import annotations

import sys

from .app import TelegramTUI


def main() -> int:
    app = TelegramTUI(live_traffic="--no-traffic" not in sys.argv)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
