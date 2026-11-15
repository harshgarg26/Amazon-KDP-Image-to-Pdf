"""End-to-end batch run: inspect -> process -> PDF -> validate -> report.

Source images are only ever read. Failed images are reported (never silently
dropped); the run is resumable and cancellable."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import reporting
from .importer import ImageRecord
from .inspector import GREEN, RED, YELLOW, InspectionResult, apply_batch_checks, inspect_record
from .pdf_generator import GenerationCancelled, PageEntry, generate_pdf
from .processor import process_one
from .settings import BookSettings
from .validator import ValidationReport, validate_pdf

STATE_FILE = ".kdpbuilder_state.json"
ProgressFn = Callable[[str, int, int, str], None]  # (stage, current, total, filename)


class PipelineError(Exception):
    pass


@dataclass
class RunResult:
    output_dir: Path
    pdf_path: Path | None = None
    entries: list[PageEntry] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    validation: ValidationReport | None = None
    cancelled: bool = False
    reused_count: int = 0
    message: str = ""

    @property
    def overall_status(self) -> str:
        if self.validation is None:
            return RED
        status = self.validation.overall_status
        if self.skipped and status != RED:
            status = RED  # a skipped image is a failed page that needs correcting
        return status

    @property
    def counts(self) -> dict:
        c = {GREEN: 0, YELLOW: 0, RED: 0}
        for r in self.rows:
            if r.get("pdf_page") in ("(document)",):
                continue
            c[r["status"]] = c.get(r["status"], 0) + 1
        return c


class Pipeline:
    def __init__(
        self,
        settings: BookSettings,
        output_dir: str | Path,
        progress: ProgressFn | None = None,
        cancel: threading.Event | None = None,
        log_handler: logging.Handler | None = None,
        precomputed: dict[str, InspectionResult] | None = None,
    ):
        self.s = settings
        self.out = Path(output_dir)
        self.progress = progress or (lambda *a: None)
        self.cancel = cancel or threading.Event()
        self.log_handler = log_handler
        self.precomputed = precomputed or {}

    # --- folders ------------------------------------------------------
    @property
    def pdf_path(self) -> Path:
        return self.out / "manuscript.pdf"

    @property
    def processed_dir(self) -> Path:
        return self.out / "processed_images"

    @property
    def previews_dir(self) -> Path:
        return self.out / "previews"

    @property
    def reports_dir(self) -> Path:
        return self.out / "reports"

    # --- state (resume support) ---------------------------------------
    def _load_state(self) -> dict:
        p = self.out / STATE_FILE
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("version") == 1:
                return data
        except (OSError, ValueError):
            pass
        return {"version": 1, "items": {}}

    def _save_state(self, state: dict) -> None:
        tmp = self.out / (STATE_FILE + ".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(self.out / STATE_FILE)

    # --- run ------------------------------------------------------------
    def run(self, records: list[ImageRecord], skip_failed: bool | None = None,
            resume: bool = False) -> RunResult:
        s = self.s
        skip_failed = s.skip_failed if skip_failed is None else skip_failed
        problems = s.validate()
        if problems:
            raise PipelineError("Invalid settings: " + " ".join(problems))
        if not records:
            raise PipelineError("No images were imported.")
        out_root = self.out.resolve()
        for r in records:
            rp = Path(r.path).resolve()
            if any(p in (self.processed_dir.resolve(), self.previews_dir.resolve(), self.reports_dir.resolve())
                   for p in rp.parents):
                raise PipelineError(
                    f"'{r.filename}' is inside the output folder ({out_root}). Choose an output folder "
                    "that does not contain source images so originals can never be overwritten.")
        for d in (self.out, self.processed_dir, self.previews_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)

        log = reporting.make_logger(self.reports_dir / "processing_log.txt", append=resume,
                                    extra_handler=self.log_handler)
        result = RunResult(output_dir=self.out)
        try:
            return self._run(records, skip_failed, resume, log, result)
        finally:
            reporting.close_logger(log)

    def _run(self, records, skip_failed, resume, log, result: RunResult) -> RunResult:
        s = self.s
        log.info("=== KDP Builder run started: %d image(s), resume=%s, skip_failed=%s ===",
                 len(records), resume, skip_failed)
        log.info("Page %.3f x %.3f in, %d DPI target, placement=%s, margins in/out/top/bottom = "
                 "%g/%g/%g/%g in, bleed=%s", s.page_width_in, s.page_height_in, s.dpi_target,
                 s.placement, s.inside_margin_in, s.outside_margin_in, s.top_margin_in,
                 s.bottom_margin_in, s.bleed)
        if s.any_modification_enabled:
            log.info("Optional image modifications ENABLED: color_mode=%s near_white=%s bw_threshold=%s "
                     "contrast=%s background=%s", s.color_mode, s.near_white_clean, s.bw_threshold,
                     s.contrast_adjust and s.contrast_factor, s.background_color)
        state = self._load_state() if resume else {"version": 1, "items": {}}
        proc_sig, layout_sig = s.processing_signature(), s.layout_signature()
        total = len(records)
        inspections: list[InspectionResult] = []

        for idx, rec in enumerate(records, 1):
            if self.cancel.is_set():
                result.cancelled = True
                log.warning("Cancelled by user after %d of %d images.", idx - 1, total)
                break
            self.progress("process", idx, total, rec.filename)
            page_no = len(result.entries) + 1
            key = str(Path(rec.path).resolve())
            cached = state["items"].get(key)
            fresh = bool(
                resume and cached and cached.get("size") == rec.file_size
                and cached.get("mtime") == rec.mtime and cached.get("proc_sig") == proc_sig
                and (self.processed_dir / cached.get("processed", "?")).exists()
            )
            try:
                if rec.error:
                    raise ValueError(rec.error)
                insp_key = f"{key}|{page_no}|{layout_sig}"
                if fresh and cached.get("insp_key") == insp_key and cached.get("inspection"):
                    insp = InspectionResult.from_dict(cached["inspection"])
                elif insp_key in self.precomputed:
                    insp = self.precomputed[insp_key]
                else:
                    insp = inspect_record(rec, page_no, s)
                if insp.decode_failed:
                    raise ValueError(insp.errors[0].message if insp.errors else "Image could not be decoded")
                if fresh:
                    processed = self.processed_dir / cached["processed"]
                    size = tuple(cached["size_px"])
                    result.reused_count += 1
                    log.info("[%d/%d] %s - reused processed image (resume)", idx, total, rec.filename)
                else:
                    processed, size, info = process_one(rec.path, s, self.processed_dir)
                    log.info("[%d/%d] %s -> %s (%dx%d px)%s", idx, total, rec.filename, processed.name,
                             size[0], size[1], "; " + "; ".join(info.notes) if info.notes else "")
                state["items"][key] = {
                    "size": rec.file_size, "mtime": rec.mtime, "proc_sig": proc_sig,
                    "processed": processed.name, "size_px": list(size),
                    "insp_key": insp_key, "inspection": insp.to_dict(),
                }
                self._save_state(state)
            except Exception as exc:
                reason = str(exc)
                log.error("[%d/%d] %s FAILED: %s", idx, total, rec.filename, reason)
                result.skipped.append({"filename": rec.filename, "path": rec.path, "reason": reason})
                if not skip_failed:
                    result.message = (f"Stopped at '{rec.filename}': {reason}. "
                                      "Fix or remove the image, or enable 'skip failed images'.")
                    self._finish_reports(result, log)
                    raise PipelineError(result.message)
                continue
            inspections.append(insp)
            result.entries.append(PageEntry(page_no, rec, str(processed), size[0], size[1], insp))

        apply_batch_checks(inspections)

        if result.cancelled:
            result.message = "Cancelled before the PDF was generated."
            self._finish_reports(result, log)
            return result
        if not result.entries:
            result.message = "No image could be processed."
            self._finish_reports(result, log)
            raise PipelineError(result.message)

        # --- PDF ---
        try:
            generate_pdf(result.entries, s, self.pdf_path,
                         progress=lambda i, n, f: self.progress("pdf", i, n, f), cancel=self.cancel)
        except GenerationCancelled:
            result.cancelled = True
            result.message = "Cancelled during PDF generation."
            log.warning(result.message)
            self._finish_reports(result, log)
            return result
        result.pdf_path = self.pdf_path
        log.info("PDF written: %s (%d pages)", self.pdf_path, len(result.entries))

        # --- independent validation ---
        result.validation = validate_pdf(
            self.pdf_path, result.entries, s, previews_dir=self.previews_dir,
            progress=lambda i, n, f: self.progress("validate", i, n, f), cancel=self.cancel)
        if self.cancel.is_set():
            result.cancelled = True
        self._finish_reports(result, log)
        v = result.validation
        log.info("Validation (internal checks, NOT a KDP Print Previewer result): %s", v.overall_status)
        result.message = (
            f"{len(result.entries)} page(s) written. Internal validation: {v.overall_status}"
            + (f"; {len(result.skipped)} image(s) skipped." if result.skipped else ".")
        )
        return result

    def _finish_reports(self, result: RunResult, log) -> None:
        result.rows = reporting.build_rows(result.entries, result.validation, result.skipped)
        reporting.write_validation_csv(self.reports_dir / "validation_report.csv", result.rows)
        reporting.write_failed_pages_csv(self.reports_dir / "failed_pages.csv", result.rows)
        reporting.write_pdf_metadata(self.reports_dir / "pdf_metadata.json",
                                     result.pdf_path or (self.out / "__no_pdf_generated__"), self.s,
                                     result.validation, result.rows)
        c = result.counts
        log.info("Reports written to %s (green=%d yellow=%d red=%d)", self.reports_dir,
                 c[GREEN], c[YELLOW], c[RED])
