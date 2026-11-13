"""Import af firmaer og personer fra Excel, CSV og ZIP med billeder."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image

from app.main import app


def jpg(color="#884422", size=(300, 400)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def xlsx(rows, embed: dict | None = None) -> bytes:
    """rows: første række er overskrifter. embed: {rækkenummer: billedbytes} sættes ind over cellerne."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Personer"
    for r in rows:
        ws.append(r)
    for row_no, data in (embed or {}).items():
        img = XLImage(io.BytesIO(data))
        ws.add_image(img, f"J{row_no}")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def zipped(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def upload(c, name, data, dry_run=True, **form):
    form = {k: str(v) for k, v in form.items()}
    return c.post("/api/admin/import", files={"file": (name, data)}, data={"dry_run": str(dry_run).lower(), **form})


@pytest.fixture(scope="module")
def partner_admin(client):
    plat = TestClient(app)
    plat.post("/api/admin/login", json={"password": "hemmelig"})
    partner = plat.post("/api/admin/partners", json={"name": "Importhuset"}).json()
    inv = plat.post(f"/api/admin/partners/{partner['id']}/users", json={"email": "import@huset.dk"}).json()
    c = TestClient(app)
    r = c.post("/api/admin/invite/accept", json={"token": inv["invite_url"].split("#invite=")[1],
                                                 "password": "importkode-123"})
    assert r.status_code == 200
    c.platform = plat
    return c


HEAD = ["Firma", "Navn", "Titel", "E-mail", "Mobil", "SMS", "E-mail-besked", "Billede", "Vis på skærmen"]


def test_template_downloads_as_excel(partner_admin):
    r = partner_admin.get("/api/admin/import/template")
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    wb = load_workbook(io.BytesIO(r.content))
    assert [c.value for c in wb["Personer"][1]] == HEAD
    assert "Vejledning" in wb.sheetnames


def test_partner_import_with_embedded_and_zipped_photos(partner_admin):
    c = partner_admin
    sheet = xlsx([
        HEAD,
        ["Æble ApS", "Anna Hansen", "Direktør", "Anna@Aeble.dk", "+45 20 30 40 50", "ja", "ja", "", ""],
        ["æble aps", "Bo Jensen", "Salg", "bo@aeble.dk", "", "", "", "bo.jpg", "nej"],
        ["Pære A/S", "Carla", "", "carla@paere.dk", "60708090", "", "", "", ""],
        ["Pære A/S", "", "Mangler navn", "", "", "", "", "", ""],
        ["Pære A/S", "Dorte", "", "ikke-en-mail", "", "", "", "", ""],
        ["Pære A/S", "Erik", "", "", "", "måske", "", "", ""],
    ], embed={2: jpg("#aa0000")})
    data = zipped({"personer.xlsx": sheet, "billeder/bo.jpg": jpg("#00aa00"),
                   "carla@paere.dk.png": jpg("#0000aa"), "__MACOSX/._bo.jpg": b"junk"})

    preview = upload(c, "import.zip", data, dry_run=True).json()
    assert preview["dry_run"] and preview["firms_new"] == ["Æble ApS", "Pære A/S"]
    assert preview["people_new"] == 3 and preview["people_updated"] == 0 and preview["photos"] == 3
    assert {e["row"] for e in preview["errors"]} == {5, 6, 7}
    assert c.get("/api/admin/tenants").json() == []  # forhåndsvisning gemmer intet

    done = upload(c, "import.zip", data, dry_run=False).json()
    assert done["people_new"] == 3 and done["photos"] == 3
    firms = {t["name"]: t for t in c.get("/api/admin/tenants").json()}
    assert set(firms) == {"Æble ApS", "Pære A/S"}
    aeble = c.get(f"/api/admin/tenants/{firms['Æble ApS']['id']}").json()
    assert aeble["partner_name"] == "Importhuset"
    people = {h["name"]: h for h in aeble["hosts"]}
    assert people["Anna Hansen"]["email"] == "anna@aeble.dk" and people["Anna Hansen"]["photo_url"]
    assert people["Bo Jensen"]["photo_url"] and not people["Bo Jensen"]["active"]
    assert not people["Bo Jensen"]["notify_sms"] and people["Bo Jensen"]["notify_email"]  # tom = ja hvis e-mail
    carla = c.get(f"/api/admin/tenants/{firms['Pære A/S']['id']}").json()["hosts"][0]
    assert carla["photo_url"] and carla["notify_sms"]

    # Importér igen med rettelser: personer findes på e-mail, tomme celler ændrer intet.
    again = xlsx([HEAD, ["Æble ApS", "Anna Hansen-Berg", "", "anna@aeble.dk", "", "", "nej", "", ""]])
    r = upload(c, "rettelser.xlsx", again, dry_run=False).json()
    assert r["people_new"] == 0 and r["people_updated"] == 1 and r["firms_new"] == []
    anna = next(h for h in c.get(f"/api/admin/tenants/{firms['Æble ApS']['id']}").json()["hosts"]
                if h["email"] == "anna@aeble.dk")
    assert anna["name"] == "Anna Hansen-Berg" and anna["title"] == "Direktør" and not anna["notify_email"]
    assert anna["photo_url"] == people["Anna Hansen"]["photo_url"]


def test_csv_with_semicolons(partner_admin):
    csv = "Firma;Navn;E-mail\nCSV Firma;Søren Ærø;soren@csv.dk\nCSV Firma;Åse;\n".encode("utf-8-sig")
    r = upload(partner_admin, "liste.csv", csv, dry_run=False).json()
    assert r["firms_new"] == ["CSV Firma"] and r["people_new"] == 2


def test_tenant_admin_imports_people_into_own_firm(partner_admin):
    plat = partner_admin.platform
    firm = plat.post("/api/admin/tenants", json={"name": "Egen import"}).json()
    plat.patch(f"/api/admin/tenants/{firm['id']}/subscription", json={"self_service": True})
    inv = plat.post(f"/api/admin/tenants/{firm['id']}/users", json={"email": "selv@import.dk"}).json()
    c = TestClient(app)
    c.post("/api/admin/invite/accept", json={"token": inv["invite_url"].split("#invite=")[1],
                                             "password": "selvimport-123"})
    assert "Firma" not in [x.value for x in load_workbook(io.BytesIO(
        c.get("/api/admin/import/template").content))["Personer"][1]]

    r = upload(c, "p.xlsx", xlsx([HEAD, ["Ignoreres A/S", "Gitte", "", "", "", "", "", "", ""]]), dry_run=False)
    r = r.json()
    assert r["firms"] == ["Egen import"] and r["people_new"] == 1 and "ignoreres" in r["warnings"][0]
    assert [h["name"] for h in c.get(f"/api/admin/tenants/{firm['id']}").json()["hosts"]] == ["Gitte"]

    other = plat.post("/api/admin/tenants", json={"name": "Fremmed"}).json()
    assert upload(c, "p.xlsx", xlsx([HEAD]), tenant_id=other["id"]).status_code == 404


def test_bad_files(partner_admin):
    c = partner_admin
    assert upload(c, "x.xlsx", xlsx([["Navn"], ["Uden firma"]])).status_code == 422  # partner skal have Firma
    assert upload(c, "x.xlsx", xlsx([["Noget"], ["andet"]])).status_code == 422       # ingen Navn-kolonne
    assert upload(c, "x.pdf", b"%PDF").status_code == 422
    assert upload(c, "x.zip", b"ikke en zip").status_code == 422
    assert upload(c, "x.zip", zipped({"a.jpg": jpg()})).status_code == 422
    r = upload(c, "x.zip", zipped({"a.xlsx": xlsx([HEAD, ["F", "Navn Navnesen", "", "", "", "", "", "mangler.jpg",
                                                         ""]])})).json()
    assert any("mangler.jpg" in w for w in r["warnings"])
