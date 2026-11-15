# Amazon-KDP-Image-to-Pdf
KDP Builder is a lightweight desktop app that converts coloring book images into Amazon KDP-ready interior PDFs. It offers bulk image import, automatic sorting, image inspection, precise page formatting, and PDF validation. Advantages: Saves time, simplifies publishing, improves print quality, and helps catch formatting issues before upload.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

> Not an Amazon tool. Every check is an internal check. None of it is an Amazon KDP Print Previewer result, and the app never claims otherwise. Always review your upload in KDP's own Print Previewer. This project is not affiliated with or endorsed by Amazon.

## Why

The usual "images to PDF" route often produces the classic KDP problems: artwork touching the page boundary, wrong margins, full-page images that ignore the gutter, low effective resolution, transparency, blank or gray patches, and inconsistent page sizes. KDP Builder is built around preventing and diagnosing exactly those.

## Features

 Bulk import — files, folders (optionally with subfolders), ZIP archives and drag & drop; PNG, JPG/JPEG, WebP, TIFF, BMP
 Natural sorting (1, 2, 9, 10, 11) and manual reordering; every PDF page shows its exact source filename
 Automatic detection of pixel size, aspect ratio, format, color mode, transparency, DPI metadata and EXIF orientation
 Pre-flight inspection — illustration bounding box, margins and centering, artwork touching or clipped at the image edge, effective DPI, transparency, unwanted color, gray/black/white patches, background noise, JPEG blocking. White pixels and gray antialiasing are not treated as errors; nothing is erased or changed
 KDP layout engine — exact trim size (default 8.5 x 11 in = 612 x 792 pt), separate inside / outside / top / bottom margins with the gutter alternating per page, optional bleed, default fit inside printable area:
  scale = min(printable_width / image_width, printable_height / image_height), centered, aspect ratio always preserved (never stretched, cropped or auto-zoomed)
 Clean PDF — one image per page, lossless Flate streams (no JPEG recompression), transparency flattened onto pure white, identical MediaBox/CropBox on every page, no text, borders, crop marks, page numbers or watermarks
 Independent post-generation validation — re-reads the PDF with pikepdf + PyMuPDF: page count, boxes, size, orientation, image object coordinates and margins, safe-area containment, distortion, effective DPI, transparency masks, layers, blank pages, and embedded pixels compared with the processed image (catches resampling and wrong page order), plus a rendered comparison of every page with its source
 GREEN / YELLOW / RED status per page with plain-language messages; the PDF is never called valid while any page is RED
 Safe batch processing — originals are never modified, corrupted files are skipped and reported (not silently dropped), cancellable, resumable, full processing log
 Optional image edits, all OFF by default — grayscale, near-white cleaning, black & white threshold, contrast
 Reports — CSV validation report, failed pages CSV, processing log, PDF metadata JSON, rendered page previews
 Command-line mode using the same engine

## Install and run (Windows)

1. Install Python 3.11 or newer from <https://www.python.org/downloads/> and tick Add python.exe to PATH.
2. Download or clone this repository.
3. Double-click start.bat. On the first run it creates its own virtual environment (.venv), installs the dependencies and starts the app. Later runs start immediately.

Manual alternative:


python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py


## Usage

| Screen | What you do |
|---|---|
| Dashboard | Totals (imported / valid / warning / failed / PDF pages), progress, activity log, Inspect all images |
| Import Images | Add files, folders or ZIPs, or drop them on the window; reorder pages; natural sort |
| Image Inspection | Preview with printable-area overlay (green), illustration box (red), placed image (blue); margins, zoom, previous / next |
| Page Settings | Trim size, DPI, margins, bleed, binding, placement, background, color mode, optional edits; save / load as JSON |
| PDF Generator | Output folder, Generate PDF, Cancel, skip-failed and resume options, live progress |
| PDF Validation | Page-by-page results, error text, preview of any page, export report |
| Export | Open the output folder, save the PDF, copy everything |

Command line:


python main.py --cli path\to\images -o output
python main.py --cli pages.zip -o output --margins 0.75 0.5 0.5 0.5 --dpi 300
python main.py --cli --help


## Output


output/
  manuscript.pdf
  previews/               page_0001.png ... (rendered from the finished PDF)
  processed_images/       flattened lossless copies embedded in the PDF
  reports/
    validation_report.csv one row per page, plus skipped images
    failed_pages.csv      RED rows only
    processing_log.txt
    pdf_metadata.json


## Defaults

Paperback, 8.5 x 11 in, black & white, white paper, no bleed, 300 DPI target (2550 x 3300 px source), 0.5 in margins, pure white #FFFFFF background, portrait, fit-inside placement. Everything is configurable.

## Project layout

main.py                  entry point (GUI, or --cli)
kdpbuilder/
  settings.py            book / layout / processing settings (strictly validated)
  layout.py              exact page geometry and image placement
  importer.py            discovery, natural sort, hardened ZIP extraction, metadata
  processor.py           orientation, transparency flattening, optional edits
  inspector.py           pre-PDF image inspection
  pdf_generator.py       ReportLab PDF writer
  validator.py           independent post-generation validation
  reporting.py           CSV / JSON / log output
  pipeline.py            resumable, cancellable batch run
  controller.py          GUI-independent application state
  gui/                   CustomTkinter interface


## Notes and limits

 Effective DPI is calculated from the final placed size, not from file metadata.
 CMYK sources are converted to RGB without an ICC profile.
 The 0.25 in "near trim edge" warning and the 150 DPI failure threshold are configurable internal thresholds, not KDP rules. Check KDP's current requirements for your trim size and page count.
 Inspection thresholds are heuristics: YELLOW means "look at this page", not "wrong".

## License

Released under the [MIT License](LICENSE) — free to use, modify and distribute, provided the copyright notice is kept.

### Third-party software

KDP Builder depends on these packages, installed separately with pip and governed by their own licenses:
customtkinter (MIT), tkinterdnd2 (MIT), Pillow (HPND), NumPy (BSD-3-Clause), ReportLab (BSD-3-Clause),
pikepdf (MPL-2.0) and PyMuPDF (AGPL-3.0 or a commercial license from Artifex).
If you redistribute a bundle that includes these libraries (for example a packaged .exe), you must comply with
each license; in particular, distributing PyMuPDF inside a bundled application brings the AGPL's obligations
(or requires an Artifex commercial license). This repository itself only lists the dependencies.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions are welcome.
