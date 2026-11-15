"""Pre-PDF image quality and boundary inspection.

Everything here only REPORTS - nothing is ever modified or erased. White pixels are
not assumed to be errors and gray illustration details are left alone; unusual
findings are raised as warnings for a human to review.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass, field

import numpy as np

from . import layout
from .importer import ImageRecord
from .processor import LoadInfo, load_flattened
from .settings import BookSettings

INFO, WARNING, ERROR = "INFO", "WARNING", "ERROR"
GREEN, YELLOW, RED = "GREEN", "YELLOW", "RED"


@dataclass
class Finding:
    severity: str
    code: str
    message: str


@dataclass
class Thresholds:
    ink_level: int = 235  # gray value below this counts as artwork
    min_ink_per_line: int = 3  # ignore isolated specks when finding the bounding box
    large_margin_frac: float = 0.20
    tight_margin_frac: float = 0.01
    centered_tol_frac: float = 0.03
    small_art_area_frac: float = 0.25  # artwork area / safe area on the page
    chroma_level: int = 30
    colored_frac_warn: float = 0.0005
    flat_std: float = 1.5
    gray_lo: int = 40
    gray_hi: int = 230
    gray_patch_area_frac: float = 0.0015
    black_patch_area_frac: float = 0.015
    noise_block_frac: float = 0.03
    jpeg_block_ratio: float = 1.15
    aspect_tol: float = 0.01


DEFAULT_THRESHOLDS = Thresholds()


@dataclass
class InspectionResult:
    filename: str
    path: str
    page_number: int
    width_px: int = 0
    height_px: int = 0
    status: str = GREEN
    findings: list[Finding] = field(default_factory=list)
    bbox_px: tuple[int, int, int, int] | None = None  # x0, y0, x1, y1 (x1/y1 exclusive)
    margins_px: dict | None = None
    margins_pct: dict | None = None
    art_margins_in: dict | None = None  # artwork -> trim edges as laid out on the page
    effective_dpi: float | None = None
    transparent_fraction: float = 0.0
    colored_fraction: float = 0.0
    decode_failed: bool = False
    stats: dict = field(default_factory=dict)

    def add(self, severity: str, code: str, message: str) -> None:
        self.findings.append(Finding(severity, code, message))

    def finalize(self) -> "InspectionResult":
        sev = {f.severity for f in self.findings}
        self.status = RED if ERROR in sev else YELLOW if WARNING in sev else GREEN
        return self

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == WARNING]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "InspectionResult":
        d = dict(d)
        d["findings"] = [Finding(**f) for f in d.get("findings", [])]
        if d.get("bbox_px") is not None:
            d["bbox_px"] = tuple(d["bbox_px"])
        return cls(**d)


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _components(mask: np.ndarray) -> list[tuple[int, bool, list[tuple[int, int]]]]:
    """4-connected components of a small boolean block grid.
    Returns (size, touches_edge, cells)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    for sy, sx in zip(*np.nonzero(mask)):
        if seen[sy, sx]:
            continue
        q = deque([(sy, sx)])
        seen[sy, sx] = True
        cells = []
        touches = False
        while q:
            y, x = q.popleft()
            cells.append((y, x))
            if y in (0, h - 1) or x in (0, w - 1):
                touches = True
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        out.append((len(cells), touches, cells))
    return out


def _block_stats(gray: np.ndarray, bs: int):
    h, w = gray.shape
    nby, nbx = h // bs, w // bs
    if nby < 2 or nbx < 2:
        return None
    view = gray[: nby * bs, : nbx * bs].reshape(nby, bs, nbx, bs)
    f = view.astype(np.float32)
    mean = f.mean(axis=(1, 3))
    std = f.std(axis=(1, 3))
    bmin = view.min(axis=(1, 3))
    bmax = view.max(axis=(1, 3))
    return mean, std, bmin, bmax


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


# ----------------------------------------------------------------------
# main entry point
# ----------------------------------------------------------------------
def inspect_record(
    record: ImageRecord,
    page_number: int,
    settings: BookSettings,
    th: Thresholds = DEFAULT_THRESHOLDS,
    load_cache: tuple | None = None,
) -> InspectionResult:
    res = InspectionResult(filename=record.filename, path=record.path, page_number=page_number)
    if record.error:
        res.decode_failed = True
        res.add(ERROR, "OPEN_FAILED", f"Image cannot be used: {record.error}")
        return res.finalize()
    try:
        if load_cache is not None:
            img, info = load_cache
        else:
            img, info = load_flattened(record.path, settings, apply_modifications=False)
    except Exception as exc:  # corrupted, truncated, unsupported variant ...
        res.decode_failed = True
        res.add(ERROR, "DECODE_FAILED", f"Image is corrupted or could not be decoded: {exc}")
        return res.finalize()

    w, h = img.size
    res.width_px, res.height_px = w, h
    rgb = np.asarray(img.convert("RGB"))
    gray = np.asarray(img.convert("L"))
    res.transparent_fraction = info.transparent_fraction

    _check_dimensions(res, record, settings, th)
    placement = layout.compute_placement(w, h, page_number, settings)
    res.effective_dpi = placement.effective_dpi
    _check_resolution(res, placement, settings)
    _check_transparency(res, info)
    _check_ink_geometry(res, gray, placement, settings, th)
    _check_edges(res, gray, th)
    _check_pixels(res, rgb, gray, record, settings, th)
    for note in info.notes:
        res.add(INFO, "LOAD_NOTE", note)
    if record.dpi is not None:
        dx, dy = record.dpi
        if dx <= 0 or dy <= 0 or dx > 2400 or dy > 2400 or abs(dx - dy) > 1:
            res.add(INFO, "ODD_DPI_METADATA",
                    f"DPI metadata is unusual ({record.dpi_text}). It is ignored: placement uses pixel "
                    "dimensions and the layout, not file metadata.")
        elif abs(dx - settings.dpi_target) > 1:
            res.add(INFO, "DPI_METADATA",
                    f"DPI metadata ({record.dpi_text}) differs from the {settings.dpi_target} DPI target. "
                    "It is ignored; the effective DPI is calculated from the final placement.")
    return res.finalize()


# ----------------------------------------------------------------------
# individual checks
# ----------------------------------------------------------------------
def _check_dimensions(res, record, s, th):
    w, h = res.width_px, res.height_px
    ew, eh = s.expected_pixels
    if (w, h) != (ew, eh):
        res.add(INFO, "DIM_DIFFERS", f"Image is {w} x {h} px; the configured page is {ew} x {eh} px.")
    page_aspect = s.page_width_in / s.page_height_in
    aspect = w / h
    page_portrait = page_aspect < 1
    if (aspect < 1) != page_portrait and abs(aspect - 1) > 0.02:
        res.add(WARNING, "ORIENTATION",
                f"{'Landscape' if aspect > 1 else 'Portrait'} image on a "
                f"{'portrait' if page_portrait else 'landscape'} page: it will be scaled down to fit "
                "(never rotated, cropped or stretched).")
    elif abs(aspect / page_aspect - 1) > th.aspect_tol:
        res.add(WARNING, "ASPECT_RATIO",
                f"Aspect ratio {aspect:.4f} differs from the page ratio {page_aspect:.4f}; the image will be "
                "fitted with extra white space, never stretched.")
    if record.exif_orientation != 1:
        res.add(INFO, "EXIF_ORIENTATION",
                f"EXIF orientation {record.exif_orientation} was applied so the image appears upright.")


def _check_resolution(res, placement, s):
    dpi = placement.effective_dpi
    if dpi < s.dpi_error_threshold:
        res.add(ERROR, "LOW_RES",
                f"Effective resolution is {dpi:.0f} DPI at the placed size - far below the "
                f"{s.dpi_target} DPI target (internal failure threshold {s.dpi_error_threshold} DPI).")
    elif dpi < s.dpi_target * 0.98:
        res.add(WARNING, "LOW_RES",
                f"Effective resolution is {dpi:.0f} DPI at the placed size, below the "
                f"{s.dpi_target} DPI target.")


def _check_transparency(res, info: LoadInfo):
    if not info.had_alpha:
        return
    if info.transparent_fraction > 0:
        res.add(WARNING, "TRANSPARENCY",
                f"{_pct(info.transparent_fraction)} of pixels are transparent or semi-transparent "
                f"({_pct(info.fully_transparent_fraction)} fully transparent). They will be flattened onto "
                "the background colour - check the artwork looks as intended.")
    else:
        res.add(INFO, "ALPHA_OPAQUE", "Alpha channel present but fully opaque; it will be removed.")


def _ink_bbox(gray: np.ndarray, th: Thresholds):
    mask = gray < th.ink_level
    cols = np.flatnonzero(mask.sum(axis=0) >= th.min_ink_per_line)
    rows = np.flatnonzero(mask.sum(axis=1) >= th.min_ink_per_line)
    if cols.size == 0 or rows.size == 0:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def _check_ink_geometry(res, gray, placement, s, th):
    h, w = gray.shape
    bbox = _ink_bbox(gray, th)
    res.bbox_px = bbox
    if bbox is None:
        res.add(WARNING, "BLANK", "No artwork detected - the page looks blank. Is this intentional?")
        return
    x0, y0, x1, y1 = bbox
    m = {"left": x0, "right": w - x1, "top": y0, "bottom": h - y1}
    res.margins_px = m
    mp = {"left": x0 / w, "right": (w - x1) / w, "top": y0 / h, "bottom": (h - y1) / h}
    res.margins_pct = mp

    # artwork rectangle as laid out on the page (PDF points, origin bottom-left)
    sc = placement.scale_pt_per_px
    img = placement.image
    art = layout.Rect(
        img.x0 + x0 * sc, img.y0 + (h - y1) * sc, img.x0 + x1 * sc, img.y0 + (h - y0) * sc
    )
    dist = layout.edge_distances_in(art, placement.trim)
    res.art_margins_in = {k: round(v, 4) for k, v in dist.items()}

    big = [k for k, v in mp.items() if v > th.large_margin_frac]
    if big:
        res.add(WARNING, "LARGE_MARGIN",
                "Unusually large white margin on " + ", ".join(f"{k} ({_pct(mp[k])})" for k in big) + ".")
    tight = [k for k, v in mp.items() if 0 < m[k] and v < th.tight_margin_frac and m[k] > 2]
    if tight:
        res.add(WARNING, "TIGHT_MARGIN",
                "Extremely small margin inside the image on "
                + ", ".join(f"{k} ({m[k]} px)" for k in tight) + ".")
    dx = abs(m["left"] - m["right"]) / w
    dy = abs(m["top"] - m["bottom"]) / h
    off = []
    if dx > th.centered_tol_frac:
        off.append(f"horizontally by {dx * 100:.1f}% of the width")
    if dy > th.centered_tol_frac:
        off.append(f"vertically by {dy * 100:.1f}% of the height")
    if off:
        res.add(WARNING, "OFF_CENTER", "Illustration is not centred in the image: " + " and ".join(off) + ".")

    safe_area = placement.safe.width * placement.safe.height
    art_area = art.width * art.height
    if safe_area > 0 and art_area / safe_area < th.small_art_area_frac:
        res.add(WARNING, "ART_SMALL",
                f"Illustration fills only {_pct(art_area / safe_area)} of the printable area; "
                "it may be too small.")

    # artwork vs printable area on the page
    if not placement.safe.contains(art, tol=0.05):
        beyond_trim = [k for k, v in dist.items() if v < -0.0007]
        sev = ERROR if beyond_trim else WARNING
        res.add(sev, "ART_OUTSIDE_SAFE",
                "Illustration extends outside the configured printable area"
                + (f" and beyond the trim edge on {', '.join(beyond_trim)}" if beyond_trim else "") + ".")
    else:
        close = [k for k, v in dist.items() if v < s.kdp_min_margin_in - 1e-6]
        if close:
            res.add(WARNING, "ART_NEAR_TRIM",
                    f"Illustration is closer than {s.kdp_min_margin_in:g} in to the trim edge on "
                    + ", ".join(f"{k} ({dist[k]:.2f} in)" for k in close) + ".")


def _check_edges(res, gray, th):
    h, w = gray.shape
    band = max(2, round(0.001 * max(w, h)))
    mask = gray < th.ink_level
    edges = {
        "left": mask[:, :band].any(axis=1),
        "right": mask[:, -band:].any(axis=1),
        "top": mask[:band, :].any(axis=0),
        "bottom": mask[-band:, :].any(axis=0),
    }
    touching, solid = [], []
    for name, line in edges.items():
        n = int(line.sum())
        if n < th.min_ink_per_line:
            continue
        frac = n / line.size
        if frac > 0.5:
            solid.append(f"{name} ({_pct(frac)} of the edge)")
        else:
            touching.append(f"{name} ({n} px)")
    if solid:
        res.add(WARNING, "EDGE_BAND",
                "Dark pixels run along the image boundary on " + ", ".join(solid)
                + " - a border frame, scan edge or broken/suspicious edge. Inspect the page.")
    if touching:
        res.add(WARNING, "EDGE_TOUCH",
                "Artwork touches the image boundary on " + ", ".join(touching)
                + " - the illustration may be clipped.")


def _check_pixels(res, rgb, gray, record, s, th):
    h, w = gray.shape
    # --- unwanted colour ---------------------------------------------
    chroma = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2).astype(np.int16)
    colored = float((chroma > th.chroma_level).mean())
    res.colored_fraction = colored
    if s.interior == "bw" and colored > th.colored_frac_warn:
        res.add(WARNING, "COLOR_PIXELS",
                f"{_pct(colored)} of pixels are coloured in a black & white interior. "
                "Enable grayscale conversion or inspect the image.")

    # --- flat-region analysis ----------------------------------------
    bs = max(8, round(min(w, h) / 80))
    stats = _block_stats(gray, bs)
    if stats is None:
        return
    mean, std, bmin, bmax = stats
    total_blocks = mean.size
    flat = std < th.flat_std

    gray_flat = flat & (mean >= th.gray_lo) & (mean <= th.gray_hi)
    gp_min = max(4, int(np.ceil(th.gray_patch_area_frac * total_blocks)))
    patches = [c for c in _components(gray_flat) if c[0] >= gp_min]
    if patches:
        biggest = max(patches, key=lambda c: c[0])
        cells = np.array(biggest[2])
        avg = float(np.mean([mean[y, x] for y, x in biggest[2]]))
        area = biggest[0] / total_blocks
        touches_bottom = bool((cells[:, 0] == mean.shape[0] - 1).any())
        if biggest[1] and touches_bottom and 118 <= avg <= 138 and area > 0.03:
            res.add(WARNING, "CORRUPT_REGION",
                    f"A flat mid-gray region ({_pct(area)} of the page, gray {avg:.0f}) reaches the image edge - "
                    "typical of a truncated or corrupted file. Inspect the image.")
        else:
            res.add(WARNING, "GRAY_PATCH",
                    f"{len(patches)} flat gray region(s) detected (largest {_pct(area)} of the page, "
                    f"gray {avg:.0f}). Check it is intended shading and not a patch.")
    black_flat = flat & (mean < th.gray_lo)
    bp_min = max(8, int(np.ceil(th.black_patch_area_frac * total_blocks)))
    blacks = [c for c in _components(black_flat) if c[0] >= bp_min]
    if blacks:
        big = max(c[0] for c in blacks)
        res.add(WARNING, "BLACK_BLOCK",
                f"Large solid black region(s) detected (largest {_pct(big / total_blocks)} of the page). "
                "Fine for silhouettes, but verify it is not a rendering error.")

    pure_white = flat & (mean >= 253)
    off_white = flat & (mean > th.gray_hi) & (mean < 253)
    npure, noff = int(pure_white.sum()), int(off_white.sum())
    if noff + npure > 0:
        off_frac = noff / (noff + npure)
        if off_frac > 0.005:
            if npure >= 0.02 * total_blocks and noff >= 0.02 * total_blocks:
                res.add(WARNING, "WHITE_PATCH",
                        "Background mixes pure-white and off-white flat regions "
                        f"({_pct(off_frac)} off-white) - possible white patches or a tinted background.")
            else:
                level = float(mean[off_white].mean())
                res.add(WARNING, "BG_NOT_WHITE",
                        f"Background is not pure white ({_pct(off_frac)} of flat background area is "
                        f"off-white, average {level:.0f}). The optional near-white cleaning can fix this.")
    # noise in "empty" areas (compression artifacts, scanner noise)
    # blocks that are essentially pure white; antialiasing halos next to lines have a lower minimum
    empty = bmin >= 248
    if empty.sum() > 0:
        noisy = empty & ((bmax.astype(np.int16) - bmin.astype(np.int16)) >= 2)
        nf = float(noisy.sum() / empty.sum())
        if nf > th.noise_block_frac:
            res.add(WARNING, "BG_NOISE",
                    f"{_pct(nf)} of empty background blocks contain faint noise - possible compression "
                    "artifacts or scanner noise.")
    # JPEG 8x8 blocking
    if record.format.upper() in ("JPEG", "MPO") and w >= 64:
        d = np.abs(np.diff(gray.astype(np.int16), axis=1))
        edge_cols = d[:, 7::8]
        rest_sum = d.sum() - edge_cols.sum()
        rest_n = d.size - edge_cols.size
        other = rest_sum / max(rest_n, 1)
        if other > 0.05:
            ratio = float(edge_cols.mean() / other)
            res.stats["jpeg_block_ratio"] = round(ratio, 3)
            if ratio > th.jpeg_block_ratio:
                res.add(WARNING, "JPEG_BLOCKING",
                        f"Visible JPEG 8x8 block structure (ratio {ratio:.2f}) - lossy compression artifacts.")
        res.add(INFO, "LOSSY_SOURCE", "Source is a lossy JPEG; the PDF embeds it losslessly, "
                "but existing artifacts remain.")
    elif record.format.upper() == "WEBP":
        res.add(INFO, "LOSSY_SOURCE", "Source is WebP (may be lossy); existing artifacts remain.")


# ----------------------------------------------------------------------
# batch-level checks
# ----------------------------------------------------------------------
def apply_batch_checks(results: list[InspectionResult]) -> None:
    """Flag images whose pixel dimensions differ from the most common size."""
    sized = [r for r in results if r.width_px and not r.decode_failed]
    if len({(r.width_px, r.height_px) for r in sized}) <= 1:
        return
    common, _ = Counter((r.width_px, r.height_px) for r in sized).most_common(1)[0]
    for r in sized:
        if (r.width_px, r.height_px) != common and not any(f.code == "BATCH_DIM" for f in r.findings):
            r.add(WARNING, "BATCH_DIM",
                  f"Unexpected dimensions {r.width_px} x {r.height_px}: most pages are "
                  f"{common[0]} x {common[1]} px.")
            r.finalize()


def inspect_all(records, settings, progress=None, cancel=None) -> list[InspectionResult]:
    results = []
    for i, rec in enumerate(records, 1):
        if cancel is not None and cancel.is_set():
            break
        if progress:
            progress(i, len(records), rec.filename)
        results.append(inspect_record(rec, i, settings))
    apply_batch_checks(results)
    return results
