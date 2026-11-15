"""Main window: sidebar navigation, page switching, controller event pump, drag & drop."""

from __future__ import annotations

import customtkinter as ctk

from .. import APP_NAME, __version__
from ..controller import Controller
from .page_dashboard import DashboardPage
from .page_export import ExportPage
from .page_generator import GeneratorPage
from .page_import import ImportPage
from .page_inspection import InspectionPage
from .page_settings import SettingsPage
from .page_validation import ValidationPage
from .widgets import style_treeview

try:  # optional: native drag & drop (Windows/macOS/Linux)
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND = True
except Exception:  # pragma: no cover
    DND_FILES = None
    TkinterDnD = None
    _DND = False

NAV = [
    ("dashboard", "Dashboard", DashboardPage),
    ("import", "Import Images", ImportPage),
    ("inspection", "Image Inspection", InspectionPage),
    ("settings", "Page Settings", SettingsPage),
    ("generator", "PDF Generator", GeneratorPage),
    ("validation", "PDF Validation", ValidationPage),
    ("export", "Export", ExportPage),
]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.dnd_available = False
        if _DND:
            try:  # attach the tkdnd package to this CTk root
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_available = True
            except Exception:
                self.dnd_available = False
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        style_treeview(dark=True)
        self.title(f"{APP_NAME} {__version__} - Amazon KDP manuscript PDF generator")
        self.geometry("1280x820")
        self.minsize(1050, 680)
        self.ctl = Controller()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        side = ctk.CTkFrame(self, width=200, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        ctk.CTkLabel(side, text=APP_NAME, font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(20, 2))
        ctk.CTkLabel(side, text="KDP manuscript builder", text_color="gray70").pack(pady=(0, 18))
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.status = ctk.CTkLabel(self, text="Ready", anchor="w", text_color="gray70")
        self.status.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 4))

        self.pages: dict[str, ctk.CTkFrame] = {}
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, label, cls in NAV:
            self.pages[key] = cls(self)
            b = ctk.CTkButton(side, text=label, anchor="w", height=38, fg_color="transparent",
                              text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"),
                              command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[key] = b
        self.current = ""
        self.show("dashboard")
        self._setup_dnd()
        self.after(100, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------------
    def show(self, key: str) -> None:
        if key not in ("settings",) and "settings" in self.pages and self.current == "settings":
            self.pages["settings"].apply(silent=True)
        if self.current:
            self.pages[self.current].pack_forget()
            self.nav_buttons[self.current].configure(fg_color="transparent")
        self.current = key
        self.nav_buttons[key].configure(fg_color=("gray75", "gray25"))
        self.pages[key].pack(fill="both", expand=True)
        self.pages[key].on_show()

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def inspect_all(self) -> None:
        if not self.ctl.records:
            self.set_status("Import images first")
            return
        if not self.pages["settings"].apply(silent=True):
            return
        if not self.ctl.start_inspection():
            self.set_status("Another job is running")

    # ------------------------------------------------------------------
    def _setup_dnd(self) -> None:
        if not self.dnd_available:
            return
        try:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            self.dnd_available = False

    def _on_drop(self, event) -> None:
        try:
            paths = list(self.tk.splitlist(event.data))
        except Exception:
            paths = [event.data]
        self.pages["import"].add_paths(paths)
        self.show("import")

    # ------------------------------------------------------------------
    def _pump(self) -> None:
        try:
            while True:
                ev = self.ctl.events.get_nowait()
                for page in self.pages.values():
                    page.on_event(ev)
                if ev[0] == "error":
                    self.set_status(ev[1])
                elif ev[0] == "run_done":
                    self.set_status(ev[1].message)
        except Exception:
            pass
        self.after(100, self._pump)

    def _close(self) -> None:
        self.ctl.cancel()
        self.destroy()


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
