"""Image normalisation: orientation, mode conversion, transparency flattening and
the OPTIONAL (default-off) modifications. Source files are never modified."""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from .settings import BookSettings

warnings.simplefilter("error", Image.DecompressionBombWarning)
Image.MAX_IMAGE_PIXELS = 200_000_000  # ~200 MP; above 2x this Pillow raises


@dataclass
class LoadInfo:
    original_mode: str = ""
    had_alpha: bool = False
    transparent_fraction: float = 0.0  # alpha == 0 ... < 255 (any transparency)
    fully_transparent_fraction: float = 0.0  # alpha == 0
    exif_orientation_applied: bool = False
    notes: list[str] = field(default_factory=list)


def _to_uint8(arr: np.ndarray) -> np.ndarray:
    a = arr.astype(np.float64)
    top = 65535.0 if a.max() > 255 else 255.0
    return np.clip(np.rint(a / top * 255.0), 0, 255).astype(np.uint8)


def load_flattened(
    path: str | Path, settings: BookSettings, apply_modifications: bool = True
) -> tuple[Image.Image, LoadInfo]:
    """Decode an image fully, apply EXIF orientation, flatten any transparency onto
    the background colour and return an RGB (or L) image with no alpha channel.

    Raises on corrupted / truncated files."""
    info = LoadInfo()
    with Image.open(path) as src:
        src.load()  # raises on truncated/corrupted data
        im = src.copy()
        src_info = dict(src.info)
    info.original_mode = im.mode

    orient = 1
    try:
        orient = int(im.getexif().get(0x0112, 1) or 1)
    except Exception:
        pass
    if orient != 1:
        try:
            im = ImageOps.exif_transpose(im)
            info.exif_orientation_applied = True
            info.notes.append(f"EXIF orientation {orient} applied")
        except Exception:
            info.notes.append("EXIF orientation could not be applied")

    mode = im.mode
    had_palette_transparency = "transparency" in src_info or "transparency" in im.info
    bg = settings.background_rgb

    if mode in ("I;16", "I;16L", "I;16B", "I;16N", "I", "F"):
        im = Image.fromarray(_to_uint8(np.asarray(im)), "L")
        info.notes.append(f"{mode} converted to 8-bit grayscale")
        mode = "L"
    if mode == "1":
        im = im.convert("L")
        mode = "L"
    if mode in ("P", "PA"):
        im = im.convert("RGBA")
        mode = "RGBA"
    elif mode in ("LA", "La"):
        im = im.convert("RGBA")
        mode = "RGBA"
    elif mode == "RGBa":
        im = im.convert("RGBA")
        mode = "RGBA"
    elif mode == "CMYK":
        im = im.convert("RGB")
        info.notes.append("CMYK converted to RGB (no ICC profile applied)")
        mode = "RGB"
    elif mode not in ("L", "RGB", "RGBA"):
        im = im.convert("RGB")
        mode = "RGB"

    if mode == "RGBA":
        alpha = np.asarray(im.getchannel("A"))
        info.had_alpha = True
        info.transparent_fraction = float((alpha < 255).mean())
        info.fully_transparent_fraction = float((alpha == 0).mean())
        canvas = Image.new("RGBA", im.size, bg + (255,))
        im = Image.alpha_composite(canvas, im).convert("RGB")
    elif had_palette_transparency:
        info.had_alpha = True
    if im.mode == "L":
        # keep an 8-bit gray image gray unless the user asked otherwise; the
        # composite above only applies to images with alpha
        pass

    if apply_modifications:
        im = apply_optional_modifications(im, settings)
    return im, info


def apply_optional_modifications(im: Image.Image, s: BookSettings) -> Image.Image:
    """Every step here is OFF by default and only runs when explicitly enabled."""
    if s.color_mode == "grayscale" and im.mode != "L":
        im = im.convert("L")
    if s.contrast_adjust and abs(s.contrast_factor - 1.0) > 1e-9:
        im = ImageEnhance.Contrast(im).enhance(s.contrast_factor)
    if s.near_white_clean:
        arr = np.array(im)
        if arr.ndim == 3:
            mask = (arr >= s.near_white_threshold).all(axis=2)
            arr[mask] = 255
        else:
            arr[arr >= s.near_white_threshold] = 255
        im = Image.fromarray(arr, im.mode)
    if s.bw_threshold:
        g = im.convert("L") if im.mode != "L" else im
        t = s.bw_threshold_value
        im = g.point(lambda p, t=t: 255 if p >= t else 0, "L")
    return im


def processed_filename(source_path: str | Path) -> str:
    p = Path(source_path)
    digest = hashlib.sha1(str(p.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{p.stem}_{digest}.png"


def process_one(
    source_path: str | Path, settings: BookSettings, out_dir: str | Path
) -> tuple[Path, tuple[int, int], LoadInfo]:
    """Normalise one image and save it losslessly (PNG) in `out_dir`."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    im, info = load_flattened(source_path, settings, apply_modifications=True)
    dest = out_dir / processed_filename(source_path)
    tmp = dest.with_suffix(".tmp.png")
    im.save(tmp, format="PNG", dpi=(settings.dpi_target, settings.dpi_target), compress_level=6)
    tmp.replace(dest)
    return dest, im.size, info


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
