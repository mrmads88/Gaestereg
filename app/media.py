"""Image uploads: validated, resized and stored under DATA_DIR/media."""
import io
import re
import uuid

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps

from .config import settings

MAX_BYTES = 10 * 1024 * 1024


class LocalStorage:
    """Billeder som filer i DATA_DIR/media. Skal billederne senere i Azure Blob Storage, laves en klasse med
    de samme fire metoder, og `storage` herunder skiftes. Resten af koden bruger kun dem."""

    def __init__(self, root):
        self.root = root

    def save(self, name: str, data: bytes) -> None:
        (self.root / name).write_bytes(data)

    def delete(self, name: str) -> None:
        p = self.root / name
        if p.exists():
            p.unlink()

    def exists(self, name: str) -> bool:
        return (self.root / name).exists()

    def path(self, name: str):
        return self.root / name


CONTENT_TYPES = {"png": "image/png", "jpg": "image/jpeg", "svg": "image/svg+xml"}


class BlobStorage:
    """Billeder i Azure Blob Storage (prod), så de overlever, at serveren flyttes eller skaleres.

    /media svarer fra en lokal kopi (DATA_DIR/media), der hentes fra Blob første gang, et billede bruges. Billednavne
    er tilfældige og ændres aldrig, så kopien kan aldrig blive forældet. Samme fire metoder som LocalStorage."""

    def __init__(self, container, cache_root):
        self.container = container  # azure.storage.blob.ContainerClient (eller en falsk i tests)
        self.cache = LocalStorage(cache_root)

    def save(self, name: str, data: bytes) -> None:
        from azure.storage.blob import ContentSettings
        ext = name.rsplit(".", 1)[-1]
        self.container.upload_blob(name, data, overwrite=True, content_settings=ContentSettings(
            content_type=CONTENT_TYPES.get(ext, "application/octet-stream"),
            cache_control="public, max-age=31536000, immutable"))
        self.cache.save(name, data)

    def delete(self, name: str) -> None:
        try:
            self.container.delete_blob(name)
        except Exception as e:  # noqa: BLE001 - findes den ikke, er den allerede væk
            if type(e).__name__ != "ResourceNotFoundError":
                raise
        self.cache.delete(name)

    def exists(self, name: str) -> bool:
        return self.cache.exists(name) or self.container.get_blob_client(name).exists()

    def path(self, name: str):
        if not self.cache.exists(name):
            self.cache.save(name, self.container.download_blob(name).readall())
        return self.cache.path(name)


def make_storage():
    """Blob Storage, når AZURE_STORAGE_CONNECTION_STRING er sat (prod). Ellers lokale filer (dev, tests)."""
    if not settings.azure_storage_connection_string:
        return LocalStorage(settings.media_dir)
    from azure.storage.blob import BlobServiceClient
    container = BlobServiceClient.from_connection_string(settings.azure_storage_connection_string) \
        .get_container_client(settings.azure_storage_container)
    try:
        container.create_container()
    except Exception as e:  # noqa: BLE001 - findes allerede
        if type(e).__name__ != "ResourceExistsError":
            raise
    return BlobStorage(container, settings.media_dir)


storage = make_storage()

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
        storage.save(name, data)
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
    storage.save(name, buf.getvalue())
    return name


def delete_media(name: str) -> None:
    if not name or "/" in name or "\\" in name:
        return
    storage.delete(name)


def media_url(name: str) -> str:
    return f"/media/{name}" if name else ""
