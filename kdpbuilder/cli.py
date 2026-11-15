"""Headless command line interface (same engine as the GUI)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .controller import Controller
from .pipeline import Pipeline, PipelineError
from .settings import BookSettings


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kdpbuilder", description="Build and validate a KDP interior PDF.")
    p.add_argument("inputs", nargs="+", help="image files, folders or ZIP archives")
    p.add_argument("-o", "--output", default="output", help="output folder (default: ./output)")
    p.add_argument("--settings", help="settings JSON file saved from the GUI")
    p.add_argument("--trim", nargs=2, type=float, metavar=("W", "H"), help="trim size in inches")
    p.add_argument("--dpi", type=int)
    p.add_argument("--margins", nargs=4, type=float, metavar=("INSIDE", "OUTSIDE", "TOP", "BOTTOM"))
    p.add_argument("--bleed", action="store_true")
    p.add_argument("--placement", choices=["fit", "center", "custom"])
    p.add_argument("--grayscale", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--no-skip-failed", action="store_true", help="stop at the first failed image")
    return p


def run_cli(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        s = BookSettings.load(args.settings) if args.settings else BookSettings()
    except (OSError, ValueError) as exc:
        print(f"Cannot load settings: {exc}", file=sys.stderr)
        return 2
    if args.trim:
        s.trim_width_in, s.trim_height_in = args.trim
    if args.dpi:
        s.dpi_target = args.dpi
    if args.margins:
        s.inside_margin_in, s.outside_margin_in, s.top_margin_in, s.bottom_margin_in = args.margins
    if args.bleed:
        s.bleed = True
    if args.placement:
        s.placement = args.placement
    if args.grayscale:
        s.color_mode = "grayscale"
    out = Path(args.output)
    ctl = Controller(out)
    ctl.settings = s
    added, rejected = ctl.add_items(args.inputs)
    for name, why in rejected:
        print(f"not added: {name}: {why}", file=sys.stderr)
    if not ctl.records:
        print("No supported images found.", file=sys.stderr)
        return 2

    def progress(stage, cur, total, name):
        print(f"\r[{stage}] {cur}/{total} {name[:50]:<50}", end="", flush=True)

    try:
        res = Pipeline(s, out, progress=progress).run(
            ctl.records, skip_failed=not args.no_skip_failed, resume=args.resume)
    except PipelineError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    c = res.counts
    print(f"\n{res.message}\nGREEN {c['GREEN']}  YELLOW {c['YELLOW']}  RED {c['RED']}\nOutput: {out.resolve()}")
    print("Note: these are internal checks, not an Amazon KDP Print Previewer result.")
    return 0 if res.overall_status != "RED" else 1
