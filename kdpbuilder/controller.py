"""GUI-independent application state and background jobs.

The GUI only calls this class and polls `events` (a thread-safe queue), so the
whole workflow can be exercised without a display."""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path

from . import layout, reporting
from .importer import ImageRecord, import_images, natural_key, read_metadata
from .inspector import (
    GREEN, YELLOW, InspectionResult, apply_batch_checks, inspect_record,
)
from .pipeline import Pipeline, PipelineError, RunResult
from .settings import BookSettings
from .validator import validate_pdf


class _QueueLogHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__(logging.INFO)
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        self.q.put(("log", record.levelname, record.getMessage()))


class Controller:
    def __init__(self, output_dir: str | Path | None = None):
        self.settings = BookSettings()
        self.records: list[ImageRecord] = []
        self.inspections: dict[str, InspectionResult] = {}  # key: path|page|layout_sig
        self.output_dir = Path(output_dir) if output_dir else Path.home() / "KDP_Builder_output"
        self.last_run: RunResult | None = None
        self.events: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self._worker: threading.Thread | None = None
        self.busy = False
        self.progress_state = {"stage": "idle", "current": 0, "total": 0, "filename": ""}

    # ------------------------------------------------------------------
    # import / ordering
    # ------------------------------------------------------------------
    @property
    def zip_dir(self) -> Path:
        return self.output_dir / "_extracted_zips"

    def add_items(self, items, recursive: bool = False) -> tuple[int, list[tuple[str, str]]]:
        """Add files, folders or ZIPs. New items are naturally sorted among themselves and
        appended after the existing manual order. Returns (added_count, rejected)."""
        new, rejected = import_images(items, zip_dest=self.zip_dir, recursive=recursive)
        have = {str(Path(r.path).resolve()) for r in self.records}
        added = 0
        for r in new:
            if str(Path(r.path).resolve()) in have:
                continue
            self.records.append(r)
            added += 1
        if added:
            self.inspections.clear()
        return added, rejected

    def clear(self) -> None:
        self.records.clear()
        self.inspections.clear()
        self.last_run = None

    def remove(self, indices: list[int]) -> None:
        for i in sorted(set(indices), reverse=True):
            if 0 <= i < len(self.records):
                del self.records[i]
        self.inspections.clear()

    def move(self, indices: list[int], delta: int) -> list[int]:
        """Move the selected rows up (delta=-1) or down (+1). Returns the new indices."""
        n = len(self.records)
        idx = sorted({i for i in indices if 0 <= i < n})
        if not idx or delta not in (-1, 1):
            return idx
        sel = set(idx)
        for i in (idx if delta < 0 else reversed(idx)):
            j = i + delta
            if 0 <= j < n and j not in sel:
                self.records[i], self.records[j] = self.records[j], self.records[i]
                sel.remove(i)
                sel.add(j)
        self.inspections.clear()
        return sorted(sel)

    def natural_sort(self) -> None:
        self.records.sort(key=lambda r: natural_key(r.path))
        self.inspections.clear()

    def refresh_record(self, index: int) -> None:
        r = self.records[index]
        self.records[index] = read_metadata(r.path, origin=r.origin)

    # ------------------------------------------------------------------
    # inspection
    # ------------------------------------------------------------------
    def key_for(self, index: int) -> str:
        r = self.records[index]
        return f"{Path(r.path).resolve()}|{index + 1}|{self.settings.layout_signature()}"

    def inspection_for(self, index: int, compute: bool = True) -> InspectionResult | None:
        key = self.key_for(index)
        res = self.inspections.get(key)
        if res is None and compute:
            res = inspect_record(self.records[index], index + 1, self.settings)
            self.inspections[key] = res
        return res

    def inspect_all(self, progress=None, cancel: threading.Event | None = None) -> list[InspectionResult]:
        results = []
        for i, rec in enumerate(self.records):
            if cancel is not None and cancel.is_set():
                break
            if progress:
                progress("inspect", i + 1, len(self.records), rec.filename)
            res = self.inspection_for(i)
            results.append(res)
        apply_batch_checks(results)
        return results

    def summary(self) -> dict:
        """Counts for the dashboard (inspection results if available)."""
        valid = warn = fail = 0
        for i, rec in enumerate(self.records):
            if rec.error:
                fail += 1
                continue
            res = self.inspection_for(i, compute=False)
            if res is None:
                continue
            if res.status == GREEN:
                valid += 1
            elif res.status == YELLOW:
                warn += 1
            else:
                fail += 1
        run = self.last_run
        pages = len(run.entries) if run and run.pdf_path else 0
        return {
            "total": len(self.records), "valid": valid, "warning": warn, "failed": fail,
            "pdf_pages": pages,
            "inspected": sum(1 for i in range(len(self.records)) if self.inspection_for(i, compute=False)),
        }

    def page_geometry(self, index: int):
        """Layout for the Inspection view (None if the image cannot be read)."""
        r = self.records[index]
        if r.error:
            return None
        return layout.compute_placement(r.oriented_width, r.oriented_height, index + 1, self.settings)

    # ------------------------------------------------------------------
    # background jobs
    # ------------------------------------------------------------------
    def _start(self, target, *args) -> bool:
        if self.busy:
            return False
        self.busy = True
        self.cancel_event.clear()
        self._worker = threading.Thread(target=self._guard, args=(target, *args), daemon=True)
        self._worker.start()
        return True

    def _guard(self, target, *args) -> None:
        try:
            target(*args)
        except PipelineError as exc:
            self.events.put(("error", str(exc)))
        except Exception as exc:  # never let a worker die silently
            self.events.put(("error", f"Unexpected error: {exc}"))
        finally:
            self.busy = False
            self.events.put(("idle",))

    def _progress(self, stage: str, cur: int, total: int, name: str) -> None:
        self.progress_state = {"stage": stage, "current": cur, "total": total, "filename": name}
        self.events.put(("progress", stage, cur, total, name))

    def start_inspection(self) -> bool:
        if not self.records:
            return False

        def job():
            self.inspect_all(progress=self._progress, cancel=self.cancel_event)
            self.events.put(("inspection_done",))

        return self._start(job)

    def start_generation(self, resume: bool = False, skip_failed: bool | None = None) -> bool:
        if not self.records:
            return False

        def job():
            pipe = Pipeline(
                self.settings, self.output_dir, progress=self._progress, cancel=self.cancel_event,
                log_handler=_QueueLogHandler(self.events), precomputed=dict(self.inspections))
            self.last_run = pipe.run(list(self.records), skip_failed=skip_failed, resume=resume)
            self.events.put(("run_done", self.last_run))

        return self._start(job)

    def start_revalidation(self) -> bool:
        """Re-open the finished PDF and validate it again (also refreshes the reports)."""
        run = self.last_run
        if not run or not run.pdf_path or not Path(run.pdf_path).exists():
            return False

        def job():
            run.validation = validate_pdf(
                run.pdf_path, run.entries, self.settings, previews_dir=run.output_dir / "previews",
                progress=self._progress, cancel=self.cancel_event)
            run.rows = reporting.build_rows(run.entries, run.validation, run.skipped)
            rep = run.output_dir / "reports"
            reporting.write_validation_csv(rep / "validation_report.csv", run.rows)
            reporting.write_failed_pages_csv(rep / "failed_pages.csv", run.rows)
            reporting.write_pdf_metadata(rep / "pdf_metadata.json", run.pdf_path, self.settings,
                                         run.validation, run.rows)
            self.events.put(("run_done", run))

        return self._start(job)

    def cancel(self) -> None:
        self.cancel_event.set()

    def wait(self, timeout: float | None = None) -> None:
        if self._worker is not None:
            self._worker.join(timeout)
