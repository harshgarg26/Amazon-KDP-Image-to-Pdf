"""Independent post-generation validation of the finished PDF.

The PDF is re-opened from disk with pikepdf (structure) and PyMuPDF (placement and
rendering). Nothing here trusts the generator's own bookkeeping: image positions,
sizes and pixels are read back from the file, and every page is rendered and compared
with its source image.

These are INTERNAL checks. They are not an Amazon KDP Print Previewer result."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pikepdf
from PIL import Image

try:  # PyMuPDF >= 1.24.3 exposes `pymupdf`; older releases use `fitz`
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

from . import KDP_DISCLAIMER, layout
from .inspector import ERROR, GREEN, INFO, RED, WARNING, YELLOW, Finding
from .pdf_generator import PageEntry
from .processor import load_flattened
from .settings import BookSettings

TOL_PT = 0.02  # tolerance for page-size / placement comparisons (points)


@dataclass
class PageValidation:
    pdf_page: int
    filename: str
    original_width_px: int = 0
    original_height_px: int = 0
    effective_dpi: float | None = None
    page_width_pt: float | None = None
    page_height_pt: float | None = None
    image_x0_pt: float | None = None
    image_y0_pt: float | None = None
    image_x1_pt: float | None = None
    image_y1_pt: float | None = None
    image_width_pt: float | None = None
    image_height_pt: float | None = None
    margin_left_in: float | None = None
    margin_right_in: float | None = None
    margin_top_in: float | None = None
    margin_bottom_in: float | None = None
    embedded_width_px: int | None = None
    embedded_height_px: int | None = None
    transparency_status: str = "UNKNOWN"  # NONE | DETECTED
    boundary_status: str = "UNKNOWN"  # PASS | WARN | FAIL
    embedded_matches_processed: bool | None = None
    render_mean_diff: float | None = None
    render_bad_blocks: int | None = None
    status: str = GREEN
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: str, code: str, message: str) -> None:
        self.findings.append(Finding(severity, code, message))

    def finalize(self) -> "PageValidation":
        sev = {f.severity for f in self.findings}
        self.status = RED if ERROR in sev else YELLOW if WARNING in sev else GREEN
        return self


@dataclass
class ValidationReport:
    pdf_path: str
    pages: list[PageValidation] = field(default_factory=list)
    doc_findings: list[Finding] = field(default_factory=list)
    expected_pages: int = 0
    actual_pages: int = 0
    integrity_ok: bool = False
    page_sizes_pt: list[tuple[float, float]] = field(default_factory=list)
    disclaimer: str = KDP_DISCLAIMER

    @property
    def overall_status(self) -> str:
        statuses = {p.status for p in self.pages}
        sev = {f.severity for f in self.doc_findings}
        if RED in statuses or ERROR in sev:
            return RED
        if YELLOW in statuses or WARNING in sev:
            return YELLOW
        return GREEN

    @property
    def passed(self) -> bool:
        """True only if nothing failed. Warnings (yellow) do not fail the PDF."""
        return self.overall_status != RED

    def to_dict(self) -> dict:
        d = asdict(self)
        d["overall_status"] = self.overall_status
        d["passed"] = self.passed
        return d


def _pdf_syntax_problems(pdf: pikepdf.Pdf) -> list[str]:
    check = getattr(pdf, "check", None)
    if callable(check):
        return [str(p) for p in check()]
    check = getattr(pdf, "check_pdf_syntax", None)
    if callable(check):
        return [str(p) for p in check()]
    return []


def _pixmap_array(doc, xref: int) -> np.ndarray:
    pm = fitz.Pixmap(doc, xref)
    if pm.alpha or pm.colorspace is None or (pm.n - pm.alpha) not in (1, 3):
        pm = fitz.Pixmap(fitz.csRGB, pm)
    arr = np.frombuffer(pm.samples, dtype=np.uint8)
    stride = pm.stride
    arr = arr.reshape(pm.height, stride)[:, : pm.width * pm.n]
    return arr.reshape(pm.height, pm.width, pm.n)


def _as_rgb(arr: np.ndarray) -> np.ndarray:
    if arr.ndim == 2:
        arr = arr[:, :, None]
    if arr.shape[2] == 1:
        return np.repeat(arr, 3, axis=2)
    return arr[:, :, :3]


def _block_means(a: np.ndarray, bs: int) -> np.ndarray:
    h, w = a.shape
    nby, nbx = h // bs, w // bs
    return a[: nby * bs, : nbx * bs].reshape(nby, bs, nbx, bs).mean(axis=(1, 3))


def _image_xobjects(pkpage) -> list:
    out = []
    res = pkpage.obj.get("/Resources")
    xobj = res.get("/XObject") if res is not None else None
    if xobj is None:
        return out
    for name in xobj.keys():
        obj = xobj[name]
        if obj.get("/Subtype") == "/Image":
            out.append((str(name), obj))
    return out


def validate_pdf(
    pdf_path: str | Path,
    entries: list[PageEntry],
    settings: BookSettings,
    previews_dir: str | Path | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    cancel: threading.Event | None = None,
    compare_render: bool = True,
) -> ValidationReport:
    pdf_path = Path(pdf_path)
    report = ValidationReport(pdf_path=str(pdf_path), expected_pages=len(entries))

    def doc_add(sev: str, code: str, msg: str) -> None:
        report.doc_findings.append(Finding(sev, code, msg))

    # ---------------- structure (pikepdf) ----------------
    try:
        pk = pikepdf.open(pdf_path)
    except Exception as exc:
        doc_add(ERROR, "PDF_UNREADABLE", f"The PDF cannot be opened: {exc}")
        return report
    problems = _pdf_syntax_problems(pk)
    report.integrity_ok = not problems
    for pr in problems[:10]:
        doc_add(ERROR, "PDF_STRUCTURE", f"PDF structure problem: {pr}")
    report.actual_pages = len(pk.pages)
    if report.actual_pages != len(entries):
        doc_add(ERROR, "PAGE_COUNT",
                f"PDF has {report.actual_pages} pages but {len(entries)} were expected.")
    if "/OCProperties" in pk.Root:
        doc_add(WARNING, "LAYERS", "The PDF contains optional-content layers; none should be present.")
    if "/Encrypt" in pk.trailer:
        doc_add(ERROR, "ENCRYPTED", "The PDF is encrypted; KDP requires an unencrypted file.")

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        doc_add(ERROR, "PDF_UNREADABLE", f"The PDF cannot be rendered: {exc}")
        return report

    exp_w, exp_h = layout.page_size_pt(settings)
    previews = Path(previews_dir) if previews_dir else None
    if previews:
        previews.mkdir(parents=True, exist_ok=True)
    n = min(len(entries), len(pk.pages), doc.page_count)
    sizes = []
    mods_enabled = settings.any_modification_enabled
    ref_settings = BookSettings.from_dict(settings.to_dict())
    ref_settings.color_mode = "preserve"

    for i in range(n):
        if cancel is not None and cancel.is_set():
            doc_add(WARNING, "CANCELLED", "Validation was cancelled before every page was checked.")
            break
        e = entries[i]
        if progress:
            progress(i + 1, n, e.record.filename)
        pv = PageValidation(pdf_page=i + 1, filename=e.record.filename,
                            original_width_px=e.record.oriented_width or e.width_px,
                            original_height_px=e.record.oriented_height or e.height_px)
        report.pages.append(pv)
        try:
            _validate_page(pv, e, pk.pages[i], doc[i], doc, settings, exp_w, exp_h,
                           previews, compare_render, mods_enabled, ref_settings)
        except Exception as exc:  # a validator bug must never pass a page silently
            pv.add(ERROR, "VALIDATION_ERROR", f"Validation could not complete for this page: {exc}")
        sizes.append((pv.page_width_pt, pv.page_height_pt))
        pv.finalize()
    report.page_sizes_pt = [s for s in sizes if s[0] is not None]
    if len({(round(a, 2), round(b, 2)) for a, b in report.page_sizes_pt}) > 1:
        doc_add(ERROR, "PAGE_SIZES", "Pages do not all share the same size.")
    doc.close()
    pk.close()
    return report


def _validate_page(pv, e, pkpage, page, doc, s, exp_w, exp_h, previews, compare_render,
                   mods_enabled, ref_settings):
    # ---- page boxes / size / orientation ----
    mb = [float(x) for x in pkpage.mediabox]
    cb = [float(x) for x in pkpage.cropbox]
    pw, ph = mb[2] - mb[0], mb[3] - mb[1]
    pv.page_width_pt, pv.page_height_pt = round(pw, 3), round(ph, 3)
    if abs(pw - exp_w) > TOL_PT or abs(ph - exp_h) > TOL_PT:
        pv.add(ERROR, "PAGE_SIZE", f"Page is {pw:.2f} x {ph:.2f} pt, expected {exp_w:.2f} x {exp_h:.2f} pt.")
    if any(abs(a - b) > TOL_PT for a, b in zip(mb, cb)):
        pv.add(ERROR, "CROPBOX", f"CropBox {cb} differs from MediaBox {mb}.")
    if abs(mb[0]) > TOL_PT or abs(mb[1]) > TOL_PT:
        pv.add(WARNING, "MEDIABOX_ORIGIN", f"MediaBox does not start at (0, 0): {mb}.")
    if (pw < ph) != (exp_w < exp_h):
        pv.add(ERROR, "ORIENTATION", "Page orientation differs from the configured orientation.")
    if int(pkpage.obj.get("/Rotate", 0) or 0) % 360 != 0:
        pv.add(ERROR, "ROTATED_PAGE", "Page has a /Rotate entry; pages must be unrotated.")

    # ---- transparency ----
    img_objs = _image_xobjects(pkpage)
    has_transparency = False
    for _, obj in img_objs:
        if obj.get("/SMask") is not None or obj.get("/Mask") is not None:
            has_transparency = True
    grp = pkpage.obj.get("/Group")
    if grp is not None and grp.get("/S") == "/Transparency":
        pv.add(WARNING, "TRANSPARENCY_GROUP", "Page declares a transparency group.")
    pv.transparency_status = "DETECTED" if has_transparency else "NONE"
    if has_transparency:
        pv.add(ERROR, "TRANSPARENCY", "Unexpected transparency (soft mask / mask) found on an image.")

    # ---- images ----
    infos = page.get_image_info(xrefs=True)
    if len(infos) == 0:
        pv.add(ERROR, "NO_IMAGE", "No image found on this page (missing image).")
        pv.boundary_status = "FAIL"
        return
    if len(infos) > 1:
        pv.add(ERROR, "MULTI_IMAGE", f"{len(infos)} images found; exactly one is expected per page.")
    info = infos[0]
    x0, ytop, x1, ybot = info["bbox"]  # PyMuPDF: top-left origin
    H = page.rect.height
    img = layout.Rect(x0, H - ybot, x1, H - ytop)  # back to PDF coordinates (bottom-left origin)
    pv.image_x0_pt, pv.image_y0_pt = round(img.x0, 3), round(img.y0, 3)
    pv.image_x1_pt, pv.image_y1_pt = round(img.x1, 3), round(img.y1, 3)
    pv.image_width_pt, pv.image_height_pt = round(img.width, 3), round(img.height, 3)
    pv.embedded_width_px, pv.embedded_height_px = int(info["width"]), int(info["height"])
    t = info.get("transform")
    if t and (abs(t[1]) > 1e-4 or abs(t[2]) > 1e-4):
        pv.add(ERROR, "IMAGE_ROTATED", "Image is rotated or skewed on the page.")

    # embedded size == processed size (no unwanted resampling)
    if (pv.embedded_width_px, pv.embedded_height_px) != (e.width_px, e.height_px):
        pv.add(ERROR, "EMBED_SIZE",
               f"Embedded image is {pv.embedded_width_px} x {pv.embedded_height_px} px, expected "
               f"{e.width_px} x {e.height_px} px (the image was resampled).")
    # aspect ratio preserved
    if img.width > 0 and img.height > 0:
        a_img = img.width / img.height
        a_px = pv.embedded_width_px / pv.embedded_height_px
        if abs(a_img / a_px - 1) > 0.002:
            pv.add(ERROR, "DISTORTED",
                   f"Image is distorted: placed ratio {a_img:.4f} vs pixel ratio {a_px:.4f}.")
        dpi_x = pv.embedded_width_px / (img.width / 72.0)
        dpi_y = pv.embedded_height_px / (img.height / 72.0)
        pv.effective_dpi = round(min(dpi_x, dpi_y), 1)
        if pv.effective_dpi < s.dpi_error_threshold:
            pv.add(ERROR, "LOW_RES", f"Effective resolution {pv.effective_dpi:.0f} DPI is below the "
                   f"internal failure threshold of {s.dpi_error_threshold} DPI.")
        elif pv.effective_dpi < s.dpi_target * 0.98:
            pv.add(WARNING, "LOW_RES", f"Effective resolution {pv.effective_dpi:.0f} DPI is below the "
                   f"{s.dpi_target} DPI target.")

    # ---- safe-area / boundary validation ----
    trim = layout.trim_rect(e.page_number, s)
    safe = layout.safe_rect(e.page_number, s)
    dist = layout.edge_distances_in(img, trim)
    pv.margin_left_in, pv.margin_right_in = round(dist["left"], 4), round(dist["right"], 4)
    pv.margin_top_in, pv.margin_bottom_in = round(dist["top"], 4), round(dist["bottom"], 4)
    page_rect = layout.page_rect(s)
    if not page_rect.contains(img, tol=TOL_PT):
        pv.boundary_status = "FAIL"
        pv.add(ERROR, "IMAGE_OFF_PAGE", "Image object extends beyond the page edge.")
    elif min(dist.values()) < -TOL_PT / 72.0:
        pv.boundary_status = "FAIL"
        sides = [k for k, v in dist.items() if v < -TOL_PT / 72.0]
        pv.add(ERROR, "IMAGE_BEYOND_TRIM", "Image object extends beyond the trim edge ("
               + ", ".join(sides) + ").")
    elif not safe.contains(img, tol=TOL_PT):
        pv.boundary_status = "WARN"
        # safe margins per side for the message
        want = {
            "left": (safe.x0 - trim.x0) / 72.0, "right": (trim.x1 - safe.x1) / 72.0,
            "top": (trim.y1 - safe.y1) / 72.0, "bottom": (safe.y0 - trim.y0) / 72.0,
        }
        sides = [f"{k} ({dist[k]:.3f} in, needs {want[k]:.3f} in)" for k in dist
                 if dist[k] < want[k] - TOL_PT / 72.0]
        pv.add(WARNING, "IMAGE_OUTSIDE_SAFE",
               "Image object exceeds the configured safe area: " + ", ".join(sides) + ".")
    else:
        pv.boundary_status = "PASS"
        close = [k for k, v in dist.items() if v < s.kdp_min_margin_in - 1e-6]
        if close:
            pv.boundary_status = "WARN"
            pv.add(WARNING, "NEAR_TRIM",
                   f"Image object is closer than {s.kdp_min_margin_in:g} in to the trim edge ("
                   + ", ".join(close) + "). Check KDP's margin requirements for your book.")

    # ---- fonts / text ----
    if page.get_text("text").strip():
        pv.add(WARNING, "TEXT_PRESENT", "Unexpected text found on the page (none should be added).")

    # ---- embedded pixels identical to the processed image (lossless embedding / order) ----
    xref = int(info.get("xref") or 0)
    if xref:
        emb = _as_rgb(_pixmap_array(doc, xref))
        with Image.open(e.processed_path) as pim:
            pim.load()
            proc = _as_rgb(np.asarray(pim.convert("L") if pim.mode == "L" else pim.convert("RGB")))
        if emb.shape == proc.shape and np.array_equal(emb, proc):
            pv.embedded_matches_processed = True
        else:
            pv.embedded_matches_processed = False
            if emb.shape != proc.shape:
                pv.add(ERROR, "EMBED_MISMATCH", "Embedded image does not match the processed image "
                       f"(shape {emb.shape} vs {proc.shape}) - wrong page order or resampling.")
            else:
                diff = int(np.abs(emb.astype(np.int16) - proc.astype(np.int16)).max())
                pv.add(ERROR, "EMBED_MISMATCH",
                       f"Embedded image pixels differ from the processed image (max difference {diff}) "
                       "- wrong page order or lossy re-encoding.")
    else:
        pv.add(WARNING, "INLINE_IMAGE", "Image is inline (no XObject); pixel identity was not verified.")

    # ---- render + compare against the source image ----
    R = s.preview_dpi
    pix = page.get_pixmap(dpi=R, alpha=False)
    rendered = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if previews is not None:
        rendered.save(previews / f"page_{e.page_number:04d}.png")
    rgray = np.asarray(rendered.convert("L"), dtype=np.float32)
    source_has_ink = True
    insp = e.inspection
    if insp is not None and getattr(insp, "bbox_px", None) is None and not getattr(insp, "decode_failed", False):
        source_has_ink = False
    if rgray.min() >= 250:
        if source_has_ink:
            pv.add(ERROR, "BLANK_PAGE", "The page renders blank but its source image contains artwork.")
        else:
            pv.add(WARNING, "BLANK_PAGE", "Blank page (the source image is blank too).")
    if compare_render:
        ref, _ = load_flattened(e.record.path, ref_settings, apply_modifications=False)
        pw_px = max(1, round(img.width * R / 72.0))
        ph_px = max(1, round(img.height * R / 72.0))
        canvas = Image.new("L", (pix.width, pix.height), 255)
        resized = ref.convert("L").resize((pw_px, ph_px), Image.LANCZOS)
        canvas.paste(resized, (round(img.x0 * R / 72.0), round(ytop * R / 72.0)))
        cgray = np.asarray(canvas, dtype=np.float32)
        mean_diff = float(np.abs(rgray - cgray).mean())
        bs = 16
        bad = int((np.abs(_block_means(rgray, bs) - _block_means(cgray, bs)) > 40).sum())
        pv.render_mean_diff, pv.render_bad_blocks = round(mean_diff, 3), bad
        if mods_enabled:
            if bad or mean_diff >= 2.5:
                pv.add(INFO, "RENDER_DIFF_EXPECTED",
                       f"Rendered page differs from the original image (mean {mean_diff:.2f}, {bad} blocks) - "
                       "expected because optional image modifications are enabled.")
        elif bad >= 5 or mean_diff >= 5:
            pv.add(ERROR, "RENDER_DIFF",
                   f"Rendered page differs from the source image (mean difference {mean_diff:.2f}, "
                   f"{bad} blocks differ strongly) - missing content, patches or black blocks.")
        elif bad >= 1 or mean_diff >= 2.5:
            pv.add(WARNING, "RENDER_DIFF",
                   f"Rendered page differs slightly from the source image (mean {mean_diff:.2f}, "
                   f"{bad} blocks) - inspect the page preview.")
