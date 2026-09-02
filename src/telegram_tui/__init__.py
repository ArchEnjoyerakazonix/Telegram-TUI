"""telegram-tui — terminal Telegram client on Textual (mock engine)."""

from .app import TelegramTUI
from .engine import MockEngine

__all__ = ["TelegramTUI", "MockEngine"]
__version__ = "0.1.0"
