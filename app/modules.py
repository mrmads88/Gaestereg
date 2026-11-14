"""Moduler: det, kunden har købt, låser funktioner op. Gæsteregistrering er altid med.

Modulerne følger af kundens aktive pakker og tilkøb (billing.py, Product.modules). En kunde er et firma eller et hus.
Har huset et modul, gælder det for alle husets firmaer (huset betaler). Har kun firmaet modulet, kan firmaet bruge
sine egne lokaler og køkkener. Slås et modul fra, slettes intet; det skjules bare.

Resultatet caches i hukommelsen pr. dag og tømmes ved alle admin-ændringer (middleware i main.py), så skærme og
bookingsider ikke spørger databasen om abonnementet hver gang.
"""
import json
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import object_session

from .models import BillingAccount, Partner, Tenant

MODULES = ("rooms", "catering", "self_service", "reports", "signage")
NAMES = {"rooms": "Mødelokaler", "catering": "Forplejning", "self_service": "Selvbetjening",
         "reports": "Overblik og månedsrapport", "signage": "Infoskærm"}

_cache: dict[tuple[str, int, date], frozenset] = {}


def clear_cache() -> None:
    _cache.clear()


def _granted(db, col, oid: int) -> frozenset:
    from . import billing  # undgå cirkulær import
    key = (col, oid, date.today())
    if key not in _cache:
        acc = db.scalar(select(BillingAccount).where(getattr(BillingAccount, col) == oid))
        _cache[key] = frozenset(billing.modules_of_account(db, acc.id, key[2])) if acc else frozenset()
    return _cache[key]


def prime(db, tenants: list[Tenant]) -> None:
    """Fyld cachen for mange firmaer på én gang (kundelisten i admin): tre forespørgsler i alt, uden lange IN-lister.
    Alle kundekonti og tilmeldinger læses; der er én konto pr. betalende kunde, så tabellerne er små."""
    from . import billing
    from .models import AccountProduct
    today = date.today()
    accs = db.scalars(select(BillingAccount)).all()
    owner = {a.id: ("tenant_id", a.tenant_id) if a.tenant_id else ("partner_id", a.partner_id) for a in accs}
    prods = billing.products_by_id(db)
    grants: dict[tuple, set] = {("tenant_id", t.id): set() for t in tenants}
    grants.update({("partner_id", t.partner_id): set() for t in tenants if t.partner_id})
    for ap in db.scalars(select(AccountProduct)).all():
        key = owner.get(ap.account_id)
        if key in grants and billing.active_on(ap, today):
            grants[key] |= set(json.loads(prods[ap.product_id].modules or "[]"))
    for (col, oid), mods in grants.items():
        _cache[(col, oid, today)] = frozenset(mods)


def of_partner_set(p: Partner | None) -> frozenset:
    if p is None or not p.active:
        return frozenset()
    return _granted(object_session(p), "partner_id", p.id)


def of_tenant_set(t: Tenant | None) -> frozenset:
    if t is None:
        return frozenset()
    own = _granted(object_session(t), "tenant_id", t.id)
    # Selvbetjening kan også være slået til direkte (fra før pakkerne).
    if t.self_service:
        own = own | {"self_service"}
    return own | of_partner_set(t.partner)


def partner_has(p: Partner | None, m: str) -> bool:
    return m in of_partner_set(p)


def tenant_has(t: Tenant | None, m: str) -> bool:
    return m in of_tenant_set(t)


def owner_has(db, tenant_id: int | None, partner_id: int | None, m: str) -> bool:
    """Er modulet slået til for ejeren af et lokale eller køkken?"""
    if tenant_id is not None:
        return tenant_has(db.get(Tenant, tenant_id), m)
    return partner_has(db.get(Partner, partner_id) if partner_id else None, m)


def _off(m: str, who: str) -> HTTPException:
    return HTTPException(403, f"{NAMES[m]} er ikke slået til for {who}. Kontakt din leverandør for at komme i gang.")


def require_tenant(t: Tenant, m: str) -> None:
    if not tenant_has(t, m):
        raise _off(m, t.name)


def require_partner(p: Partner, m: str) -> None:
    if not partner_has(p, m):
        raise _off(m, p.name)


def of_tenant(t: Tenant) -> dict:
    """{"rooms": {"on": bool, "via": "house" | "firm" | ""}, ...} til admin."""
    house = of_partner_set(t.partner)
    firm = of_tenant_set(t)
    return {m: {"on": m in firm, "via": "house" if m in house else "firm" if m in firm else ""} for m in MODULES}


def of_partner(p: Partner) -> dict:
    mods = of_partner_set(p)
    return {m: {"on": m in mods, "via": "house" if m in mods else ""} for m in MODULES}
