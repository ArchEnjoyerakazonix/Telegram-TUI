"""Attachment picker: a path field with completion over a directory tree."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DirectoryTree, Input, Static

from ..models import format_size


def complete_path(text: str) -> str:
    """Extend ``text`` as far as the filesystem unambiguously allows."""
    if not text:
        return text
    expanded = Path(text).expanduser()
    if text.endswith("/"):
        base, prefix = expanded, ""
    else:
        base, prefix = expanded.parent, expanded.name
    try:
        matches = sorted(
            child for child in base.iterdir() if child.name.startswith(prefix)
        )
    except OSError:
        return text
    if not matches:
        return text
    if len(matches) == 1:
        only = matches[0]
        return f"{only}{os.sep}" if only.is_dir() else str(only)
    shared = os.path.commonprefix([match.name for match in matches])
    return str(base / shared) if shared else text


class PathInput(Input):
    """Input where Tab completes the path instead of moving focus."""

    BINDINGS = [Binding("tab", "complete", "Complete", priority=True, show=False)]

    def action_complete(self) -> None:
        completed = complete_path(self.value)
        if completed != self.value:
            self.value = completed
            self.cursor_position = len(completed)


class VisibleTree(DirectoryTree):
    """Directory tree without dotfiles — rarely what anyone wants to send."""

    def filter_paths(self, paths):
        return [path for path in paths if not path.name.startswith(".")]


class AttachScreen(ModalScreen["tuple[Path, bool] | None"]):
    """Pick a file to send, and whether to send it uncompressed."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    AttachScreen { align: center middle; background: #000000 70%; }
    #attach-box {
        width: 100%;
        max-width: 76;
        height: auto;
        max-height: 100%;
        overflow-y: auto;
        padding: 1 2;
        background: #16161e;
        border: heavy #7aa2f7;
    }
    #attach-title { color: #7aa2f7; text-style: bold; margin-bottom: 1; }
    #attach-info { color: #a9b1d6; height: 1; margin-bottom: 1; }
    #attach-box Input {
        background: #1f2335;
        border: solid #3b4261;
        color: #c0caf5;
    }
    #attach-box Input:focus { border: solid #b7e680; }
    #attach-tree {
        height: 10;
        margin-bottom: 1;
        background: #1f2335;
        border: solid #3b4261;
    }
    #attach-doc { margin-bottom: 1; }
    #attach-buttons { height: auto; }
    .attach-btn { width: 1fr; margin: 0 1 0 0; }
    """

    def __init__(self, start_dir: Path | None = None) -> None:
        super().__init__()
        self._start_dir = Path(start_dir or Path.home())

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="attach-box"):
                yield Static("📎 Attach file", id="attach-title")
                yield PathInput(
                    placeholder="Path to the file… (Tab completes)", id="attach-path"
                )
                yield Static("", id="attach-info", markup=False)
                yield VisibleTree(self._start_dir, id="attach-tree")
                yield Checkbox("Send as file (no compression)", id="attach-doc")
                with Horizontal(id="attach-buttons"):
                    yield Button(
                        "Send (Enter)", id="btn-attach-send", classes="attach-btn btn-primary"
                    )
                    yield Button(
                        "Cancel (Esc)", id="btn-attach-cancel", classes="attach-btn btn-secondary"
                    )

    def on_mount(self) -> None:
        self.query_one(PathInput).focus()

    # -- keeping the info line in step ---------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        self._describe(event.value)

    def _describe(self, raw: str) -> None:
        info = self.query_one("#attach-info", Static)
        if not raw.strip():
            info.update("")
            return
        path = Path(raw).expanduser()
        if path.is_dir():
            info.update("directory — pick a file inside it")
        elif path.is_file():
            mime = mimetypes.guess_type(path.name)[0] or "unknown type"
            info.update(f"{format_size(path.stat().st_size)} · {mime}")
        else:
            info.update("no such file")

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        field = self.query_one(PathInput)
        field.value = str(event.path)
        field.cursor_position = len(field.value)
        self._describe(field.value)
        field.focus()

    # -- submit ---------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-attach-send":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        field = self.query_one(PathInput)
        info = self.query_one("#attach-info", Static)
        raw = field.value.strip()
        if not raw:
            info.update("enter a path, or pick a file from the tree")
            field.focus()
            return
        path = Path(raw).expanduser()
        if not path.is_file():
            self._describe(raw)
            field.focus()
            return
        self.dismiss((path, self.query_one("#attach-doc", Checkbox).value))

    def action_cancel(self) -> None:
        self.dismiss(None)
