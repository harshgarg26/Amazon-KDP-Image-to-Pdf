"""Small shared GUI helpers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from tkinter import ttk

import customtkinter as ctk

STATUS_COLORS = {"GREEN": "#2e9e5b", "YELLOW": "#d6a413", "RED": "#d64545", "GRAY": "#6b7280"}
STATUS_LABEL = {"GREEN": "GREEN", "YELLOW": "YELLOW", "RED": "RED"}


def style_treeview(dark: bool = True) -> None:
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    bg, fg, sel, head = (
        ("#242424", "#e5e5e5", "#1f6aa5", "#333333") if dark else ("#ffffff", "#1a1a1a", "#3b8ed0", "#e5e5e5")
    )
    style.configure("Treeview", background=bg, foreground=fg, fieldbackground=bg, rowheight=26,
                    borderwidth=0, font=("Segoe UI", 10))
    style.configure("Treeview.Heading", background=head, foreground=fg, relief="flat",
                    font=("Segoe UI", 10, "bold"))
    style.map("Treeview", background=[("selected", sel)], foreground=[("selected", "#ffffff")])
    style.map("Treeview.Heading", background=[("active", head)])


def make_tree(parent, columns: list[tuple[str, str, int]], height: int = 12) -> ttk.Treeview:
    """columns: (id, heading, width). Returns a Treeview packed with a vertical scrollbar."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height,
                        selectmode="extended")
    for cid, head, width in columns:
        tree.heading(cid, text=head)
        tree.column(cid, width=width, anchor="w", stretch=True)
    sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    for tag, color in (("GREEN", STATUS_COLORS["GREEN"]), ("YELLOW", STATUS_COLORS["YELLOW"]),
                       ("RED", STATUS_COLORS["RED"])):
        tree.tag_configure(tag, foreground=color)
    tree.frame = frame  # type: ignore[attr-defined]
    return tree


def open_folder(path: str | Path) -> None:
    path = str(path)
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


class StatCard(ctk.CTkFrame):
    def __init__(self, parent, title: str, color: str = "#1f6aa5"):
        super().__init__(parent, corner_radius=10)
        self.value = ctk.CTkLabel(self, text="0", font=ctk.CTkFont(size=30, weight="bold"), text_color=color)
        self.value.pack(padx=18, pady=(12, 0))
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=12), text_color="gray70").pack(
            padx=18, pady=(0, 12))

    def set(self, value) -> None:
        self.value.configure(text=str(value))


class Page(ctk.CTkFrame):
    """Base class for the seven main sections."""

    title = ""

    def __init__(self, app):
        super().__init__(app.content, fg_color="transparent")
        self.app = app
        self.ctl = app.ctl
        ctk.CTkLabel(self, text=self.title, font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", padx=20, pady=(16, 8))

    def on_show(self) -> None:  # called when the section becomes visible
        pass

    def on_event(self, event: tuple) -> None:  # called for controller events
        pass
