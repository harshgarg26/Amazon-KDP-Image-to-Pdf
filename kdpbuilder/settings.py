"""Book, layout and processing settings."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path

PLACEMENT_MODES = ("fit", "center", "custom")
COLOR_MODES = ("preserve", "grayscale")
BINDINGS = ("left", "right")

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


@dataclass
class BookSettings:
    # --- book ---------------------------------------------------------
    trim_width_in: float = 8.5
    trim_height_in: float = 11.0
    dpi_target: int = 300
    bleed: bool = False
    bleed_in: float = 0.125
    interior: str = "bw"  # "bw" or "color" (affects colour-pixel warnings only)

    # --- margins (inches, measured from the trim edge) ------------------
    inside_margin_in: float = 0.5
    outside_margin_in: float = 0.5
    top_margin_in: float = 0.5
    bottom_margin_in: float = 0.5
    binding: str = "left"  # "left": page 1 is a right-hand page, gutter on its left

    # --- placement ----------------------------------------------------
    placement: str = "fit"  # fit | center | custom
    custom_scale: float = 1.0  # multiplier on the fit scale (custom mode)
    custom_offset_x_in: float = 0.0  # + moves right (custom mode)
    custom_offset_y_in: float = 0.0  # + moves up (custom mode)

    # --- image normalisation -----------------------------------------
    background_color: str = "#FFFFFF"
    color_mode: str = "preserve"  # preserve | grayscale
    # Optional modifications. ALL are disabled by default.
    near_white_clean: bool = False
    near_white_threshold: int = 245
    bw_threshold: bool = False
    bw_threshold_value: int = 128
    contrast_adjust: bool = False
    contrast_factor: float = 1.0

    # --- run behaviour ------------------------------------------------
    skip_failed: bool = True
    kdp_min_margin_in: float = 0.25  # commonly cited minimum margin; warning only
    dpi_error_threshold: int = 150  # effective DPI below this is a failure
    preview_dpi: int = 100

    # ------------------------------------------------------------------
    @property
    def bleed_amount_in(self) -> float:
        return self.bleed_in if self.bleed else 0.0

    @property
    def page_width_in(self) -> float:
        return self.trim_width_in + self.bleed_amount_in

    @property
    def page_height_in(self) -> float:
        return self.trim_height_in + 2 * self.bleed_amount_in

    @property
    def expected_pixels(self) -> tuple[int, int]:
        return (
            round(self.page_width_in * self.dpi_target),
            round(self.page_height_in * self.dpi_target),
        )

    @property
    def background_rgb(self) -> tuple[int, int, int]:
        m = _HEX_RE.match(self.background_color.strip())
        if not m:
            return (255, 255, 255)
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    @property
    def background_is_white(self) -> bool:
        return self.background_rgb == (255, 255, 255)

    # ------------------------------------------------------------------
    def validate(self) -> list[str]:
        """Return a list of human readable problems (empty = valid)."""
        errs: list[str] = []
        if not (1.0 <= self.trim_width_in <= 40 and 1.0 <= self.trim_height_in <= 40):
            errs.append("Trim width/height must be between 1 and 40 inches.")
        if not (30 <= self.dpi_target <= 2400):
            errs.append("DPI target must be between 30 and 2400.")
        if self.bleed and not (0 < self.bleed_in <= 1):
            errs.append("Bleed must be greater than 0 and at most 1 inch.")
        for name in ("inside_margin_in", "outside_margin_in", "top_margin_in", "bottom_margin_in"):
            if getattr(self, name) < 0:
                errs.append(f"{name.replace('_', ' ')} cannot be negative.")
        if self.inside_margin_in + self.outside_margin_in >= self.trim_width_in:
            errs.append("Inside + outside margins leave no printable width.")
        if self.top_margin_in + self.bottom_margin_in >= self.trim_height_in:
            errs.append("Top + bottom margins leave no printable height.")
        if self.placement not in PLACEMENT_MODES:
            errs.append(f"Placement must be one of {PLACEMENT_MODES}.")
        if self.color_mode not in COLOR_MODES:
            errs.append(f"Color mode must be one of {COLOR_MODES}.")
        if self.binding not in BINDINGS:
            errs.append(f"Binding must be one of {BINDINGS}.")
        if self.interior not in ("bw", "color"):
            errs.append("Interior must be 'bw' or 'color'.")
        if not _HEX_RE.match(self.background_color.strip()):
            errs.append("Background colour must be a hex value such as #FFFFFF.")
        if self.custom_scale <= 0:
            errs.append("Custom scale must be greater than 0.")
        if not (0 <= self.near_white_threshold <= 255):
            errs.append("Near-white threshold must be 0-255.")
        if not (0 <= self.bw_threshold_value <= 255):
            errs.append("Black & white threshold must be 0-255.")
        if self.contrast_factor <= 0:
            errs.append("Contrast factor must be greater than 0.")
        if not (30 <= self.preview_dpi <= 300):
            errs.append("Preview DPI must be between 30 and 300.")
        return errs

    @property
    def any_modification_enabled(self) -> bool:
        return bool(
            self.color_mode != "preserve"
            or self.near_white_clean
            or self.bw_threshold
            or (self.contrast_adjust and abs(self.contrast_factor - 1.0) > 1e-9)
            or not self.background_is_white
        )

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BookSettings":
        """Build settings from untrusted data (e.g. a JSON file): unknown keys are ignored and
        every value must have the same type as its default, otherwise ValueError is raised."""
        if not isinstance(data, dict):
            raise ValueError("Settings file must contain a JSON object.")
        defaults = cls()
        clean: dict = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            value, default = data[f.name], getattr(defaults, f.name)
            if isinstance(default, bool):
                ok = isinstance(value, bool)
            elif isinstance(default, int):
                ok = isinstance(value, int) and not isinstance(value, bool)
            elif isinstance(default, float):
                ok = isinstance(value, (int, float)) and not isinstance(value, bool)
                value = float(value) if ok else value
            else:
                ok = isinstance(value, str) and len(value) <= 64
            if not ok:
                raise ValueError(f"Invalid value for setting '{f.name}'.")
            clean[f.name] = value
        return cls(**clean)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "BookSettings":
        p = Path(path)
        if p.stat().st_size > 64 * 1024:
            raise ValueError("Settings file is unexpectedly large.")
        return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def _signature(self, names: tuple[str, ...]) -> str:
        payload = json.dumps({n: getattr(self, n) for n in names}, sort_keys=True)
        return hashlib.sha1(payload.encode()).hexdigest()[:12]

    def processing_signature(self) -> str:
        """Hash of every setting that changes processed pixel data."""
        return self._signature(
            (
                "background_color", "color_mode", "near_white_clean", "near_white_threshold",
                "bw_threshold", "bw_threshold_value", "contrast_adjust", "contrast_factor",
                "dpi_target",
            )
        )

    def layout_signature(self) -> str:
        """Hash of every setting (used to cache inspection results)."""
        return self._signature(tuple(f.name for f in fields(self)))
