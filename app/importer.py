"""Import af firmaer og personer fra Excel (.xlsx), CSV eller en ZIP-fil med ark og billeder.

Billeder kan komme tre steder fra:
1. Indlejret i Excel-arket ud for personens række (Indsæt > Billede > Placer over celler).
2. I en ZIP-fil sammen med arket. Kolonnen "Billede" angiver filnavnet.
3. I ZIP-filen med personens e-mail eller navn som filnavn, fx anna@firma.dk.jpg eller Anna Hansen.png.

Tomme celler ændrer ikke noget på personer, der findes i forvejen.
Hele importen kører i én transaktion. Ved forhåndsvisning (dry_run) rulles den tilbage, og
der gemmes ingen billeder. Så viser forhåndsvisningen præcis, hvad importen vil gøre.
"""
import csv
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .media import check_image, delete_media, store_image
from .models import Host, Tenant

MAX_FILE = 60 * 1024 * 1024
MAX_UNZIPPED = 200 * 1024 * 1024
MAX_ROWS = 2000
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

# Kolonnenavne, vi forstår. Sammenlignes uden store bogstaver, mellemrum og tegn.
HEADERS = {
    "firm": ["firma", "virksomhed", "company", "kunde", "firmanavn"],
    "name": ["navn", "name", "fuldenavn", "fuldtnavn"],
    "title": ["titel", "title", "stilling", "jobtitel"],
    "email": ["email", "mail", "emailadresse"],
    "phone": ["mobil", "telefon", "tlf", "phone", "mobilnummer", "telefonnummer"],
    "notify_sms": ["sms", "beskedpasms", "smsbesked"],
    "notify_email": ["emailbesked", "beskedpaemail", "mailbesked", "beskedpamail"],
    "photo": ["billede", "foto", "photo", "billedfil", "image"],
    "active": ["vispaskaermen", "vis", "aktiv", "active"],
}
TEMPLATE_COLUMNS = ["Firma", "Navn", "Titel", "E-mail", "Mobil", "SMS", "E-mail-besked", "Billede",
                    "Vis på skærmen"]


def _norm(s) -> str:
    s = str(s or "").lower().replace("æ", "ae").replace("ø", "o").replace("å", "a")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s)


def _key(s: str) -> str:
    """Til at matche navne: små bogstaver og ét mellemrum, men æøå bevares."""
    return " ".join(str(s or "").split()).casefold()


_HEADER_LOOKUP = {_norm(h): k for k, hs in HEADERS.items() for h in hs}


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)  # mobilnumre læst som tal
    return " ".join(str(v).split())


def _flag(v: str) -> bool | None:
    n = _norm(v)
    if not n:
        return None
    if n in ("ja", "j", "x", "1", "yes", "y", "true", "sand"):
        return True
    if n in ("nej", "n", "0", "no", "false", "falsk"):
        return False
    raise ValueError(f'"{v}" skal være ja eller nej')


# ---------- reading files ----------

@dataclass
class Sheet:
    columns: list[str]                                  # vores nøgler, fx ["firm", "name", ...]
    rows: list[tuple[int, dict]]                        # (rækkenummer i arket, {nøgle: værdi})
    row_images: dict[int, bytes] = field(default_factory=dict)
    files: dict[str, bytes] = field(default_factory=dict)   # billeder fra ZIP, nøgle = filnavn (små bogstaver)
    unknown_columns: list[str] = field(default_factory=list)


def _table(raw_rows: list[list], first_row_no: int = 1) -> Sheet:
    for i, raw in enumerate(raw_rows[:20]):
        keys = [_HEADER_LOOKUP.get(_norm(c)) for c in raw]
        if "name" in keys:
            header_idx = i
            break
    else:
        raise HTTPException(422, 'Arket mangler en kolonne, der hedder "Navn". Brug gerne skabelonen.')
    header = raw_rows[header_idx]
    keys = [_HEADER_LOOKUP.get(_norm(c)) for c in header]
    unknown = [str(c) for c, k in zip(header, keys) if k is None and _cell(c)]
    rows = []
    for j, raw in enumerate(raw_rows[header_idx + 1:], start=header_idx + 1 + first_row_no):
        rec = {k: _cell(v) for k, v in zip(keys, raw) if k}
        if any(rec.values()):
            rows.append((j, rec))
    if len(rows) > MAX_ROWS:
        raise HTTPException(422, f"Arket har {len(rows)} rækker. Højst {MAX_ROWS} ad gangen.")
    return Sheet([k for k in keys if k], rows, unknown_columns=unknown)


def _read_xlsx(data: bytes) -> Sheet:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True)
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "Excel-filen kunne ikke læses. Gem den som .xlsx og prøv igen.")
    ws = wb["Personer"] if "Personer" in wb.sheetnames else wb.worksheets[0]
    sheet = _table([list(r) for r in ws.iter_rows(values_only=True)])
    # Billeder, der ligger over cellerne. anchor._from.row er 0-baseret.
    for img in getattr(ws, "_images", []):
        try:
            row_no = img.anchor._from.row + 1
            sheet.row_images[row_no] = img._data()
        except Exception:  # noqa: BLE001 - et billede, vi ikke kan placere, springes over
            continue
    return sheet


def _read_csv(data: bytes) -> Sheet:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        delimiter = csv.Sniffer().sniff(text[:4000], delimiters=";,\t").delimiter
    except csv.Error:
        delimiter = ";"  # dansk Excel gemmer CSV med semikolon
    return _table(list(csv.reader(io.StringIO(text), delimiter=delimiter)))


def _read_zip(data: bytes) -> Sheet:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(422, "ZIP-filen kunne ikke åbnes")
    infos = [i for i in zf.infolist() if not i.is_dir() and "__MACOSX" not in i.filename
             and not PurePosixPath(i.filename).name.startswith(".")]
    if sum(i.file_size for i in infos) > MAX_UNZIPPED:
        raise HTTPException(422, "ZIP-filen er for stor udpakket (maks 200 MB)")
    sheets = [i for i in infos if i.filename.lower().endswith((".xlsx", ".csv"))]
    if not sheets:
        raise HTTPException(422, "ZIP-filen skal indeholde et Excel-ark (.xlsx) eller en CSV-fil")
    if len(sheets) > 1:
        raise HTTPException(422, "ZIP-filen indeholder flere ark. Læg kun ét ark i ZIP-filen.")
    sheet_info = sheets[0]
    raw = zf.read(sheet_info)
    sheet = _read_xlsx(raw) if sheet_info.filename.lower().endswith(".xlsx") else _read_csv(raw)
    for i in infos:
        name = PurePosixPath(i.filename).name
        if PurePosixPath(name).suffix.lower() in IMAGE_EXT:
            sheet.files[name.lower()] = zf.read(i)
    return sheet


def read_upload(filename: str, data: bytes) -> Sheet:
    if not data:
        raise HTTPException(400, "Filen er tom")
    if len(data) > MAX_FILE:
        raise HTTPException(400, "Filen er for stor (maks 60 MB)")
    name = (filename or "").lower()
    if name.endswith(".zip"):
        return _read_zip(data)
    if name.endswith(".xlsx"):
        return _read_xlsx(data)
    if name.endswith(".csv") or name.endswith(".txt"):
        return _read_csv(data)
    raise HTTPException(422, "Brug en Excel-fil (.xlsx), en CSV-fil eller en ZIP-fil med ark og billeder")


# ---------- applying ----------

@dataclass
class Scope:
    kind: str                      # tenant | partner | none
    tenant: Tenant | None = None   # kind == tenant
    partner_id: int | None = None  # kind == partner


def _find_photo(sheet: Sheet, row_no: int, rec: dict) -> tuple[bytes | None, str | None]:
    if row_no in sheet.row_images:
        return sheet.row_images[row_no], None
    wanted = rec.get("photo", "")
    if wanted:
        base = PurePosixPath(wanted.replace("\\", "/")).name.lower()
        if base in sheet.files:
            return sheet.files[base], None
        stems = {PurePosixPath(n).stem: n for n in sheet.files}
        if PurePosixPath(base).stem in stems:
            return sheet.files[stems[PurePosixPath(base).stem]], None
        return None, f'Billedet "{wanted}" findes ikke i ZIP-filen'
    # Ingen kolonne: prøv e-mail eller navn som filnavn.
    stems = {PurePosixPath(n).stem: n for n in sheet.files}
    for cand in (rec.get("email", "").lower(), _key(rec.get("name", ""))):
        if cand and cand in stems:
            return sheet.files[stems[cand]], None
    return None, None


def apply_import(db: Session, scope: Scope, sheet: Sheet, dry_run: bool, default_sender) -> dict:
    from .notify import valid_email

    errors, warnings, preview = [], [], []
    firms_new, firms_used = [], set()
    counts = {"new": 0, "updated": 0, "photos": 0}
    saved_files, old_files = [], []
    tenants_by_name: dict[str, Tenant] = {}

    if scope.kind == "tenant" and "firm" in sheet.columns:
        warnings.append(f'Kolonnen "Firma" ignoreres. Alle personer lægges ind hos {scope.tenant.name}.')
    if scope.kind != "tenant" and "firm" not in sheet.columns:
        raise HTTPException(422, 'Arket mangler kolonnen "Firma", som fortæller, hvilket firma personen hører til.')
    if sheet.unknown_columns:
        warnings.append("Disse kolonner bliver ikke brugt: " + ", ".join(sheet.unknown_columns))

    # Firmaer og personer slås op i Python, ikke med SQL lower(): SQLite laver kun A-Z om til små bogstaver,
    # så "Æble ApS" ville ellers blive oprettet to gange.
    if scope.kind != "tenant":
        q = select(Tenant).where(Tenant.partner_id == scope.partner_id if scope.kind == "partner"
                                 else Tenant.partner_id.is_(None))
        for x in db.scalars(q):
            tenants_by_name.setdefault(_key(x.name), x)
    hosts_by_tenant: dict[int, list[Host]] = {}

    def tenant_for(name: str) -> Tenant:
        k = _key(name)
        if k not in tenants_by_name:
            t = Tenant(name=name, sms_sender=default_sender(name), partner_id=scope.partner_id)
            db.add(t)
            db.flush()
            firms_new.append(name)
            tenants_by_name[k] = t
        return tenants_by_name[k]

    def hosts_of(t: Tenant) -> list[Host]:
        if t.id not in hosts_by_tenant:
            hosts_by_tenant[t.id] = list(db.scalars(select(Host).where(Host.tenant_id == t.id)))
        return hosts_by_tenant[t.id]

    try:
        for row_no, rec in sheet.rows:
            name = rec.get("name", "")
            if not name:
                errors.append({"row": row_no, "message": "Navn mangler"})
                continue
            email = rec.get("email", "").lower()
            if email and not valid_email(email):
                errors.append({"row": row_no, "message": f'"{rec["email"]}" er ikke en gyldig e-mail'})
                continue
            try:
                flags = {k: _flag(rec.get(k, "")) for k in ("notify_sms", "notify_email", "active")}
            except ValueError as e:
                errors.append({"row": row_no, "message": str(e)})
                continue
            if len(name) > 120 or len(rec.get("title", "")) > 120 or len(rec.get("phone", "")) > 40:
                errors.append({"row": row_no, "message": "Navn, titel eller mobil er for lang"})
                continue

            if scope.kind == "tenant":
                t = scope.tenant
            else:
                firm = rec.get("firm", "")
                if not firm:
                    errors.append({"row": row_no, "message": "Firma mangler"})
                    continue
                if len(firm) > 120:
                    errors.append({"row": row_no, "message": "Firmanavnet er for langt (maks 120 tegn)"})
                    continue
                t = tenant_for(firm)
            firms_used.add(t.name)

            # Find personen: på e-mail, ellers på navn (hvis den fundne ikke har en anden e-mail).
            people = hosts_of(t)
            h = next((x for x in people if email and (x.email or "").lower() == email), None)
            if h is None:
                h = next((x for x in people if _key(x.name) == _key(name) and (not email or not x.email)), None)
            action = "opdateret" if h is not None else "ny"
            if h is None:
                last = max((x.sort_order for x in people), default=-1)
                h = Host(tenant_id=t.id, name=name, title="", email="", phone="", photo_path="",
                         sort_order=last + 1, notify_sms=bool(rec.get("phone")), notify_email=bool(email),
                         active=True)
                db.add(h)
                people.append(h)
            h.name = name
            for k in ("title", "phone"):
                if rec.get(k):
                    setattr(h, k, rec[k])
            if email:
                h.email = email
            for k, v in flags.items():
                if v is not None:
                    setattr(h, k, v)

            photo, problem = _find_photo(sheet, row_no, rec)
            if problem:
                warnings.append(f"Række {row_no}: {problem}")
            if photo is not None:
                try:
                    if dry_run:
                        check_image(photo)
                    else:
                        new_name = store_image(photo, "photo")
                        saved_files.append(new_name)
                        if h.photo_path:
                            old_files.append(h.photo_path)
                        h.photo_path = new_name
                    counts["photos"] += 1
                except HTTPException as e:
                    warnings.append(f"Række {row_no}: billedet blev sprunget over. {e.detail}")
                    photo = None
            db.flush()
            counts["new" if action == "ny" else "updated"] += 1
            preview.append({"row": row_no, "firm": t.name, "name": name, "action": action,
                            "photo": photo is not None})

        if dry_run:
            db.rollback()
        else:
            db.commit()
            for f in old_files:
                delete_media(f)
    except Exception:
        db.rollback()
        for f in saved_files:
            delete_media(f)
        raise

    return {
        "dry_run": dry_run,
        "firms_new": firms_new,
        "firms": sorted(firms_used),
        "people_new": counts["new"],
        "people_updated": counts["updated"],
        "photos": counts["photos"],
        "errors": errors,
        "warnings": warnings,
        "rows": preview[:500],
        "row_count": len(sheet.rows),
    }


def template_xlsx(with_firm: bool = True) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "Personer"
    cols = TEMPLATE_COLUMNS if with_firm else TEMPLATE_COLUMNS[1:]
    ws.append(cols)
    examples = [
        ["Firma 1 ApS", "Anna Hansen", "Direktør", "anna@firma1.dk", "+45 20 30 40 50", "ja", "ja",
         "anna.jpg", "ja"],
        ["Firma 1 ApS", "Bo Jensen", "Salgschef", "bo@firma1.dk", "", "nej", "ja", "", "ja"],
        ["Firma 2 A/S", "Carla Nielsen", "Reception", "carla@firma2.dk", "+45 60 70 80 90", "ja", "nej", "",
         "ja"],
    ]
    for ex in examples:
        ws.append(ex if with_firm else ex[1:])
    fill = PatternFill("solid", fgColor="1F3A5A")
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = fill
    for i, w in enumerate([18, 22, 18, 26, 18, 8, 14, 16, 15][-len(cols):], start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    ws.freeze_panes = "A2"
    yes_no = DataValidation(type="list", formula1='"ja,nej"', allow_blank=True)
    ws.add_data_validation(yes_no)
    for name in ("SMS", "E-mail-besked", "Vis på skærmen"):
        letter = ws.cell(1, cols.index(name) + 1).column_letter
        yes_no.add(f"{letter}2:{letter}{MAX_ROWS + 1}")

    guide = wb.create_sheet("Vejledning")
    lines = [
        "Sådan bruger du arket",
        "",
        "Én række pr. person. Kun Navn er påkrævet" + (" (og Firma)." if with_firm else "."),
        "Firma: personen lægges ind hos firmaet med det navn. Findes firmaet ikke, oprettes det." if with_firm
        else "Alle personer lægges ind hos det firma, du importerer til.",
        "Personer findes igen på e-mail (ellers navn). Så kan du rette arket og importere igen.",
        "Tomme celler ændrer ikke noget hos personer, der findes i forvejen.",
        "SMS / E-mail-besked: ja eller nej. Tom = ja, hvis mobil/e-mail er udfyldt.",
        "Vis på skærmen: nej skjuler personen på skærmen. Tom = ja.",
        "",
        "Billeder (valgfrit) kan tilføjes på to måder:",
        "1) Sæt billedet ind i arket ud for personen: Indsæt > Billeder > Placer over celler.",
        "2) Læg arket og billederne i én ZIP-fil og skriv filnavnet i kolonnen Billede (fx anna.jpg).",
        "   Uden kolonnen findes billedet på e-mail eller navn, fx anna@firma1.dk.jpg eller Anna Hansen.jpg.",
        "",
        "Du ser altid en forhåndsvisning, før noget bliver gemt.",
    ]
    for line in lines:
        guide.append([line])
    guide["A1"].font = Font(bold=True, size=14)
    guide.column_dimensions["A"].width = 100

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
