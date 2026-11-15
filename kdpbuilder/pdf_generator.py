"""PDF generation with ReportLab.

One image per page, exact page size, the whole image object positioned inside the
printable area (never a full-page image), lossless embedding, no extras."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from reportlab import rl_config
from reportlab.pdfgen import canvas as rl_canvas

from . import APP_NAME, __version__, layout
from .importer import ImageRecord
from .settings import BookSettings


class GenerationCancelled(Exception):
    pass


@dataclass
class PageEntry:
    page_number: int
    record: ImageRecord
    processed_path: str
    width_px: int
    height_px: int
    inspection: object | None = None  # InspectionResult


def generate_pdf(
    entries: list[PageEntry],
    settings: BookSettings,
    pdf_path: str | Path,
    progress: Callable[[int, int, str], None] | None = None,
    cancel: threading.Event | None = None,
) -> list[layout.Placement]:
    """Write the manuscript. Returns the intended placement of every page."""
    if not entries:
        raise ValueError("No pages to write.")
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = pdf_path.with_suffix(".tmp.pdf")
    page_w, page_h = layout.page_size_pt(settings)
    rl_config.useA85 = 0  # plain Flate (lossless) streams, no ASCII85 size overhead

    c = rl_canvas.Canvas(
        str(tmp_path), pagesize=(page_w, page_h), pageCompression=1, enforceColorSpace=None
    )
    c.setTitle("KDP interior manuscript")
    c.setAuthor("")
    c.setCreator(f"{APP_NAME} {__version__}")
    c.setProducer(f"{APP_NAME} {__version__} (ReportLab)")
    c.setSubject("Amazon KDP paperback interior")
    placements: list[layout.Placement] = []
    try:
        for i, e in enumerate(entries, 1):
            if cancel is not None and cancel.is_set():
                raise GenerationCancelled()
            if progress:
                progress(i, len(entries), e.record.filename)
            pl = layout.compute_placement(e.width_px, e.height_px, e.page_number, settings)
            placements.append(pl)
            # consistent boxes on every page (PDF coordinate system, bottom-left origin)
            c.setPageSize((page_w, page_h))
            c.setCropBox((0, 0, page_w, page_h))
            if settings.bleed:
                t = pl.trim
                c.setTrimBox((t.x0, t.y0, t.x1, t.y1))
                c.setBleedBox((0, 0, page_w, page_h))
            if not settings.background_is_white:
                r, g, b = (v / 255.0 for v in settings.background_rgb)
                c.setFillColorRGB(r, g, b)
                c.rect(0, 0, page_w, page_h, stroke=0, fill=1)
            c.drawImage(
                e.processed_path,
                pl.image.x0,
                pl.image.y0,
                width=pl.image.width,
                height=pl.image.height,
                mask=None,
                preserveAspectRatio=False,  # the placement already preserves the ratio
            )
            c.showPage()
        c.save()
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    tmp_path.replace(pdf_path)
    return placements
