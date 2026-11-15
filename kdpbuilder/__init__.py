KDP Builder - Amazon KDP professional manuscript PDF generator.

Modules
-------
settings       book / layout / processing settings
layout         exact KDP page geometry (page size, margins, image placement)
importer       image discovery, natural sorting, ZIP extraction, metadata
processor      image normalisation (flatten transparency, optional edits)
inspector      pre-PDF image quality and boundary inspection
pdf_generator  ReportLab PDF generation
validator      independent post-generation PDF validation (PyMuPDF + pikepdf)
reporting      CSV / JSON / log output
pipeline       end-to-end batch run (resumable, cancellable)
controller     GUI-independent application state
gui            CustomTkinter user interface


__version__ = "1.0.0"
APP_NAME = "KDP Builder"
KDP_DISCLAIMER = (
    "Internal checks only. This is NOT an Amazon KDP Print Previewer "
    "result - always run KDP's own Print Previewer before publishing."
)
