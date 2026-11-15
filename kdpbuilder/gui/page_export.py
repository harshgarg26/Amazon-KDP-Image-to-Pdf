"""7. Export."""

from __future__ import annotations

import shutil
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .widgets import Page, open_folder


class ExportPage(Page):
    title = "Export"

    def __init__(self, app):
        super().__init__(app)
        self.summary = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=950)
        self.summary.pack(fill="x", padx=24, pady=4)
        self.files = ctk.CTkTextbox(self, height=230)
        self.files.pack(fill="x", padx=20, pady=6)
        self.files.configure(state="disabled")
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=6)
        ctk.CTkButton(bar, text="Open output folder", command=self.open_out).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Save PDF as...", command=self.save_pdf).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Copy whole output folder to...", command=self.copy_all).pack(side="left", padx=4)
        self.note = ctk.CTkLabel(
            self, anchor="w", justify="left", wraplength=950, text_color="gray70",
            text="Output layout:  manuscript.pdf, previews/, processed_images/, reports/ "
                 "(validation_report.csv, failed_pages.csv, processing_log.txt, pdf_metadata.json).\n"
                 "The internal validation is not an Amazon KDP result - upload to KDP and review its "
                 "Print Previewer before publishing.")
        self.note.pack(fill="x", padx=24, pady=8)

    def _run(self):
        return self.ctl.last_run

    def refresh(self) -> None:
        run = self._run()
        self.files.configure(state="normal")
        self.files.delete("1.0", "end")
        if not run:
            self.summary.configure(text="Nothing has been generated yet.")
        else:
            out = Path(run.output_dir)
            self.summary.configure(text=f"Output folder: {out}\n{run.message}")
            for p in sorted(out.rglob("*")):
                if p.is_file() and not p.name.startswith(".") and "_extracted_zips" not in p.parts:
                    rel = p.relative_to(out)
                    if rel.parts[0] in ("processed_images", "previews") and len(rel.parts) > 1:
                        continue
                    self.files.insert("end", f"{rel}   ({p.stat().st_size / 1024:.0f} KB)\n")
            for sub in ("processed_images", "previews"):
                d = out / sub
                if d.exists():
                    self.files.insert("end", f"{sub}/   ({sum(1 for _ in d.glob('*.png'))} images)\n")
        self.files.configure(state="disabled")

    def open_out(self) -> None:
        run = self._run()
        open_folder(run.output_dir if run else self.ctl.output_dir)

    def save_pdf(self) -> None:
        run = self._run()
        if not run or not run.pdf_path or not Path(run.pdf_path).exists():
            messagebox.showinfo("No PDF", "Generate the PDF first.")
            return
        dest = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
                                            initialfile="manuscript.pdf")
        if dest:
            shutil.copy2(run.pdf_path, dest)
            self.app.set_status(f"PDF saved: {dest}")

    def copy_all(self) -> None:
        run = self._run()
        if not run:
            messagebox.showinfo("Nothing to copy", "Generate the PDF first.")
            return
        dest = filedialog.askdirectory(title="Copy the output folder into...")
        if not dest:
            return
        target = Path(dest) / Path(run.output_dir).name
        if target.exists():
            messagebox.showerror("Exists", f"{target} already exists; choose another location.")
            return
        shutil.copytree(run.output_dir, target, ignore=shutil.ignore_patterns("_extracted_zips", ".kdpbuilder_state*"))
        self.app.set_status(f"Copied to {target}")

    def on_show(self) -> None:
        self.refresh()

    def on_event(self, event: tuple) -> None:
        if event[0] == "run_done":
            self.refresh()
