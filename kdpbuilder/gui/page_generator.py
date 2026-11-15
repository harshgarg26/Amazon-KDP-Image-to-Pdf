"""5. PDF Generator."""

from __future__ import annotations

from tkinter import filedialog, messagebox

import customtkinter as ctk

from .widgets import Page, open_folder


class GeneratorPage(Page):
    title = "PDF Generator"

    def __init__(self, app):
        super().__init__(app)
        box = ctk.CTkFrame(self)
        box.pack(fill="x", padx=20, pady=4)
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(12, 4))
        ctk.CTkLabel(row, text="Output folder:").pack(side="left")
        self.out_var = ctk.StringVar(value=str(self.ctl.output_dir))
        ctk.CTkEntry(row, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=8)
        ctk.CTkButton(row, text="Browse...", width=90, command=self.browse).pack(side="left")
        ctk.CTkButton(row, text="Open", width=70, fg_color="gray35",
                      command=lambda: open_folder(self.out_var.get())).pack(side="left", padx=(6, 0))

        opts = ctk.CTkFrame(box, fg_color="transparent")
        opts.pack(fill="x", padx=12, pady=4)
        self.skip = ctk.CTkCheckBox(opts, text="Skip failed images (they are listed in failed_pages.csv)")
        self.skip.select()
        self.skip.pack(side="left", padx=4)
        self.resume = ctk.CTkCheckBox(opts, text="Resume interrupted run (reuse processed images)")
        self.resume.pack(side="left", padx=16)

        btns = ctk.CTkFrame(box, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(4, 12))
        self.go = ctk.CTkButton(btns, text="Generate PDF", width=150, command=self.generate)
        self.go.pack(side="left", padx=4)
        self.stop = ctk.CTkButton(btns, text="Cancel generation", width=150, fg_color="#7a2f2f",
                                  hover_color="#963a3a", state="disabled", command=self.ctl.cancel)
        self.stop.pack(side="left", padx=4)

        prog = ctk.CTkFrame(self)
        prog.pack(fill="x", padx=20, pady=8)
        self.bar = ctk.CTkProgressBar(prog)
        self.bar.set(0)
        self.bar.pack(fill="x", padx=14, pady=(14, 6))
        self.stage = ctk.CTkLabel(prog, text="Idle", anchor="w", font=ctk.CTkFont(weight="bold"))
        self.stage.pack(fill="x", padx=14)
        self.current = ctk.CTkLabel(prog, text="Current file: -", anchor="w")
        self.current.pack(fill="x", padx=14)
        self.page = ctk.CTkLabel(prog, text="Current page: -", anchor="w")
        self.page.pack(fill="x", padx=14, pady=(0, 12))

        self.result = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=900)
        self.result.pack(fill="x", padx=24, pady=4)
        ctk.CTkLabel(self, text="Log", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=24)
        self.log = ctk.CTkTextbox(self)
        self.log.pack(fill="both", expand=True, padx=20, pady=(2, 16))
        self.log.configure(state="disabled")

    def browse(self) -> None:
        d = filedialog.askdirectory(title="Choose the output folder")
        if d:
            self.out_var.set(d)

    def generate(self) -> None:
        if not self.ctl.records:
            messagebox.showinfo("Nothing to do", "Import some images first.")
            return
        if not self.app.pages["settings"].apply(silent=True):
            return
        self.ctl.output_dir = type(self.ctl.output_dir)(self.out_var.get())
        self.ctl.settings.skip_failed = bool(self.skip.get())
        if self.ctl.settings.any_modification_enabled:
            if not messagebox.askyesno(
                    "Optional modifications enabled",
                    "Optional image modifications (grayscale, cleaning, thresholding, contrast or a "
                    "non-white background) are enabled. The processed copies will differ from your "
                    "originals (originals are never changed). Continue?"):
                return
        self._clear_log()
        if self.ctl.start_generation(resume=bool(self.resume.get()), skip_failed=bool(self.skip.get())):
            self.go.configure(state="disabled")
            self.stop.configure(state="normal")
            self.result.configure(text="")
        else:
            messagebox.showinfo("Busy", "Another job is already running.")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def on_event(self, event: tuple) -> None:
        kind = event[0]
        if kind == "progress":
            _, stage, cur, total, name = event
            label = {"process": "Processing images", "pdf": "Writing PDF pages",
                     "validate": "Validating PDF", "inspect": "Inspecting"}.get(stage, stage)
            self.bar.set(cur / total if total else 0)
            self.stage.configure(text=f"{label}  ({cur} / {total})")
            self.current.configure(text=f"Current file: {name}")
            self.page.configure(text=f"Current page: {cur}")
        elif kind == "log":
            self._log(f"{event[1]:<7} {event[2]}")
        elif kind == "error":
            self._log(f"ERROR   {event[1]}")
            self.result.configure(text=event[1], text_color="#d64545")
        elif kind == "run_done":
            run = event[1]
            self.result.configure(
                text=run.message + ("\n" + "Output: " + str(run.output_dir)), text_color="#e5e5e5")
            self.stage.configure(text="Finished" if not run.cancelled else "Cancelled")
        elif kind == "idle":
            self.go.configure(state="normal")
            self.stop.configure(state="disabled")
