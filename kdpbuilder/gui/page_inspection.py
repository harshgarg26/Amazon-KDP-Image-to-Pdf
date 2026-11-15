"""3. Image Inspection: preview, printable-area overlay, illustration bounding box, margins."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageTk

from ..inspector import ERROR, INFO, WARNING
from ..layout import PT_PER_IN
from ..processor import load_flattened
from .widgets import STATUS_COLORS, Page

PAD = 24
MAX_PREVIEW = 1800  # longest side of the cached preview bitmap


class InspectionPage(Page):
    title = "Image Inspection"

    def __init__(self, app):
        super().__init__(app)
        self.index = 0
        self.zoom = 1.0
        self._photo = None
        self._cache_key = None
        self._cache_img: Image.Image | None = None

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20)
        ctk.CTkButton(top, text="< Previous", width=90, command=lambda: self.step(-1)).pack(side="left", padx=3)
        ctk.CTkButton(top, text="Next >", width=90, command=lambda: self.step(1)).pack(side="left", padx=3)
        self.name_label = ctk.CTkLabel(top, text="", font=ctk.CTkFont(weight="bold"))
        self.name_label.pack(side="left", padx=14)
        ctk.CTkButton(top, text="+", width=36, command=lambda: self.set_zoom(self.zoom * 1.25)).pack(
            side="right", padx=2)
        ctk.CTkButton(top, text="Fit", width=44, command=lambda: self.set_zoom(1.0)).pack(side="right", padx=2)
        ctk.CTkButton(top, text="-", width=36, command=lambda: self.set_zoom(self.zoom / 1.25)).pack(
            side="right", padx=2)
        self.zoom_label = ctk.CTkLabel(top, text="100%", width=54)
        self.zoom_label.pack(side="right")

        opts = ctk.CTkFrame(self, fg_color="transparent")
        opts.pack(fill="x", padx=20, pady=(4, 0))
        self.view = ctk.CTkSegmentedButton(opts, values=["Page layout", "Source image"],
                                           command=lambda _v: self.render())
        self.view.set("Page layout")
        self.view.pack(side="left", padx=3)
        self.show_safe = ctk.CTkCheckBox(opts, text="Printable area", command=self.render)
        self.show_safe.select()
        self.show_safe.pack(side="left", padx=10)
        self.show_bbox = ctk.CTkCheckBox(opts, text="Illustration box", command=self.render)
        self.show_bbox.select()
        self.show_bbox.pack(side="left", padx=10)
        ctk.CTkLabel(opts, text="green = printable area   red = illustration box   blue = placed image",
                     text_color="gray70").pack(side="left", padx=14)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=8)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.canvas = tk.Canvas(left, bg="#1b1b1b", highlightthickness=0)
        hs = tk.Scrollbar(left, orient="horizontal", command=self.canvas.xview)
        vs = tk.Scrollbar(left, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hs.set, yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        hs.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.render())
        self.canvas.bind("<MouseWheel>", self._wheel)

        right = ctk.CTkFrame(body)
        right.grid(row=0, column=1, sticky="nsew")
        self.status_label = ctk.CTkLabel(right, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.status_label.pack(anchor="w", padx=12, pady=(10, 0))
        self.details = ctk.CTkTextbox(right, wrap="word")
        self.details.pack(fill="both", expand=True, padx=8, pady=8)
        self.details.configure(state="disabled")

    # ------------------------------------------------------------------
    def step(self, d: int) -> None:
        n = len(self.ctl.records)
        if n:
            self.index = (self.index + d) % n
            self.render()

    def set_zoom(self, z: float) -> None:
        self.zoom = max(0.2, min(8.0, z))
        self.zoom_label.configure(text=f"{round(self.zoom * 100)}%")
        self.render()

    def _wheel(self, e) -> None:
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def on_show(self) -> None:
        self.render()

    def on_event(self, event: tuple) -> None:
        if event[0] in ("inspection_done",):
            self.render()

    def _source_preview(self, rec) -> Image.Image:
        key = (rec.path, rec.mtime, self.ctl.settings.background_color)
        if self._cache_key != key:
            img, _ = load_flattened(rec.path, self.ctl.settings, apply_modifications=False)
            img = img.convert("RGB")
            scale = MAX_PREVIEW / max(img.size)
            if scale < 1:
                img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                                 Image.LANCZOS)
            self._cache_key, self._cache_img = key, img
        return self._cache_img  # type: ignore[return-value]

    # ------------------------------------------------------------------
    def render(self) -> None:
        c = self.canvas
        c.delete("all")
        recs = self.ctl.records
        if not recs:
            self.name_label.configure(text="No images imported yet")
            self._set_details("Import images first.")
            return
        self.index = max(0, min(self.index, len(recs) - 1))
        rec = recs[self.index]
        self.name_label.configure(text=f"PDF page {self.index + 1} of {len(recs)}  -  {rec.filename}")
        if rec.error:
            self.status_label.configure(text="RED - unreadable", text_color=STATUS_COLORS["RED"])
            self._set_details(rec.error)
            return
        try:
            insp = self.ctl.inspection_for(self.index)
            src = self._source_preview(rec)
        except Exception as exc:
            self._set_details(f"Cannot display this image: {exc}")
            return
        geom = self.ctl.page_geometry(self.index)
        cw = max(c.winfo_width(), 300)
        ch = max(c.winfo_height(), 300)
        bbox = insp.bbox_px if insp else None
        sw, sh = rec.oriented_width, rec.oriented_height

        if self.view.get() == "Page layout" and geom is not None:
            pw, ph = geom.page.width, geom.page.height
            k = min((cw - 2 * PAD) / pw, (ch - 2 * PAD) / ph) * self.zoom

            def X(x):
                return PAD + x * k

            def Y(y):
                return PAD + (ph - y) * k

            c.create_rectangle(X(0), Y(ph), X(pw), Y(0), fill="white", outline="#888888")
            if self.ctl.settings.bleed:
                t = geom.trim
                c.create_rectangle(X(t.x0), Y(t.y1), X(t.x1), Y(t.y0), outline="#999999", dash=(2, 3))
            im = geom.image
            iw, ih = max(1, round(im.width * k)), max(1, round(im.height * k))
            self._photo = ImageTk.PhotoImage(src.resize((iw, ih), Image.LANCZOS))
            c.create_image(X(im.x0), Y(im.y1), image=self._photo, anchor="nw")
            c.create_rectangle(X(im.x0), Y(im.y1), X(im.x1), Y(im.y0), outline="#3b82f6")
            if self.show_safe.get():
                s = geom.safe
                c.create_rectangle(X(s.x0), Y(s.y1), X(s.x1), Y(s.y0), outline="#22c55e", width=2, dash=(6, 4))
            if self.show_bbox.get() and bbox:
                bx0 = X(im.x0 + bbox[0] * geom.scale_pt_per_px)
                bx1 = X(im.x0 + bbox[2] * geom.scale_pt_per_px)
                by0 = Y(im.y1 - bbox[1] * geom.scale_pt_per_px)
                by1 = Y(im.y1 - bbox[3] * geom.scale_pt_per_px)
                c.create_rectangle(bx0, by0, bx1, by1, outline="#ef4444", width=2)
            c.configure(scrollregion=(0, 0, X(pw) + PAD, Y(0) + PAD))
        else:
            k = min((cw - 2 * PAD) / sw, (ch - 2 * PAD) / sh) * self.zoom
            iw, ih = max(1, round(sw * k)), max(1, round(sh * k))
            self._photo = ImageTk.PhotoImage(src.resize((iw, ih), Image.LANCZOS))
            c.create_image(PAD, PAD, image=self._photo, anchor="nw")
            c.create_rectangle(PAD, PAD, PAD + iw, PAD + ih, outline="#3b82f6")
            if self.show_bbox.get() and bbox:
                f = iw / sw
                c.create_rectangle(PAD + bbox[0] * f, PAD + bbox[1] * f, PAD + bbox[2] * f, PAD + bbox[3] * f,
                                   outline="#ef4444", width=2)
            c.configure(scrollregion=(0, 0, PAD * 2 + iw, PAD * 2 + ih))
        self._fill_details(rec, insp, geom)

    # ------------------------------------------------------------------
    def _set_details(self, text: str) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _fill_details(self, rec, insp, geom) -> None:
        if insp is None:
            return
        self.status_label.configure(text=insp.status, text_color=STATUS_COLORS[insp.status])
        L = [
            f"File: {rec.filename}",
            f"Pixels: {rec.oriented_width} x {rec.oriented_height}   Format: {rec.format}   Mode: {rec.mode}",
            f"Transparency: {'yes' if rec.has_alpha else 'no'}   DPI metadata: {rec.dpi_text}   "
            f"EXIF orientation: {rec.exif_orientation}",
        ]
        if insp.effective_dpi:
            L.append(f"Effective DPI at placed size: {insp.effective_dpi:.0f}")
        if geom is not None:
            L.append(f"Placed image: {geom.image.width / PT_PER_IN:.3f} x {geom.image.height / PT_PER_IN:.3f} in "
                     f"({geom.side} page)")
        if insp.margins_px:
            m, p = insp.margins_px, insp.margins_pct or {}
            L += ["", "Illustration margins inside the image:"]
            L += [f"  {k:<6} {m[k]:>5} px  ({p.get(k, 0) * 100:.1f}%)" for k in ("left", "right", "top", "bottom")]
        if insp.art_margins_in:
            a = insp.art_margins_in
            L += ["", "Illustration to trim edge on the page (inches):"]
            L += [f"  {k:<6} {a[k]:.3f}" for k in ("left", "right", "top", "bottom")]
        for sev, label in ((ERROR, "ERRORS"), (WARNING, "WARNINGS"), (INFO, "NOTES")):
            items = [f for f in insp.findings if f.severity == sev]
            if items:
                L += ["", label + ":"] + [f"  - {f.message}" for f in items]
        if not insp.findings:
            L += ["", "No issues found by the internal checks."]
        L += ["", "Internal check only - not a KDP Print Previewer result."]
        self._set_details("\n".join(L))
