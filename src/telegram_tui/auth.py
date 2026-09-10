"""In-terminal Telegram authorization: phone → SMS code → 2FA password."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from .backend import BaseBackend

_STEPS = {
    "phone": ("Вход в Telegram", "Номер телефона (например, +79990001122)…", False),
    "code": ("Код подтверждения", "Код из Telegram/SMS…", False),
    "password": ("Двухфакторная аутентификация", "Облачный пароль (ввод скрыт)…", True),
}


class LoginScreen(ModalScreen[bool]):
    """Step-by-step login dialog driven by the backend's sign-in methods."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    LoginScreen { align: center middle; background: $background 60%; }
    #auth-box {
        width: 64;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: round $accent;
    }
    #auth-title { text-style: bold; margin-bottom: 1; }
    #auth-error { color: $error; min-height: 1; margin-top: 1; }
    #auth-hint { color: $text-muted; margin-top: 1; }
    """

    def __init__(self, backend: BaseBackend) -> None:
        super().__init__()
        self.backend = backend
        self.step = "phone"

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="auth-box"):
                title, placeholder, password = _STEPS[self.step]
                yield Static(title, id="auth-title")
                yield Input(placeholder=placeholder, password=password, id="auth-input")
                yield Static("", id="auth-error")
                yield Static(
                    "Enter — продолжить, Esc — отмена. "
                    "Код придёт в Telegram или по SMS.",
                    id="auth-hint",
                )

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "auth-input" or event.input.disabled:
            return
        value = event.value.strip()
        error = self.query_one("#auth-error", Static)
        if not value:
            return
        event.input.disabled = True
        error.update("…")
        try:
            if self.step == "phone":
                await self.backend.request_code(value)
                self._switch("code")
            elif self.step == "code":
                try:
                    await self.backend.submit_code(value)
                except self.backend.PasswordNeededError:
                    self._switch("password")
                    return
                await self._finish()
            elif self.step == "password":
                await self.backend.submit_password(value)
                await self._finish()
        except Exception as exc:  # noqa: BLE001 - show any backend error inline
            error.update(f"Ошибка: {exc}")
            event.input.disabled = False
            event.input.focus()

    def _switch(self, step: str) -> None:
        self.step = step
        title, placeholder, password = _STEPS[step]
        self.query_one("#auth-title", Static).update(title)
        error = self.query_one("#auth-error", Static)
        error.update("…")
        if step == "password":
            error.update("Требуется облачный пароль (2FA)")
        inp = self.query_one(Input)
        inp.value = ""
        inp.placeholder = placeholder
        inp.password = password
        inp.disabled = False
        inp.focus()

    async def _finish(self) -> None:
        self.query_one("#auth-error", Static).update("✅ Успешно, загружаю чаты…")
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class WelcomeScreen(ModalScreen[str]):
    """Welcome and onboarding screen: choose between real Telegram and mock demo."""

    BINDINGS = [("escape", "choose_demo", "Explore Demo")]

    DEFAULT_CSS = """
    WelcomeScreen { align: center middle; background: #000000 70%; }
    #welcome-box {
        width: 68;
        height: auto;
        padding: 2 3;
        background: #16161e;
        border: heavy #b7e680;
    }
    #welcome-badge { color: #b7e680; text-style: bold; margin-bottom: 1; }
    #welcome-title { text-style: bold; color: #f0f0f0; margin-bottom: 1; }
    #welcome-desc { color: #a9b1d6; margin-bottom: 1; }
    .welcome-btn {
        width: 1fr;
        margin-bottom: 1;
        background: #24283b;
        color: #f0f0f0;
        border: tall #414868;
    }
    .welcome-btn:focus, .welcome-btn:hover {
        background: #b7e680;
        color: #111413;
        text-style: bold;
    }
    #welcome-note { color: #565f89; margin-top: 1; text-align: center; }
    """

    def compose(self) -> ComposeResult:
        from textual.widgets import Button

        with Center():
            with Vertical(id="welcome-box"):
                yield Static("⚡ TELEGRAM / TUI  •  v0.4.0", id="welcome-badge")
                yield Static("Твой Telegram. Полностью в терминале.", id="welcome-title")
                yield Static(
                    "Быстрый, легковесный TUI-клиент для клавиатурного управления.\n"
                    "Выберите способ запуска:",
                    id="welcome-desc",
                )
                yield Button("🚀 Войти в реальный Telegram (Telethon)", id="btn-login", classes="welcome-btn")
                yield Button("🎭 Запустить Демо-режим (Mock Workspace)", id="btn-demo", classes="welcome-btn")
                yield Static(
                    "Конфигурация хранится в ~/.config/telegram-tui/config.toml\n"
                    "[Esc / Enter] для быстрого выбора демо-режима",
                    id="welcome-note",
                )

    def on_button_pressed(self, event) -> None:  # noqa: ANN001
        if getattr(event.button, "id", None) == "btn-login":
            self.dismiss("login")
        else:
            self.dismiss("demo")

    def action_choose_demo(self) -> None:
        self.dismiss("demo")


class ApiCredentialsScreen(ModalScreen[tuple[int, str] | None]):
    """Modal dialog to input and save Telegram API ID and API Hash."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ApiCredentialsScreen { align: center middle; background: #000000 70%; }
    #api-box {
        width: 72;
        height: auto;
        padding: 2 3;
        background: #16161e;
        border: heavy #7aa2f7;
    }
    #api-title { color: #7aa2f7; text-style: bold; margin-bottom: 1; }
    #api-desc { color: #a9b1d6; margin-bottom: 1; }
    #api-error { color: #f7768e; margin-bottom: 1; height: 1; }
    #api-box Input {
        margin-bottom: 1;
        background: #1f2335;
        border: solid #3b4261;
        color: #c0caf5;
    }
    #api-box Input:focus { border: solid #b7e680; }
    .api-btn {
        width: 1fr;
        margin-bottom: 1;
        background: #24283b;
        color: #f0f0f0;
        border: tall #414868;
    }
    .api-btn:focus, .api-btn:hover {
        background: #b7e680;
        color: #111413;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        from textual.widgets import Button

        with Center():
            with Vertical(id="api-box"):
                yield Static("🔑 Настройка Telegram API", id="api-title")
                yield Static(
                    "Для прямого подключения требуются api_id и api_hash.\n"
                    "Их можно бесплатно получить на https://my.telegram.org -> 'API development tools'.",
                    id="api-desc",
                )
                yield Static("", id="api-error")
                yield Input(placeholder="App api_id (число, например 12345678)", id="input-api-id")
                yield Input(placeholder="App api_hash (строка 32 символа)", id="input-api-hash")
                yield Button("💾 Сохранить и перейти к авторизации", id="btn-save-api", classes="api-btn")
                yield Button("Отмена (вернуться в Демо-режим)", id="btn-cancel-api", classes="api-btn")

    def on_button_pressed(self, event) -> None:  # noqa: ANN001
        if getattr(event.button, "id", None) == "btn-save-api":
            self._submit()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "input-api-id":
            self.query_one("#input-api-hash", Input).focus()
        else:
            self._submit()

    def _submit(self) -> None:
        raw_id = self.query_one("#input-api-id", Input).value.strip()
        raw_hash = self.query_one("#input-api-hash", Input).value.strip()
        error = self.query_one("#api-error", Static)

        if not raw_id:
            error.update("Укажите api_id")
            self.query_one("#input-api-id", Input).focus()
            return
        try:
            api_id = int(raw_id)
        except ValueError:
            error.update("api_id должен быть целым числом")
            self.query_one("#input-api-id", Input).focus()
            return

        if not raw_hash:
            error.update("Укажите api_hash")
            self.query_one("#input-api-hash", Input).focus()
            return

        self.dismiss((api_id, raw_hash))

    def action_cancel(self) -> None:
        self.dismiss(None)

