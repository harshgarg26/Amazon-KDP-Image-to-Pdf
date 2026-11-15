"""1. Dashboard."""

from __future__ import annotations

import customtkinter as ctk

from .widgets import STATUS_COLORS, Page, StatCard


class DashboardPage(Page):
    title = "Dashboard"

    def __init__(self, app):
        super().__init__(app)
        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.pack(fill="x", padx=20)
        self.c_total = StatCard(cards, "Imported images")
        self.c_valid = StatCard(cards, "Valid (green)", STATUS_COLORS["GREEN"])
        self.c_warn = StatCard(cards, "Warnings (yellow)", STATUS_COLORS["YELLOW"])
        self.c_fail = StatCard(cards, "Failed (red)", STATUS_COLORS["RED"])
        self.c_pages = StatCard(cards, "PDF pages")
        for i, c in enumerate((self.c_total, self.c_valid, self.c_warn, self.c_fail, self.c_pages)):
            c.grid(row=0, column=i, padx=6, pady=6, sticky="nsew")
            cards.grid_columnconfigure(i, weight=1)

        self.note = ctk.CTkLabel(self, text="", anchor="w", justify="left", text_color="gray70")
        self.note.pack(fill="x", padx=24, pady=(4, 0))

        prog = ctk.CTkFrame(self)
        prog.pack(fill="x", padx=20, pady=12)
        ctk.CTkLabel(prog, text="Processing progress", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=14, pady=(10, 2))
        self.bar = ctk.CTkProgressBar(prog)
        self.bar.set(0)
        self.bar.pack(fill="x", padx=14, pady=4)
        self.prog_label = ctk.CTkLabel(prog, text="Idle", anchor="w")
        self.prog_label.pack(fill="x", padx=14, pady=(0, 10))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20)
        ctk.CTkButton(row, text="Inspect all images", command=self.app.inspect_all).pack(side="left", padx=4)
        ctk.CTkButton(row, text="Go to PDF Generator",
                      command=lambda: self.app.show("generator")).pack(side="left", padx=4)

        ctk.CTkLabel(self, text="Activity log", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=24, pady=(14, 2))
        self.log = ctk.CTkTextbox(self, height=220)
        self.log.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self.log.configure(state="disabled")

    def log_line(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def refresh(self) -> None:
        s = self.ctl.summary()
        self.c_total.set(s["total"])
        self.c_valid.set(s["valid"])
        self.c_warn.set(s["warning"])
        self.c_fail.set(s["failed"])
        self.c_pages.set(s["pdf_pages"])
        if s["total"] and s["inspected"] < s["total"]:
            self.note.configure(
                text=f"{s['inspected']} of {s['total']} images inspected. Use 'Inspect all images' for the "
                     "valid / warning / failed counts.")
        else:
            self.note.configure(text="")

    def on_show(self) -> None:
        self.refresh()

    def on_event(self, event: tuple) -> None:
        kind = event[0]
        if kind == "progress":
            _, stage, cur, total, name = event
            self.bar.set(cur / total if total else 0)
            self.prog_label.configure(text=f"{stage.title()}: {cur} / {total}  -  {name}")
        elif kind == "log":
            self.log_line(f"{event[1]:<7} {event[2]}")
        elif kind == "error":
            self.log_line(f"ERROR   {event[1]}")
        elif kind == "inspection_done":
            self.prog_label.configure(text="Inspection finished")
            self.refresh()
        elif kind == "run_done":
            self.prog_label.configure(text=event[1].message)
            self.bar.set(1)
            self.refresh()
        elif kind == "idle":
            self.refresh()
