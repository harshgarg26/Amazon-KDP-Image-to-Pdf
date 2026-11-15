"""6. PDF Validation."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

from .. import KDP_DISCLAIMER, reporting
from .widgets import STATUS_COLORS, Page, make_tree

COLUMNS = [
    ("page", "Page", 55), ("file", "Filename", 200), ("status", "Status", 80), ("dpi", "DPI", 55),
    ("bounds", "Boundary", 75), ("transp", "Transparency", 90), ("issues", "Errors / warnings", 420),
]


class ValidationPage(Page):
    title = "PDF Validation"

    def __init__(self, app):
        super().__init__(app)
        self.rows: list[dict] = []
        self._photo = None
        self.banner = ctk.CTkLabel(self, text="No PDF has been validated yet.", anchor="w",
                                   font=ctk.CTkFont(size=15, weight="bold"))
        self.banner.pack(fill="x", padx=24)
        ctk.CTkLabel(self, text=KDP_DISCLAIMER, anchor="w", text_color="gray70", wraplength=1000,
                     justify="left").pack(fill="x", padx=24, pady=(0, 6))
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=20)
        ctk.CTkButton(bar, text="Re-validate PDF", width=130, command=self.revalidate).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Export validation report...", width=190, command=self.export).pack(
            side="left", padx=4)
        self.only_problems = ctk.CTkCheckBox(bar, text="Show only warnings and failures", command=self.fill)
        self.only_problems.pack(side="left", padx=14)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=8)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.tree = make_tree(left, COLUMNS)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_selected())
        right = ctk.CTkFrame(body)
        right.grid(row=0, column=1, sticky="nsew")
        self.preview = tk.Label(right, bg="#1b1b1b")
        self.preview.pack(fill="both", expand=True, padx=6, pady=6)
        self.detail = ctk.CTkTextbox(right, height=170, wrap="word")
        self.detail.pack(fill="x", padx=6, pady=(0, 6))
        self.detail.configure(state="disabled")

    # ------------------------------------------------------------------
    def load_run(self) -> None:
        run = self.ctl.last_run
        self.rows = run.rows if run else []
        if not run:
            self.banner.configure(text="No PDF has been validated yet.", text_color="gray70")
        elif run.validation is None:
            self.banner.configure(text="No PDF was produced - see the failed images below.",
                                  text_color=STATUS_COLORS["RED"])
        else:
            st = run.overall_status
            c = run.counts
            self.banner.configure(
                text=f"Internal validation: {st}   -   {c['GREEN']} green, {c['YELLOW']} yellow, {c['RED']} red",
                text_color=STATUS_COLORS[st])
        self.fill()

    def fill(self) -> None:
        self.tree.delete(*self.tree.get_children())
        only = bool(self.only_problems.get())
        for i, r in enumerate(self.rows):
            if only and r["status"] == "GREEN":
                continue
            issues = r["errors"] or r["warnings"] or r["notes"]
            self.tree.insert("", "end", iid=str(i), tags=(r["status"],), values=(
                r["pdf_page"], r["filename"], r["status"], r["effective_dpi"], r["boundary_validation"],
                r["transparency_status"], issues.replace(" | ", "  |  ")[:300]))

    def show_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        r = self.rows[int(sel[0])]
        lines = [f"Page {r['pdf_page']}  -  {r['filename']}  -  {r['status']}"]
        for label, key in (("Errors", "errors"), ("Warnings", "warnings"), ("Notes", "notes")):
            if r[key]:
                lines.append(f"\n{label}:")
                lines += [f"  - {x}" for x in r[key].split(" | ")]
        if r["margin_left_in"] != "":
            lines.append(f"\nImage object margins (in): L {r['margin_left_in']}  R {r['margin_right_in']}  "
                         f"T {r['margin_top_in']}  B {r['margin_bottom_in']}")
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", "\n".join(lines))
        self.detail.configure(state="disabled")
        self._show_preview(r)

    def _show_preview(self, r: dict) -> None:
        run = self.ctl.last_run
        self.preview.configure(image="", text="")
        self._photo = None
        if not run or not isinstance(r["pdf_page"], int):
            self.preview.configure(text="(no preview)", fg="gray70")
            return
        path = Path(run.output_dir) / "previews" / f"page_{r['pdf_page']:04d}.png"
        if not path.exists():
            self.preview.configure(text="(no preview)", fg="gray70")
            return
        im = Image.open(path)
        w = max(self.preview.winfo_width(), 260)
        h = max(self.preview.winfo_height(), 260)
        im.thumbnail((w - 8, h - 8), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(im)
        self.preview.configure(image=self._photo)

    def revalidate(self) -> None:
        if not self.ctl.start_revalidation():
            messagebox.showinfo("Nothing to validate", "Generate a PDF first.")

    def export(self) -> None:
        if not self.rows:
            messagebox.showinfo("Nothing to export", "There is no validation report yet.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                            initialfile="validation_report.csv")
        if path:
            reporting.write_validation_csv(Path(path), self.rows)
            self.app.set_status(f"Validation report saved: {path}")

    def on_show(self) -> None:
        self.load_run()

    def on_event(self, event: tuple) -> None:
        if event[0] == "run_done":
            self.load_run()
