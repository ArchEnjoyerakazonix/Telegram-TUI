"""Configuration: mock vs live mode, API credentials, media tooling.

Lookup order (later wins):
  1. built-in defaults
  2. --config file (or ./config.toml, then ~/.config/telegram-tui/config.toml)
  3. environment variables TG_TUI_MODE / TG_TUI_API_ID / TG_TUI_API_HASH
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ENV_MODE = "TG_TUI_MODE"
ENV_API_ID = "TG_TUI_API_ID"
ENV_API_HASH = "TG_TUI_API_HASH"

DEFAULT_CONFIG_PATHS = (
    Path("config.toml"),
    Path.home() / ".config" / "telegram-tui" / "config.toml",
)

EXAMPLE_CONFIG = """\
# telegram-tui configuration
mode = "mock"            # "mock" — симуляция, "live" — реальный аккаунт

# Обязательно для mode = "live": получите на https://my.telegram.org
# api_id = 12345
# api_hash = "0123456789abcdef0123456789abcdef"
# session = "telegram-tui"   # имя файла сессии Telethon

# Медиа (необязательно):
# media_player = "mpv"     # проигрыватель голосовых сообщений
# photo_renderer = "chafa" # рендер превью фото в терминале
"""


class Config(BaseModel):
    mode: Literal["mock", "live"] = "mock"
    api_id: int | None = None
    api_hash: str | None = None
    session: str = "telegram-tui"
    media_player: str = "mpv"
    photo_renderer: str = "chafa"
    traffic_interval: float = Field(default=6.0, gt=0)

    @classmethod
    def load(
        cls,
        path: Path | str | None = None,
        environ: dict | None = None,
    ) -> "Config":
        env = os.environ if environ is None else environ
        data: dict = {}

        if path is not None:
            p = Path(path)
            if not p.exists():
                raise FileNotFoundError(f"config file not found: {p}")
            data = tomllib.loads(p.read_text(encoding="utf-8"))
        else:
            for candidate in DEFAULT_CONFIG_PATHS:
                if candidate.exists():
                    data = tomllib.loads(candidate.read_text(encoding="utf-8"))
                    break

        if env.get(ENV_MODE):
            data["mode"] = env[ENV_MODE]
        if env.get(ENV_API_ID):
            data["api_id"] = int(env[ENV_API_ID])
        if env.get(ENV_API_HASH):
            data["api_hash"] = env[ENV_API_HASH]

        cfg = cls(**data)
        if cfg.mode == "live" and (not cfg.api_id or not cfg.api_hash):
            raise ValueError(
                'mode = "live" требует api_id и api_hash: '
                "укажите их в config.toml или через TG_TUI_API_ID / TG_TUI_API_HASH "
                "(получить на https://my.telegram.org)"
            )
        return cfg
