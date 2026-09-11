"""In-terminal Telegram authorization: phone → SMS code → 2FA password."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from .backend import BaseBackend

_STEPS = {
    "phone": ("Telegram Sign In", "Phone number (e.g. +1234567890)...", False),
    "code": ("Confirmation Code", "Code from Telegram / SMS...", False),
    "password": ("Two-Factor Authentication", "Cloud password (hidden input)...", True),
}


class LoginScreen(ModalScreen[bool]):
    """Step-by-step login dialog driven by the backend's sign-in methods."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    LoginScreen { align: center middle; background: #000000 70%; }
    #auth-box {
        width: 100%;
        max-width: 70;
        height: auto;
        max-height: 100%;
        overflow-y: auto;
        padding: 1 2;
        background: #16161e;
        border: heavy #7aa2f7;
    }
    #auth-title { text-style: bold; color: #7aa2f7; margin-bottom: 1; }
    #auth-error { color: #f7768e; min-height: 1; margin-top: 1; }
    #auth-hint { color: #a9b1d6; margin-bottom: 1; }
    #auth-box Input {
        margin-bottom: 1;
        background: #1f2335;
        border: solid #414868;
        color: #c0caf5;
    }
    #auth-box Input:focus {
        border: solid #b7e680;
    }
    .auth-btn {
        width: 1fr;
        margin-bottom: 1;
    }
    """

    def __init__(self, backend: BaseBackend) -> None:
        super().__init__()
        self.backend = backend
        self.step = "phone"

    def compose(self) -> ComposeResult:
        from textual.widgets import Button

        with Center():
            with Vertical(id="auth-box"):
                title, placeholder, password = _STEPS[self.step]
                yield Static(f"🔑 {title}", id="auth-title")
                yield Input(placeholder=placeholder, password=password, id="auth-input")
                yield Static("", id="auth-error", markup=False)
                yield Static(
                    "Enter to submit, Esc to cancel. Code arrives in Telegram or by SMS.",
                    id="auth-hint",
                )
                yield Button("Continue (Enter)", id="btn-auth-submit", classes="auth-btn btn-primary")
                yield Button("Cancel (Esc)", id="btn-auth-cancel", classes="auth-btn btn-secondary")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_button_pressed(self, event) -> None:  # noqa: ANN001
        btn_id = getattr(event.button, "id", None)
        if btn_id == "btn-auth-submit":
            inp = self.query_one("#auth-input", Input)
            self.post_message(Input.Submitted(inp, inp.value))
        elif btn_id == "btn-auth-cancel":
            self.dismiss(False)

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
            error.update(f"Error: {exc}")
            event.input.disabled = False
            event.input.focus()

    def _switch(self, step: str) -> None:
        self.step = step
        title, placeholder, password = _STEPS[step]
        self.query_one("#auth-title", Static).update(f"🔑 {title}")
        error = self.query_one("#auth-error", Static)
        error.update("…")
        if step == "password":
            error.update("Cloud password required (2FA)")
        inp = self.query_one(Input)
        inp.value = ""
        inp.placeholder = placeholder
        inp.password = password
        inp.disabled = False
        inp.focus()

    async def _finish(self) -> None:
        self.query_one("#auth-error", Static).update("Signed in successfully, loading chats...")
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class WelcomeScreen(ModalScreen[str]):
    """Welcome and onboarding screen: choose between real Telegram and mock demo."""

    BINDINGS = [("escape", "choose_demo", "Explore Demo")]

    DEFAULT_CSS = """
    WelcomeScreen { align: center middle; background: #000000 70%; }
    #welcome-box {
        width: 100%;
        max-width: 70;
        height: auto;
        max-height: 100%;
        overflow-y: auto;
        padding: 1 2;
        background: #16161e;
        border: heavy #b7e680;
    }
    #welcome-badge { color: #b7e680; text-style: bold; margin-bottom: 1; }
    #welcome-title { text-style: bold; color: #f0f0f0; margin-bottom: 1; }
    #welcome-desc { color: #a9b1d6; margin-bottom: 1; }
    .welcome-btn {
        width: 1fr;
        margin-bottom: 1;
        border: tall #414868;
    }
    .btn-primary {
        background: #7aa2f7;
        color: #111413;
        text-style: bold;
        border: tall #7aa2f7;
    }
    .btn-primary:focus, .btn-primary:hover {
        background: #b7e680;
        color: #111413;
        border: tall #b7e680;
    }
    .btn-secondary {
        background: #24283b;
        color: #c0caf5;
        border: tall #414868;
    }
    .btn-secondary:focus, .btn-secondary:hover {
        background: #414868;
        color: #ffffff;
        text-style: bold;
    }
    #welcome-note { color: #565f89; margin-top: 1; text-align: center; }
    """

    def compose(self) -> ComposeResult:
        from textual.widgets import Button

        with Center():
            with Vertical(id="welcome-box"):
                yield Static("⚡ TELEGRAM / TUI  •  v0.4.0", id="welcome-badge")
                yield Static("Your Telegram. Entirely in your terminal.", id="welcome-title")
                yield Static(
                    "Fast, lightweight TUI client built for keyboard control.\n"
                    "Select how you want to launch:",
                    id="welcome-desc",
                )
                yield Button("Log in to Telegram (Telethon Live)", id="btn-login", classes="welcome-btn btn-primary")
                yield Button("Explore Demo Workspace (Offline Mock)", id="btn-demo", classes="welcome-btn btn-secondary")
                yield Static(
                    "Configuration stored in ~/.config/telegram-tui/config.toml\n"
                    "[Esc / Enter] to explore demo mode",
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
        width: 100%;
        max-width: 72;
        height: auto;
        max-height: 100%;
        overflow-y: auto;
        padding: 1 2;
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
    #api-box Input:focus { border: solid #7aa2f7; }
    .api-btn {
        width: 1fr;
        margin-bottom: 1;
        border: tall #414868;
    }
    .btn-primary {
        background: #7aa2f7;
        color: #111413;
        text-style: bold;
        border: tall #7aa2f7;
    }
    .btn-primary:focus, .btn-primary:hover {
        background: #b7e680;
        color: #111413;
        border: tall #b7e680;
    }
    .btn-secondary {
        background: #24283b;
        color: #c0caf5;
        border: tall #414868;
    }
    .btn-secondary:focus, .btn-secondary:hover {
        background: #414868;
        color: #ffffff;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        from textual.widgets import Button

        with Center():
            with Vertical(id="api-box"):
                yield Static("🔑 Telegram API Setup", id="api-title")
                yield Static(
                    "Direct connection requires an api_id and api_hash.\n"
                    "Get them for free at https://my.telegram.org -> 'API development tools'.",
                    id="api-desc",
                )
                yield Static("", id="api-error", markup=False)
                yield Input(placeholder="App api_id (integer, e.g. 12345678)", id="input-api-id")
                yield Input(placeholder="App api_hash (32-character string)", id="input-api-hash")
                yield Button("Save & Connect to Telegram", id="btn-save-api", classes="api-btn btn-primary")
                yield Button("Cancel (Return to Demo)", id="btn-cancel-api", classes="api-btn btn-secondary")

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
            error.update("Please enter api_id")
            self.query_one("#input-api-id", Input).focus()
            return
        try:
            api_id = int(raw_id)
        except ValueError:
            error.update("api_id must be an integer")
            self.query_one("#input-api-id", Input).focus()
            return

        if api_id <= 0:
            error.update("api_id must be a positive integer")
            self.query_one("#input-api-id", Input).focus()
            return

        if not raw_hash:
            error.update("Please enter api_hash")
            self.query_one("#input-api-hash", Input).focus()
            return

        if "\n" in raw_hash or '"' in raw_hash or len(raw_hash) < 8:
            error.update("Invalid api_hash format")
            self.query_one("#input-api-hash", Input).focus()
            return

        self.dismiss((api_id, raw_hash))

    def action_cancel(self) -> None:
        self.dismiss(None)

