"""4. Page Settings."""

from __future__ import annotations

from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..layout import PT_PER_IN, safe_rect
from ..settings import BookSettings
from .widgets import Page

PLACEMENT_LABELS = {
    "Fit inside printable area (recommended)": "fit",
    "Center at native size (no scaling)": "center",
    "Custom scale and position": "custom",
}
COLOR_LABELS = {"Keep original colors": "preserve", "Convert to grayscale": "grayscale"}
BLEED_LABELS = {"No bleed": False, "With bleed": True}
BINDING_LABELS = {"Left-bound (page 1 is a right-hand page)": "left", "Right-bound": "right"}
INTERIOR_LABELS = {"Black & white": "bw", "Color": "color"}


def _rev(mapping: dict, value):
    return next(k for k, v in mapping.items() if v == value)


class SettingsPage(Page):
    title = "Page Settings"

    def __init__(self, app):
        super().__init__(app)
        self.form = ctk.CTkScrollableFrame(self)
        self.form.pack(fill="both", expand=True, padx=20, pady=(0, 6))
        self.form.grid_columnconfigure(1, weight=1)
        self.vars: dict[str, ctk.StringVar] = {}
        self._row = 0
        s = BookSettings()

        self._section("Book")
        self._entry("trim_width_in", "Trim width (in)", s.trim_width_in)
        self._entry("trim_height_in", "Trim height (in)", s.trim_height_in)
        self._entry("dpi_target", "DPI target", s.dpi_target)
        self._menu("bleed", "Bleed", BLEED_LABELS, "No bleed")
        self._entry("bleed_in", "Bleed amount (in)", s.bleed_in)
        self._menu("interior", "Interior", INTERIOR_LABELS, "Black & white")
        self._menu("binding", "Binding", BINDING_LABELS, _rev(BINDING_LABELS, s.binding))

        self._section("Margins (from the trim edge)")
        self._entry("inside_margin_in", "Inside margin (in)", s.inside_margin_in)
        self._entry("outside_margin_in", "Outside margin (in)", s.outside_margin_in)
        self._entry("top_margin_in", "Top margin (in)", s.top_margin_in)
        self._entry("bottom_margin_in", "Bottom margin (in)", s.bottom_margin_in)

        self._section("Image placement (aspect ratio is always preserved - never stretched or cropped)")
        self._menu("placement", "Placement", PLACEMENT_LABELS, _rev(PLACEMENT_LABELS, s.placement))
        self._entry("custom_scale", "Custom scale (x fit size)", s.custom_scale)
        self._entry("custom_offset_x_in", "Custom offset X (in, + right)", s.custom_offset_x_in)
        self._entry("custom_offset_y_in", "Custom offset Y (in, + up)", s.custom_offset_y_in)

        self._section("Color and background")
        self._entry("background_color", "Background color", s.background_color)
        self._menu("color_mode", "Color mode", COLOR_LABELS, _rev(COLOR_LABELS, s.color_mode))

        self._section("Optional image modifications (all OFF by default)")
        self._check("near_white_clean", "Near-white background cleaning", s.near_white_clean)
        self._entry("near_white_threshold", "   ...pixels at or above (0-255)", s.near_white_threshold)
        self._check("bw_threshold", "Black & white thresholding", s.bw_threshold)
        self._entry("bw_threshold_value", "   ...threshold (0-255)", s.bw_threshold_value)
        self._check("contrast_adjust", "Contrast adjustment", s.contrast_adjust)
        self._entry("contrast_factor", "   ...factor (1.0 = unchanged)", s.contrast_factor)

        self._section("Validation thresholds")
        self._entry("kdp_min_margin_in", "Warn if artwork is closer than (in)", s.kdp_min_margin_in)
        self._entry("dpi_error_threshold", "Effective DPI failure threshold", s.dpi_error_threshold)
        self._entry("preview_dpi", "Preview / comparison DPI", s.preview_dpi)

        self.info = ctk.CTkLabel(self, text="", justify="left", anchor="w", text_color="gray70")
        self.info.pack(fill="x", padx=24, pady=(0, 4))
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=(0, 12))
        ctk.CTkButton(bar, text="Apply settings", command=self.apply).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Reset to defaults", fg_color="gray35", command=self.reset).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Save settings...", fg_color="gray35", command=self.save).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Load settings...", fg_color="gray35", command=self.load).pack(side="left", padx=4)
        self.load_into_form(self.ctl.settings)

    # ---- form builders ----------------------------------------------------
    def _section(self, text: str) -> None:
        ctk.CTkLabel(self.form, text=text, font=ctk.CTkFont(weight="bold")).grid(
            row=self._row, column=0, columnspan=2, sticky="w", padx=6, pady=(14, 4))
        self._row += 1

    def _entry(self, key: str, label: str, value) -> None:
        var = ctk.StringVar(value=str(value))
        self.vars[key] = var
        ctk.CTkLabel(self.form, text=label, anchor="w").grid(row=self._row, column=0, sticky="w", padx=6, pady=3)
        ctk.CTkEntry(self.form, textvariable=var, width=220).grid(row=self._row, column=1, sticky="w", padx=6)
        self._row += 1

    def _menu(self, key: str, label: str, mapping: dict, default: str) -> None:
        var = ctk.StringVar(value=default)
        self.vars[key] = var
        ctk.CTkLabel(self.form, text=label, anchor="w").grid(row=self._row, column=0, sticky="w", padx=6, pady=3)
        ctk.CTkOptionMenu(self.form, variable=var, values=list(mapping), width=320).grid(
            row=self._row, column=1, sticky="w", padx=6)
        self._row += 1
        setattr(self, f"_map_{key}", mapping)

    def _check(self, key: str, label: str, value: bool) -> None:
        var = ctk.StringVar(value="1" if value else "0")
        self.vars[key] = var
        ctk.CTkCheckBox(self.form, text=label, variable=var, onvalue="1", offvalue="0").grid(
            row=self._row, column=0, columnspan=2, sticky="w", padx=6, pady=3)
        self._row += 1

    # ---- conversion -----------------------------------------------------------
    def load_into_form(self, s: BookSettings) -> None:
        d = s.to_dict()
        for k, var in self.vars.items():
            if hasattr(self, f"_map_{k}"):
                mapping = getattr(self, f"_map_{k}")
                var.set(_rev(mapping, d[k]))
            elif isinstance(d[k], bool):
                var.set("1" if d[k] else "0")
            else:
                var.set(str(d[k]))
        self._update_info(s)

    def collect(self) -> BookSettings:
        d = BookSettings().to_dict()
        for k, var in self.vars.items():
            raw = var.get().strip()
            if hasattr(self, f"_map_{k}"):
                d[k] = getattr(self, f"_map_{k}")[raw]
            elif isinstance(d[k], bool):
                d[k] = raw == "1"
            elif isinstance(d[k], int):
                try:
                    d[k] = int(float(raw))
                except ValueError:
                    raise ValueError(f"'{raw}' is not a valid whole number for {k.replace('_', ' ')}.")
            elif isinstance(d[k], float):
                try:
                    d[k] = float(raw)
                except ValueError:
                    raise ValueError(f"'{raw}' is not a valid number for {k.replace('_', ' ')}.")
            else:
                d[k] = raw
        d["skip_failed"] = self.ctl.settings.skip_failed
        s = BookSettings.from_dict(d)
        problems = s.validate()
        if problems:
            raise ValueError("\n".join(problems))
        return s

    def apply(self, silent: bool = False) -> bool:
        try:
            s = self.collect()
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return False
        changed = s.layout_signature() != self.ctl.settings.layout_signature()
        self.ctl.settings = s
        if changed:
            self.ctl.inspections.clear()
        self._update_info(s)
        if not silent:
            self.app.set_status("Settings applied" + (" - inspection results cleared" if changed else ""))
        return True

    def reset(self) -> None:
        self.load_into_form(BookSettings())
        self.apply()

    def save(self) -> None:
        if not self.apply(silent=True):
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Settings", "*.json")],
                                            initialfile="kdpbuilder_settings.json")
        if path:
            self.ctl.settings.save(path)

    def load(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Settings", "*.json")])
        if not path:
            return
        try:
            s = BookSettings.load(path)
            problems = s.validate()
            if problems:
                raise ValueError("\n".join(problems))
        except Exception as exc:
            messagebox.showerror("Cannot load settings", str(exc))
            return
        self.load_into_form(s)
        self.apply()

    def _update_info(self, s: BookSettings) -> None:
        w, h = s.page_width_in * PT_PER_IN, s.page_height_in * PT_PER_IN
        ew, eh = s.expected_pixels
        r1, r2 = safe_rect(1, s), safe_rect(2, s)
        self.info.configure(text=(
            f"PDF page: {w:g} x {h:g} pt ({s.page_width_in:g} x {s.page_height_in:g} in).  "
            f"Expected source image: {ew} x {eh} px at {s.dpi_target} DPI.\n"
            f"Printable area page 1 (right-hand): x {r1.x0:g}-{r1.x1:g} pt, y {r1.y0:g}-{r1.y1:g} pt.  "
            f"Page 2 (left-hand): x {r2.x0:g}-{r2.x1:g} pt."))

    def on_show(self) -> None:
        self._update_info(self.ctl.settings)
