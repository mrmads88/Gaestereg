"""Billeder i Azure Blob Storage (prod) med lokal kopi. Testes med en falsk container uden netværk."""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main as app_main
from app import media
from app.main import app


class ResourceNotFoundError(Exception):
    pass


class FakeBlob:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def exists(self):
        return self.name in self.store

    def readall(self):
        return self.store[self.name]


class FakeContainer:
    def __init__(self):
        self.store, self.meta = {}, {}

    def upload_blob(self, name, data, overwrite=False, content_settings=None):
        self.store[name] = bytes(data)
        self.meta[name] = content_settings

    def delete_blob(self, name):
        if name not in self.store:
            raise ResourceNotFoundError(name)
        del self.store[name]

    def get_blob_client(self, name):
        return FakeBlob(self.store, name)

    def download_blob(self, name):
        if name not in self.store:
            raise ResourceNotFoundError(name)
        return FakeBlob(self.store, name)


def test_blob_storage_keeps_a_local_copy(tmp_path):
    fake = FakeContainer()
    s = media.BlobStorage(fake, tmp_path)
    s.save("a" * 32 + ".png", b"png-data")
    name = "a" * 32 + ".png"
    assert fake.store[name] == b"png-data" and (tmp_path / name).read_bytes() == b"png-data"
    assert fake.meta[name].content_type == "image/png" and "immutable" in fake.meta[name].cache_control
    # En ny server uden lokal kopi henter billedet fra Blob første gang.
    (tmp_path / name).unlink()
    assert s.exists(name) and Path(s.path(name)).read_bytes() == b"png-data"
    s.delete(name)
    assert name not in fake.store and not (tmp_path / name).exists() and not s.exists(name)
    s.delete(name)  # at slette noget, der er væk, er ikke en fejl


@pytest.fixture()
def blob(tmp_path):
    fake = FakeContainer()
    old = media.storage
    store = media.BlobStorage(fake, tmp_path)
    media.storage = app_main.storage = store
    yield fake, tmp_path
    media.storage = app_main.storage = old


def test_uploads_go_to_blob_and_are_served(client, blob):
    fake, cache = blob
    c = TestClient(app)
    c.post("/api/admin/login", json={"password": "hemmelig"})
    t = c.post("/api/admin/tenants", json={"name": "Blobfirma"}).json()
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "#225").save(buf, "PNG")
    r = c.post(f"/api/admin/tenants/{t['id']}/image/logo", files={"file": ("logo.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200
    name = r.json()["logo_url"].split("/media/")[1]
    assert name in fake.store
    (cache / name).unlink()  # som efter en genstart på en ny server
    got = c.get(f"/media/{name}")
    assert got.status_code == 200 and got.content == fake.store[name]
    c.delete(f"/api/admin/tenants/{t['id']}")
    assert name not in fake.store  # firmaets billeder ryddes også op i Blob


def test_old_files_are_copied_to_blob(client, blob, monkeypatch, tmp_path_factory):
    fake, cache = blob
    old_dir = tmp_path_factory.mktemp("data") / "media"
    old_dir.mkdir()
    (old_dir / ("b" * 32 + ".png")).write_bytes(b"gammel")
    (old_dir / ("c" * 32 + ".png")).write_bytes(b"findes")
    fake.store["c" * 32 + ".png"] = b"findes"
    monkeypatch.setattr(media.settings, "data_dir", old_dir.parent)
    c = TestClient(app)
    c.post("/api/admin/login", json={"password": "hemmelig"})
    r = c.post("/api/admin/ops/media-to-blob").json()
    assert r["ok"] and r["sent"] == 1 and r["skipped"] == 1 and fake.store["b" * 32 + ".png"] == b"gammel"
