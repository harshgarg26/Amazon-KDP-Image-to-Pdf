"""Image discovery, natural sorting, ZIP extraction and metadata detection."""

from __future__ import annotations

import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

import warnings

from PIL import Image, UnidentifiedImageError

warnings.simplefilter("error", Image.DecompressionBombWarning)  # treat "suspiciously large" as a failure

Image.MAX_IMAGE_PIXELS = 200_000_000  # ~200 MP; above 2x this Pillow raises

SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}

# --- safety limits (protect against malicious or accidental huge inputs) -----------
MAX_IMAGE_FILE_BYTES = 300 * 1024 * 1024  # largest single image file accepted
MAX_ZIP_MEMBERS = 5000  # most image entries read from one archive
MAX_ZIP_MEMBER_BYTES = 300 * 1024 * 1024  # largest single extracted image
MAX_ZIP_TOTAL_BYTES = 4 * 1024 * 1024 * 1024  # total extracted size per archive
MAX_ZIP_RATIO = 200  # per-member compression ratio above this looks like a zip bomb
_EXIF_ORIENTATION = 0x0112
_NUM_RE = re.compile(r"(\d+)")


# ----------------------------------------------------------------------
# natural sorting
# ----------------------------------------------------------------------
def _natural_part(text: str) -> list:
    # re.split with one capture group always yields [str, int, str, int, ..., str]
    parts = _NUM_RE.split(text.casefold())
    return [int(p) if i % 2 else p for i, p in enumerate(parts)]


def natural_key(path: str | Path) -> tuple:
    """Sort key giving 1.png, 2.png, 9.png, 10.png, 11.png (never 10 before 2)."""
    p = Path(path)
    return tuple(tuple(_natural_part(part)) for part in p.parts)


def natural_sorted(paths) -> list:
    return sorted(paths, key=natural_key)


# ----------------------------------------------------------------------
# records
# ----------------------------------------------------------------------
@dataclass
class ImageRecord:
    path: str
    filename: str
    width: int = 0  # raw pixel width as stored in the file
    height: int = 0
    oriented_width: int = 0  # after applying EXIF orientation
    oriented_height: int = 0
    aspect_ratio: float = 0.0  # oriented width / height
    format: str = ""
    mode: str = ""
    has_alpha: bool = False
    dpi: tuple[float, float] | None = None
    exif_orientation: int = 1
    file_size: int = 0
    mtime: float = 0.0
    origin: str = ""  # e.g. "zip:pages.zip"
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def size_text(self) -> str:
        if not self.ok:
            return "-"
        return f"{self.oriented_width} x {self.oriented_height}"

    @property
    def dpi_text(self) -> str:
        if not self.dpi:
            return "none"
        return f"{self.dpi[0]:g} x {self.dpi[1]:g}"

    def to_dict(self) -> dict:
        return asdict(self)


def _has_alpha(im: Image.Image) -> bool:
    if im.mode in ("RGBA", "LA", "La", "PA", "RGBa"):
        return True
    return "transparency" in im.info


def read_metadata(path: str | Path, origin: str = "") -> ImageRecord:
    """Read metadata for one image. Never raises - problems are stored in `.error`."""
    p = Path(path)
    rec = ImageRecord(path=str(p), filename=p.name, origin=origin)
    try:
        st = p.stat()
        rec.file_size, rec.mtime = st.st_size, st.st_mtime
    except OSError as exc:
        rec.error = f"Cannot read file: {exc}"
        return rec
    if p.suffix.lower() not in SUPPORTED_EXTS:
        rec.error = f"Unsupported format '{p.suffix}'"
        return rec
    if st.st_size == 0:
        rec.error = "File is empty"
        return rec
    if st.st_size > MAX_IMAGE_FILE_BYTES:
        rec.error = f"File is too large ({st.st_size / 1e6:.0f} MB; limit {MAX_IMAGE_FILE_BYTES // 2**20} MB)"
        return rec
    try:
        with Image.open(p) as probe:
            probe.verify()  # cheap structural check; truncation is caught on full decode
        with Image.open(p) as im:
            rec.width, rec.height = im.size
            rec.format = im.format or p.suffix.lstrip(".").upper()
            rec.mode = im.mode
            rec.has_alpha = _has_alpha(im)
            dpi = im.info.get("dpi")
            if dpi and len(dpi) >= 2:
                try:
                    rec.dpi = (round(float(dpi[0]), 2), round(float(dpi[1]), 2))
                except (TypeError, ValueError):
                    rec.dpi = None
            try:
                orient = int(im.getexif().get(_EXIF_ORIENTATION, 1) or 1)
            except Exception:
                orient = 1
            rec.exif_orientation = orient if 1 <= orient <= 8 else 1
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        rec.error = f"Cannot open image: {exc}"
        return rec
    swap = rec.exif_orientation in (5, 6, 7, 8)
    rec.oriented_width = rec.height if swap else rec.width
    rec.oriented_height = rec.width if swap else rec.height
    rec.aspect_ratio = rec.oriented_width / rec.oriented_height if rec.oriented_height else 0.0
    return rec


# ----------------------------------------------------------------------
# collection
# ----------------------------------------------------------------------
@dataclass
class CollectResult:
    files: list[tuple[Path, str]] = field(default_factory=list)  # (path, origin)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (name, reason)


def _is_hidden(path: Path) -> bool:
    return any(part.startswith(".") or part == "__MACOSX" for part in path.parts if part not in (".", ".."))


def collect_paths(items, zip_dest: str | Path | None = None, recursive: bool = False) -> CollectResult:
    """Expand files, folders and ZIP archives into a list of image files."""
    result = CollectResult()
    for item in items:
        p = Path(item)
        if p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            for f in natural_sorted(it):
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS and not f.name.startswith("."):
                    result.files.append((f, ""))
        elif p.suffix.lower() == ".zip":
            if zip_dest is None:
                result.rejected.append((p.name, "ZIP import needs an extraction folder"))
                continue
            try:
                for f in extract_zip(p, Path(zip_dest) / p.stem):
                    result.files.append((f, f"zip:{p.name}"))
            except (zipfile.BadZipFile, OSError) as exc:
                result.rejected.append((p.name, f"Cannot extract ZIP: {exc}"))
        elif p.is_file():
            if p.suffix.lower() in SUPPORTED_EXTS:
                result.files.append((p, ""))
            else:
                result.rejected.append((p.name, f"Unsupported format '{p.suffix}'"))
        else:
            result.rejected.append((str(p), "Path does not exist"))
    return result


_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                 *(f"LPT{i}" for i in range(1, 10))}


def _safe_member_path(name: str) -> PurePosixPath | None:
    """Return a safe relative path for an archive member, or None to skip it."""
    rel = PurePosixPath(name.replace("\\", "/"))
    if rel.is_absolute() or not rel.parts:
        return None
    for part in rel.parts:
        if part in ("..", ".") or ":" in part or part != part.strip() or part.endswith("."):
            return None  # traversal, drive letters, NTFS alternate data streams
        if part.split(".")[0].upper() in _WIN_RESERVED:
            return None
        if any(ord(ch) < 32 for ch in part):
            return None
    if _is_hidden(Path(*rel.parts)):
        return None
    return rel


def extract_zip(zip_path: str | Path, dest: str | Path) -> list[Path]:
    """Extract only supported image members.

    Protections: path traversal, absolute paths, drive letters / NTFS streams, Windows
    reserved names, symbolic links, member-count / size / compression-ratio limits (zip
    bombs). Sizes are enforced while streaming, not trusted from the archive header."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()
    out: list[Path] = []
    total = 0
    with zipfile.ZipFile(zip_path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_ZIP_MEMBERS * 4:
            raise zipfile.BadZipFile(f"Archive has too many entries ({len(infos)})")
        for info in infos:
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                continue  # symbolic link
            rel = _safe_member_path(info.filename)
            if rel is None or rel.suffix.lower() not in SUPPORTED_EXTS:
                continue
            if len(out) >= MAX_ZIP_MEMBERS:
                raise zipfile.BadZipFile(f"Archive has more than {MAX_ZIP_MEMBERS} images")
            if info.file_size > MAX_ZIP_MEMBER_BYTES:
                raise zipfile.BadZipFile(f"'{info.filename}' is too large to extract")
            if info.compress_size and info.file_size / info.compress_size > MAX_ZIP_RATIO \
                    and info.file_size > 10 * 1024 * 1024:
                raise zipfile.BadZipFile(f"'{info.filename}' has a suspicious compression ratio (zip bomb?)")
            target = (dest / Path(*rel.parts)).resolve()
            if dest_root not in target.parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            try:
                with zf.open(info) as src, open(target, "wb") as dst:
                    while True:
                        chunk = src.read(1 << 20)
                        if not chunk:
                            break
                        written += len(chunk)
                        total += len(chunk)
                        if written > MAX_ZIP_MEMBER_BYTES or total > MAX_ZIP_TOTAL_BYTES:
                            raise zipfile.BadZipFile("Archive expands beyond the allowed size (zip bomb?)")
                        dst.write(chunk)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            out.append(target)
    return natural_sorted(out)


def import_images(items, zip_dest: str | Path | None = None, recursive: bool = False):
    """Collect, naturally sort and read metadata. Returns (records, rejected)."""
    collected = collect_paths(items, zip_dest=zip_dest, recursive=recursive)
    seen: set[str] = set()
    records: list[ImageRecord] = []
    for path, origin in sorted(collected.files, key=lambda t: natural_key(t[0])):
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        records.append(read_metadata(path, origin=origin))
    return records, collected.rejected
