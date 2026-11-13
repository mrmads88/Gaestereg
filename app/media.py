"""Image uploads: validated, resized and stored under DATA_DIR/media."""
import io
import re
import uuid

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps

from .config import settings

MAX_BYTES = 10 * 1024 * 1024

# kind -> (max side px, output format, square crop)
PROFILES = {
    "logo": (1200, "PNG", False),
    "background": (1920, "JPEG", False),
    "photo": (600, "JPEG", True),
}

_SVG_BAD = re.compile(r"<script|<foreignObject|\son[a-z]+\s*=|javascript:|<iframe|<embed|<object", re.I)


async def save_image(file: UploadFile, kind: str) -> str:
    return store_image(await file.read(), kind)


def check_image(data: bytes) -> None:
    """Tjek at data kan læses som et billede, uden at gemme noget (bruges ved forhåndsvisning af import)."""
    if not data:
        raise HTTPException(400, "Filen er tom")
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "Billedet er for stort. Maks 10 MB")
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Filen kunne ikke læses som et billede. Brug PNG eller JPG")


def store_image(data: bytes, kind: str) -> str:
    """Valider, skaler og gem et billede. Returnerer filnavnet under DATA_DIR/media."""
    if not data:
        raise HTTPException(400, "Filen er tom")
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "Billedet er for stort. Maks 10 MB")

    head = data[:400].lstrip().lower()
    if kind == "logo" and (head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2000].lower())):
        text = data.decode("utf-8", errors="replace")
        if _SVG_BAD.search(text):
            raise HTTPException(400, "SVG-filen indeholder scripts og kan ikke bruges")
        name = f"{uuid.uuid4().hex}.svg"
        (settings.media_dir / name).write_bytes(data)
        return name

    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Filen kunne ikke læses som et billede. Brug PNG, JPG eller SVG")

    max_side, fmt, square = PROFILES[kind]
    if square:
        img = ImageOps.fit(img.convert("RGB"), (max_side, max_side), Image.LANCZOS, centering=(0.5, 0.35))
    else:
        img.thumbnail((max_side, max_side), Image.LANCZOS)

    buf = io.BytesIO()
    if fmt == "PNG":
        if img.mode not in ("RGBA", "LA", "P", "RGB", "L"):
            img = img.convert("RGBA")
        img.save(buf, "PNG", optimize=True)
        ext = "png"
    else:
        img.convert("RGB").save(buf, "JPEG", quality=84, optimize=True, progressive=True)
        ext = "jpg"
    name = f"{uuid.uuid4().hex}.{ext}"
    (settings.media_dir / name).write_bytes(buf.getvalue())
    return name


def delete_media(name: str) -> None:
    if not name or "/" in name or "\\" in name:
        return
    p = settings.media_dir / name
    if p.exists():
        p.unlink()


def media_url(name: str) -> str:
    return f"/media/{name}" if name else ""
