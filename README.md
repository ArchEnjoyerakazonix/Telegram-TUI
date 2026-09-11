# telegram-tui

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Textual](https://img.shields.io/badge/TUI-Textual-00d2ff.svg?style=flat-square)](https://textual.textualize.io/)
[![Telethon](https://img.shields.io/badge/MTProto-Telethon-2ca5e0.svg?style=flat-square&logo=telegram&logoColor=white)](https://github.com/LonamiWebs/Telethon)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)
[![Tests: 178 Passed](https://img.shields.io/badge/tests-178%20passed-brightgreen.svg?style=flat-square)](tests/)

A modern, high-performance, keyboard-driven terminal client for Telegram built with [Textual](https://textual.textualize.io/) and [Telethon](https://github.com/LonamiWebs/Telethon).

Features a high-contrast three-panel interface, native terminal media rendering (`chafa`), background audio playback (`mpv`), floating PIP video notes, interactive first-run onboarding wizard, full Vim navigation, and an offline mock engine for zero-setup experimentation.

---

## Key Highlights

- **Seamless First-Run Onboarding**: Automatic terminal wizard detects missing API keys and prompts you to input credentials or explore in Mock mode. Generates `~/.config/telegram-tui/config.toml` automatically.
- **Full In-Terminal Media Pipeline**:
  - **Photos**: Rendered directly in message feed using `chafa` (auto-detecting Kitty graphics protocol, Sixel, or 24-bit half-blocks).
  - **Voice Messages**: Rendered with dynamic Unicode audio waveforms (` ▂▃▅▆▇`) and direct background playback via `mpv` (hotkey `v`).
  - **Video Notes (Circles)**: One-key popout to floating PIP window via `mpv` (hotkey `o` or `v`).
  - **Stickers & Reactions**: Rendered with emoji fallbacks (`🎭 sticker: [emoji]`) and quick numeric reactions (`1`–`5`: 👍, ❤️, 🔥, 🎉, 🤔).
  - **Every Other Attachment**: Videos, GIFs, music and documents are named, sized and timed inline — `report.pdf · 2.1 MB`, `🎬 Video · 0:45 · 12.4 MB` — and open in an external viewer with `o`.
  - **Sending Files**: `Ctrl+R` opens a picker with Tab-completing path entry and a directory tree; the composer's text rides along as the caption, and files can be sent uncompressed.
- **Three-Panel Layout**:
  - **Sidebar**: Search filtering (`/` or `Ctrl+F`), pinned chats (`Ctrl+P`), unread badge counters, and chat type badges (Private, Group, Channel).
  - **Chat Feed**: Markdown and fenced code syntax highlighting, reply chains (`↱`), pagination banner for older messages (`Ctrl+O`), and read-only channel protection.
  - **Composer**: Expandable multiline editor (`Alt+Enter` for newline, `Ctrl+G` to toggle height) with active reply indicators.
- **Vim-Centric Navigation**: Smooth navigation with `j`/`k`, `gg`/`G`, in-chat search (`/` and `n`/`N`), and instant quote replies (`r`).
- **Dual Engine Architecture**:
  - **Live Mode**: Real-time MTProto connection through Telethon with secure phone, SMS, and 2FA cloud password authentication.
  - **Mock Mode**: Fully offline simulated account with 10 pre-seeded conversations, active background traffic, and automated bot replies.

---

## Installation

### Prerequisites

- Python 3.11 or newer
- *(Optional)* [`chafa`](https://hpjansson.org/chafa/) — For in-terminal image previews
- *(Optional)* [`mpv`](https://mpv.io/) — For audio voice playback and floating PIP video notes

On Arch Linux:
```bash
sudo pacman -S chafa mpv python
```

On Ubuntu / Debian:
```bash
sudo apt update && sudo apt install chafa mpv python3 python3-venv
```

On macOS (Homebrew):
```bash
brew install chafa mpv python
```

### Install Telegram TUI

```bash
# Clone repository
git clone https://github.com/ArchEnjoyerakazonix/Telegram-TUI.git
cd Telegram-TUI

# Set up virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in editable mode, with Telethon for live mode
pip install -e ".[live]"

# Mock mode only (no Telegram connection) needs no extras:
# pip install -e .
```

---

## Quick Start

Launch the client from any terminal:

```bash
telegram-tui
```

On your first run:
1. If no configuration exists, the **Onboarding Wizard** will appear.
2. Select **"Enter API Credentials"** to connect your Telegram account, or **"Explore Mock Mode"** to try out the client with simulated data.
3. If connecting your real account, enter your phone number (`+1...`), the verification code sent to your Telegram apps, and your 2FA password (if enabled). Your session is safely preserved in `telegram-tui.session`.

---

## Configuration

Credentials can be supplied via configuration file or environment variables.

### Config File (`~/.config/telegram-tui/config.toml`)

You can create or edit `~/.config/telegram-tui/config.toml` (or `./config.toml`):

```toml
mode = "live"
api_id = 12345678
api_hash = "0123456789abcdef0123456789abcdef"
session = "telegram-tui"

# Optional media tools
media_player = "mpv"     # Voice and video playback
photo_renderer = "chafa" # In-terminal image rendering
```

> **Note**: You can obtain your `api_id` and `api_hash` freely from [my.telegram.org](https://my.telegram.org) under **API Development Tools**.

### Environment Variables

Alternatively, configure using environment variables:

```bash
export TG_TUI_MODE=live
export TG_TUI_API_ID=12345678
export TG_TUI_API_HASH=0123456789abcdef0123456789abcdef
telegram-tui
```

---

## Hotkeys & Keyboard Navigation

Telegram TUI is built for speed and fully navigable without a mouse.

### Global & Focus

| Key | Action |
|---|---|
| `Tab` / `Shift+Tab` | Cycle focus between Panels (Chat List ↔ Feed ↔ Input) |
| `Ctrl+↑` / `Ctrl+↓` | Switch focus between panels |
| `Ctrl+Q` | Quit application |
| `Esc` | Cancel reply, dismiss dialogs, or clear search |

### Chat List (Left Panel)

| Key | Action |
|---|---|
| `j` / `k` or `↓` / `↑` | Move down / up the chat list |
| `/` or `Ctrl+F` | Filter / search chat list |
| `Enter` | Select and open chat |
| `Ctrl+P` | Pin / unpin selected chat 📌 |
| `Ctrl+M` | Mark chat as read |
| `Ctrl+U` | Simulate incoming message *(mock mode only)* |

### Message Feed (Center Panel)

| Key | Action |
|---|---|
| `j` / `k` or `↓` / `↑` | Navigate messages up / down |
| `gg` / `G` | Jump to oldest / newest message |
| `r` | Quote-reply to selected message |
| `v` | Play voice note or open video note in `mpv` |
| `s` | Stop background audio playback |
| `z` | Expand / collapse an inline photo |
| `o` | Open photo/video in external viewer or `mpv` PIP |
| `1` – `5` | Add quick reaction (👍, ❤️, 🔥, 🎉, 🤔) |
| `Ctrl+O` | Load older message history from server |
| `/` | Search inside current chat feed |
| `n` / `N` | Jump to next / previous search match in feed |

### Message Composer (Bottom Panel)

| Key | Action |
|---|---|
| `Enter` | Send message |
| `Alt+Enter` | Insert newline (multiline text) |
| `Ctrl+R` | Attach a file (the typed text becomes its caption) |
| `Ctrl+G` | Expand / collapse input box height |
| `Esc` | Cancel current reply quote |

---

## Architecture & Codebase

```
telegram-tui/
├── src/telegram_tui/
│   ├── app.py                 # Core Textual App & event bindings
│   ├── auth.py                # Onboarding & Auth screens (Credentials, Phone, 2FA)
│   ├── config.py              # TOML config loader, env parser & persistence
│   ├── engine.py              # Deterministic mock engine for offline testing
│   ├── media.py               # Chafa terminal rendering & MPV subprocess manager
│   ├── models.py              # Pure data models (Chat, Message, Media, Reaction)
│   ├── telethon_backend.py    # Production Telethon MTProto client implementation
│   └── widgets/
│       ├── chat_list.py       # Sidebar chat items with badges & search
│       ├── chat_view.py       # Message bubbles, waveforms, syntax highlighting
│       ├── attach.py          # File picker: path completion + directory tree
│       ├── composer.py        # Multiline composer with reply bar
│       └── photo.py           # Inline ASCII/Sixel/Kitty image renderer
├── tests/
│   ├── conftest.py            # Isolates HOME and blocks network for every test
│   ├── test_adversarial.py    # Adversarial & stress tests, incl. live-mode mapping
│   ├── test_attach.py         # File picker & upload tests
│   ├── test_auth.py           # Full auth modal lifecycle & 2FA tests
│   ├── test_cli.py            # Entry point: config errors & --mode overrides
│   ├── test_config.py         # Config priority, parsing & persistence tests
│   ├── test_engine.py         # Mock engine state & conversation simulation tests
│   ├── test_features_mvp.py   # MVP feature validation tests
│   ├── test_media.py          # Chafa protocol detection & MPV invocation tests
│   └── test_ui.py             # Textual Pilot end-to-end user journey tests
├── pyproject.toml
└── README.md
```

---

## Testing

Telegram TUI features an exhaustive test suite covering unit logic, adversarial error handling, async network dropouts, rate limiting (FloodWait), and end-to-end terminal interactions:

```bash
# Run full test suite
pytest tests/

# Run with verbose output
pytest -v tests/
```

**178 tests** passing across all subsystems:
- ✅ **Adversarial & Resilience**: Simulates MTProto FloodWait, RPC errors, corrupted credentials, missing media tools, and network drops.
- ✅ **Authentication**: Tests full onboarding state machine: phone entry, verification code, invalid codes, 2FA cloud passwords, and dismissal.
- ✅ **Media Processing**: Validates waveform rendering, MPV background process spawning, and Chafa graphics protocol negotiation.
- ✅ **UI Pilot**: Tests real keyboard interactions, Vim motions, search filtering, quoting, pagination, and dynamic window resizing (`SIGWINCH`).

---

## License

This project is licensed under the [MIT License](LICENSE).
