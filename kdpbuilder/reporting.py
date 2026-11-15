"""CSV / JSON / log output."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path

import pikepdf

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

from . import APP_NAME, KDP_DISCLAIMER, __version__
from .inspector import ERROR, GREEN, INFO, RED, WARNING, YELLOW, InspectionResult
from .processor import file_sha256
from .settings import BookSettings
from .validator import ValidationReport

VALIDATION_COLUMNS = [
    "pdf_page", "filename", "original_width_px", "original_height_px", "effective_dpi",
    "pdf_page_width_pt", "pdf_page_height_pt",
    "image_x0_pt", "image_y0_pt", "image_x1_pt", "image_y1_pt", "image_width_pt", "image_height_pt",
    "margin_left_in", "margin_right_in", "margin_top_in", "margin_bottom_in",
    "artwork_margin_left_in", "artwork_margin_right_in", "artwork_margin_top_in", "artwork_margin_bottom_in",
    "transparency_status", "boundary_validation", "image_quality_status", "processing_status",
    "status", "errors", "warnings", "notes",
]
FAILED_COLUMNS = ["pdf_page", "filename", "status", "processing_status", "errors", "warnings"]

SEV_ORDER = {GREEN: 0, YELLOW: 1, RED: 2}


def worst(*statuses: str) -> str:
    return max(statuses, key=lambda s: SEV_ORDER.get(s, 0))


def _join(findings, severity) -> str:
    return " | ".join(f"[{f.code}] {f.message}" for f in findings if f.severity == severity)


def build_rows(entries, validation: ValidationReport | None, skipped: list[dict]) -> list[dict]:
    """Merge pre-flight inspection and PDF validation into one row per page
    (plus one row for every skipped image - nothing is silently dropped)."""
    rows: list[dict] = []
    vmap = {p.pdf_page: p for p in (validation.pages if validation else [])}
    for e in entries:
        pv = vmap.get(e.page_number)
        insp: InspectionResult | None = e.inspection
        findings = list(insp.findings) if insp else []
        quality = insp.status if insp else GREEN
        if pv:
            findings += pv.findings
        seen, uniq = set(), []
        for f in findings:  # the inspector and validator can both raise e.g. LOW_RES
            if (f.severity, f.code) not in seen:
                seen.add((f.severity, f.code))
                uniq.append(f)
        findings = uniq
        status = worst(quality, pv.status if pv else YELLOW)
        art = (insp.art_margins_in if insp and insp.art_margins_in else {}) or {}
        row = {
            "pdf_page": e.page_number,
            "filename": e.record.filename,
            "original_width_px": e.record.oriented_width or e.width_px,
            "original_height_px": e.record.oriented_height or e.height_px,
            "effective_dpi": pv.effective_dpi if pv else (insp.effective_dpi if insp else ""),
            "pdf_page_width_pt": pv.page_width_pt if pv else "",
            "pdf_page_height_pt": pv.page_height_pt if pv else "",
            "image_x0_pt": pv.image_x0_pt if pv else "",
            "image_y0_pt": pv.image_y0_pt if pv else "",
            "image_x1_pt": pv.image_x1_pt if pv else "",
            "image_y1_pt": pv.image_y1_pt if pv else "",
            "image_width_pt": pv.image_width_pt if pv else "",
            "image_height_pt": pv.image_height_pt if pv else "",
            "margin_left_in": pv.margin_left_in if pv else "",
            "margin_right_in": pv.margin_right_in if pv else "",
            "margin_top_in": pv.margin_top_in if pv else "",
            "margin_bottom_in": pv.margin_bottom_in if pv else "",
            "artwork_margin_left_in": art.get("left", ""),
            "artwork_margin_right_in": art.get("right", ""),
            "artwork_margin_top_in": art.get("top", ""),
            "artwork_margin_bottom_in": art.get("bottom", ""),
            "transparency_status": pv.transparency_status if pv else "UNKNOWN",
            "boundary_validation": pv.boundary_status if pv else "UNKNOWN",
            "image_quality_status": quality,
            "processing_status": "OK" if pv else "NOT VALIDATED",
            "status": status,
            "errors": _join(findings, ERROR),
            "warnings": _join(findings, WARNING),
            "notes": _join(findings, INFO),
        }
        rows.append(row)
    for sk in skipped:
        rows.append({c: "" for c in VALIDATION_COLUMNS} | {
            "pdf_page": "(skipped)",
            "filename": sk["filename"],
            "transparency_status": "UNKNOWN",
            "boundary_validation": "UNKNOWN",
            "image_quality_status": RED,
            "processing_status": "SKIPPED",
            "status": RED,
            "errors": sk["reason"],
        })
    if validation:
        for f in validation.doc_findings:
            rows.append({c: "" for c in VALIDATION_COLUMNS} | {
                "pdf_page": "(document)",
                "filename": Path(validation.pdf_path).name,
                "processing_status": "DOCUMENT",
                "status": RED if f.severity == ERROR else YELLOW if f.severity == WARNING else GREEN,
                "errors" if f.severity == ERROR else "warnings" if f.severity == WARNING else "notes":
                    f"[{f.code}] {f.message}",
            })
    return rows


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """Neutralise spreadsheet formula injection (CSV injection).

    File names and messages come from untrusted input; a value such as ``=HYPERLINK(...)``
    would otherwise execute when the report is opened in Excel or LibreOffice. Plain
    numbers (including negative margins) are left untouched."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        try:
            float(value)
            return value
        except ValueError:
            return "'" + value
    return value


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:  # BOM: opens cleanly in Excel
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: csv_safe(v) for k, v in r.items()})


def write_validation_csv(path: Path, rows: list[dict]) -> None:
    write_csv(path, rows, VALIDATION_COLUMNS)


def write_failed_pages_csv(path: Path, rows: list[dict]) -> None:
    write_csv(path, [r for r in rows if r["status"] == RED], FAILED_COLUMNS)


def write_pdf_metadata(path: Path, pdf_path: Path, settings: BookSettings,
                       validation: ValidationReport | None, rows: list[dict]) -> dict:
    meta: dict = {
        "generator": f"{APP_NAME} {__version__}",
        "created": datetime.now().isoformat(timespec="seconds"),
        "disclaimer": KDP_DISCLAIMER,
        "settings": settings.to_dict(),
        "pdf": {},
    }
    if pdf_path.exists():
        info: dict = {
            "file": pdf_path.name,
            "size_bytes": pdf_path.stat().st_size,
            "sha256": file_sha256(pdf_path),
        }
        try:
            with pikepdf.open(pdf_path) as pk:
                info["page_count"] = len(pk.pages)
                info["pdf_version"] = str(pk.pdf_version)
                info["encrypted"] = pk.is_encrypted
                info["docinfo"] = {str(k): str(v) for k, v in pk.docinfo.items()}
                info["pages"] = [
                    {
                        "page": i + 1,
                        "mediabox": [float(x) for x in p.mediabox],
                        "cropbox": [float(x) for x in p.cropbox],
                        "trimbox": [float(x) for x in p.trimbox],
                        "bleedbox": [float(x) for x in p.bleedbox],
                    }
                    for i, p in enumerate(pk.pages)
                ]
            with fitz.open(str(pdf_path)) as doc:
                info["fonts_embedded_or_referenced"] = sorted(
                    {f[3] for pg in doc for f in pg.get_fonts()}
                )
        except Exception as exc:
            info["inspection_error"] = str(exc)
        meta["pdf"] = info
    counts = {GREEN: 0, YELLOW: 0, RED: 0}
    for r in rows:
        if r["status"] in counts:
            counts[r["status"]] += 1
    meta["summary"] = {
        "rows": len(rows),
        "green": counts[GREEN], "yellow": counts[YELLOW], "red": counts[RED],
        "internal_validation_passed": bool(validation and validation.passed),
        "overall_status": validation.overall_status if validation else "NOT VALIDATED",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def make_logger(log_path: Path, name: str = "kdpbuilder", append: bool = False,
                extra_handler: logging.Handler | None = None) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"{name}.{log_path.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    fh = logging.FileHandler(log_path, mode="a" if append else "w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)
    if extra_handler is not None:
        logger.addHandler(extra_handler)
    return logger


def close_logger(logger: logging.Logger) -> None:
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
