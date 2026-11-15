"""Exact KDP page geometry.

All coordinates are PDF points (1/72 inch) with the origin at the BOTTOM-LEFT
of the page, i.e. the same coordinate system ReportLab and the PDF format use.
"""

from __future__ import annotations

from dataclasses import dataclass

from .settings import BookSettings

PT_PER_IN = 72.0


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    def contains(self, other: "Rect", tol: float = 0.0) -> bool:
        return (
            other.x0 >= self.x0 - tol
            and other.y0 >= self.y0 - tol
            and other.x1 <= self.x1 + tol
            and other.y1 <= self.y1 + tol
        )


@dataclass(frozen=True)
class Placement:
    page_number: int
    side: str  # "recto" (right-hand page) or "verso" (left-hand page)
    inside_on_left: bool
    page: Rect
    trim: Rect
    safe: Rect
    image: Rect
    scale_pt_per_px: float
    img_w_px: int
    img_h_px: int

    @property
    def effective_dpi(self) -> float:
        return self.img_w_px / (self.image.width / PT_PER_IN)


def page_size_pt(s: BookSettings) -> tuple[float, float]:
    return (s.page_width_in * PT_PER_IN, s.page_height_in * PT_PER_IN)


def page_side(page_number: int) -> str:
    """Page 1 is always a right-hand (recto) page in a paperback interior."""
    return "recto" if page_number % 2 == 1 else "verso"


def inside_is_left(page_number: int, s: BookSettings) -> bool:
    recto = page_side(page_number) == "recto"
    return recto if s.binding == "left" else not recto


def page_rect(s: BookSettings) -> Rect:
    w, h = page_size_pt(s)
    return Rect(0.0, 0.0, w, h)


def trim_rect(page_number: int, s: BookSettings) -> Rect:
    """The trim box inside the page. Bleed (if any) is on the outside edge,
    the top and the bottom - never on the gutter side."""
    w, h = page_size_pt(s)
    b = s.bleed_amount_in * PT_PER_IN
    if b == 0:
        return Rect(0.0, 0.0, w, h)
    if inside_is_left(page_number, s):
        return Rect(0.0, b, w - b, h - b)
    return Rect(b, b, w, h - b)


def safe_rect(page_number: int, s: BookSettings) -> Rect:
    """Printable (safe) area: trim box minus the configured margins, with the
    inside margin on the gutter side of each page."""
    t = trim_rect(page_number, s)
    inside = s.inside_margin_in * PT_PER_IN
    outside = s.outside_margin_in * PT_PER_IN
    top = s.top_margin_in * PT_PER_IN
    bottom = s.bottom_margin_in * PT_PER_IN
    if inside_is_left(page_number, s):
        x0, x1 = t.x0 + inside, t.x1 - outside
    else:
        x0, x1 = t.x0 + outside, t.x1 - inside
    return Rect(x0, t.y0 + bottom, x1, t.y1 - top)


def fit_scale(img_w: int, img_h: int, safe: Rect) -> float:
    """scale = min(printable_width / original_width, printable_height / original_height)"""
    return min(safe.width / img_w, safe.height / img_h)


def compute_placement(img_w: int, img_h: int, page_number: int, s: BookSettings) -> Placement:
    if img_w <= 0 or img_h <= 0:
        raise ValueError("Image dimensions must be positive.")
    safe = safe_rect(page_number, s)
    base = fit_scale(img_w, img_h, safe)
    if s.placement == "fit":
        scale = base
        dx = dy = 0.0
    elif s.placement == "center":
        scale = PT_PER_IN / s.dpi_target  # native size at the target DPI
        dx = dy = 0.0
    else:  # custom
        scale = base * s.custom_scale
        dx = s.custom_offset_x_in * PT_PER_IN
        dy = s.custom_offset_y_in * PT_PER_IN
    w, h = img_w * scale, img_h * scale
    cx = (safe.x0 + safe.x1) / 2 + dx
    cy = (safe.y0 + safe.y1) / 2 + dy
    image = Rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return Placement(
        page_number=page_number,
        side=page_side(page_number),
        inside_on_left=inside_is_left(page_number, s),
        page=page_rect(s),
        trim=trim_rect(page_number, s),
        safe=safe,
        image=image,
        scale_pt_per_px=scale,
        img_w_px=img_w,
        img_h_px=img_h,
    )


def edge_distances_in(inner: Rect, trim: Rect) -> dict[str, float]:
    """Distance (inches) from `inner` to each trim edge. Negative = beyond the edge."""
    return {
        "left": (inner.x0 - trim.x0) / PT_PER_IN,
        "right": (trim.x1 - inner.x1) / PT_PER_IN,
        "top": (trim.y1 - inner.y1) / PT_PER_IN,
        "bottom": (inner.y0 - trim.y0) / PT_PER_IN,
    }
