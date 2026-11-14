"""Databehandleraftalen (GDPR art. 28): tekst, version og hvem der skal acceptere.

Kundens admin accepterer ved første login. Har huset (partneren) accepteret, dækker det husets firmaer.
Teksten ligger i app/texts/databehandleraftale.html og er et udkast, indtil DPA_FINAL=1 (sat efter juridisk
gennemgang). Den endelige version har et andet versionsnummer, så alle skal acceptere igen.
"""
import html
import re
from pathlib import Path
from string import Template

from .config import settings
from .models import Partner, Tenant

DPA_VERSION = "2026-11"
TEXT = Path(__file__).parent / "texts" / "databehandleraftale.html"


def version() -> str:
    return DPA_VERSION if settings.dpa_final else DPA_VERSION + "-udkast"


def dpa_html(kunde: str = "") -> str:
    e = lambda v, alt: html.escape(v) if v else f"[{alt}]"  # noqa: E731
    draft = "" if settings.dpa_final else (
        '<p class="udkast">UDKAST til juridisk gennemgang. Teksten er ikke endelig.</p>')
    raw = re.sub(r"<!--.*?-->", "", TEXT.read_text(encoding="utf-8"), flags=re.S)  # interne noter vises ikke
    return Template(raw).safe_substitute(
        leverandoer=e(settings.operator_name, "Leverandørens navn"), cvr=e(settings.operator_cvr, "CVR"),
        adresse=e(settings.operator_address, "adresse"), email=e(settings.operator_email, "e-mail"),
        kunde=e(kunde, "Kunden"), version=html.escape(version()), udkast=draft)


def org_of(db, p):
    """Den organisation, en bruger accepterer på vegne af (firma eller hus). None for leverandøren."""
    if p.role == "tenant" and p.tenant_id:
        return db.get(Tenant, p.tenant_id)
    if p.role == "partner" and p.partner_id:
        return db.get(Partner, p.partner_id)
    return None


def required(db, p) -> bool:
    """Skal brugerens firma eller hus acceptere den nuværende version?"""
    org = org_of(db, p)
    if org is None:
        return False
    v = version()
    if org.dpa_version == v:
        return False
    if isinstance(org, Tenant) and org.partner is not None and org.partner.dpa_version == v:
        return False  # huset har accepteret på vegne af sine firmaer
    return True


def status(org) -> dict:
    from .timeutil import local_iso
    return {"version": org.dpa_version, "accepted_at": local_iso(org.dpa_accepted_at), "accepted_by": org.dpa_accepted_by,
            "current": org.dpa_version == version()}
