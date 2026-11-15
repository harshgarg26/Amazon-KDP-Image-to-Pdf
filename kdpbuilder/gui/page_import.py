"""2. Import Images."""

from __future__ import annotations

from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..importer import SUPPORTED_EXTS
from .widgets import Page, make_tree

COLUMNS = [
    ("page", "PDF page", 70), ("file", "Filename", 260), ("size", "Pixels", 110), ("aspect", "Aspect", 70),
    ("fmt", "Format", 70), ("mode", "Color mode", 80), ("alpha", "Transparency", 90),
    ("dpi", "DPI metadata", 100), ("exif", "EXIF", 55), ("status", "Status", 120),
]


class ImportPage(Page):
    title = "Import Images"

    def __init__(self, app):
        super().__init__(app)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=20)
        for text, cmd in (
            ("Add images...", self.add_images),
            ("Add folder...", self.add_folder),
            ("Add ZIP...", self.add_zip),
        ):
            ctk.CTkButton(bar, text=text, width=120, command=cmd).pack(side="left", padx=4, pady=4)
        self.recursive = ctk.CTkCheckBox(bar, text="Include subfolders")
        self.recursive.pack(side="left", padx=12)
        ctk.CTkButton(bar, text="Clear all", width=90, fg_color="#7a2f2f", hover_color="#963a3a",
                      command=self.clear).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="Remove selected", width=130, command=self.remove).pack(side="right", padx=4)

        bar2 = ctk.CTkFrame(self, fg_color="transparent")
        bar2.pack(fill="x", padx=20)
        ctk.CTkButton(bar2, text="Move up", width=90, command=lambda: self.move(-1)).pack(side="left", padx=4)
        ctk.CTkButton(bar2, text="Move down", width=100, command=lambda: self.move(1)).pack(side="left", padx=4)
        ctk.CTkButton(bar2, text="Natural sort (1, 2, 10)", width=170, command=self.natural_sort).pack(
            side="left", padx=4)
        hint = ("Drag & drop images, folders or ZIP files anywhere on this window."
                if app.dnd_available else
                "Drag & drop is unavailable (install 'tkinterdnd2'); use the buttons above.")
        ctk.CTkLabel(self, text=hint + "  Double-click a row to inspect it.  Supported: "
                     + ", ".join(sorted(e.lstrip('.').upper() for e in SUPPORTED_EXTS)),
                     text_color="gray70", anchor="w").pack(fill="x", padx=24, pady=(6, 4))

        holder = ctk.CTkFrame(self, fg_color="transparent")
        holder.pack(fill="both", expand=True, padx=20, pady=(0, 6))
        self.tree = make_tree(holder, COLUMNS)
        self.tree.bind("<Double-1>", self._open_selected)
        self.count = ctk.CTkLabel(self, text="", anchor="w")
        self.count.pack(fill="x", padx=24, pady=(0, 10))

    # ------------------------------------------------------------------
    def add_paths(self, paths) -> None:
        added, rejected = self.ctl.add_items(paths, recursive=bool(self.recursive.get()))
        self.refresh()
        msg = f"Added {added} image(s)."
        if rejected:
            msg += "\n\nNot added:\n" + "\n".join(f"- {n}: {why}" for n, why in rejected[:15])
            if len(rejected) > 15:
                msg += f"\n... and {len(rejected) - 15} more"
        if rejected or not added:
            messagebox.showinfo("Import", msg if added or rejected else "No supported images were found.")
        self.app.set_status(f"Added {added} image(s)")

    def add_images(self) -> None:
        pats = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTS))
        files = filedialog.askopenfilenames(title="Select images",
                                            filetypes=[("Images", pats), ("All files", "*.*")])
        if files:
            self.add_paths(files)

    def add_folder(self) -> None:
        d = filedialog.askdirectory(title="Select a folder of images")
        if d:
            self.add_paths([d])

    def add_zip(self) -> None:
        z = filedialog.askopenfilenames(title="Select ZIP archive(s)", filetypes=[("ZIP archives", "*.zip")])
        if z:
            self.add_paths(z)

    def _selected(self) -> list[int]:
        return [self.tree.index(i) for i in self.tree.selection()]

    def remove(self) -> None:
        sel = self._selected()
        if sel:
            self.ctl.remove(sel)
            self.refresh()

    def clear(self) -> None:
        if self.ctl.records and messagebox.askyesno("Clear", "Remove all imported images from the list?\n"
                                                    "(Your original files are not touched.)"):
            self.ctl.clear()
            self.refresh()

    def move(self, delta: int) -> None:
        sel = self.ctl.move(self._selected(), delta)
        self.refresh()
        kids = self.tree.get_children()
        self.tree.selection_set([kids[i] for i in sel if i < len(kids)])
        if sel and sel[0] < len(kids):
            self.tree.see(kids[sel[0]])

    def natural_sort(self) -> None:
        self.ctl.natural_sort()
        self.refresh()

    def _open_selected(self, _event=None) -> None:
        sel = self._selected()
        if sel:
            self.app.pages["inspection"].index = sel[0]
            self.app.show("inspection")

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.ctl.records):
            insp = self.ctl.inspection_for(i, compute=False)
            if r.error:
                status, tag = "UNREADABLE", "RED"
            elif insp is None:
                status, tag = "not inspected", ""
            else:
                status, tag = insp.status, insp.status
            self.tree.insert("", "end", tags=(tag,) if tag else (), values=(
                i + 1, r.filename, r.size_text, f"{r.aspect_ratio:.3f}" if r.ok else "-", r.format or "-",
                r.mode or "-", "yes" if r.has_alpha else "no", r.dpi_text, r.exif_orientation, status))
        n = len(self.ctl.records)
        bad = sum(1 for r in self.ctl.records if r.error)
        self.count.configure(text=f"{n} image(s) in PDF order" + (f"  -  {bad} unreadable" if bad else ""))

    def on_show(self) -> None:
        self.refresh()

    def on_event(self, event: tuple) -> None:
        if event[0] in ("inspection_done", "run_done"):
            self.refresh()
