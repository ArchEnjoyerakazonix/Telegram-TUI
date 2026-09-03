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
