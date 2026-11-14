"""Databehandleraftale (accept ved første login) og gæsternes privatlivsside."""
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import legal
from .auth import Principal, current
from .config import settings
from .db import get_db
from .models import Tenant, utcnow

admin = APIRouter(prefix="/api/admin/dpa", tags=["jura"], dependencies=[Depends(current)])
public = APIRouter(tags=["jura"])

PAGE = """<!doctype html><html lang="da"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{title}</title><style>
body{{margin:0;background:#f4f5f2;color:#14171d;font:16px/1.55 "Hanken Grotesk",system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:760px;margin:0 auto;padding:32px 20px 60px;background:#fff;min-height:100vh}}
h1{{font:800 2rem/1.1 "Bricolage Grotesque",system-ui,sans-serif;margin:0 0 4px}} h2{{font-size:1.1rem;margin:28px 0 6px}}
.meta{{color:#5d6470;margin:0 0 20px}} .udkast{{background:#fff4dd;border:1px solid #f0dfb8;border-radius:10px;padding:10px 14px;font-weight:700}}
.lang{{float:right}} .lang a{{color:#12352e;font-weight:700;margin-left:10px}} li{{margin:4px 0}}
@media print{{body{{background:#fff}} main{{padding:0}} .lang{{display:none}}}}
</style></head><body><main>{body}</main></body></html>"""


class AcceptIn(BaseModel):
    version: str = Field(max_length=40)


@public.get("/databehandleraftale", response_class=HTMLResponse, include_in_schema=False)
def dpa_page():
    return HTMLResponse(PAGE.format(title="Databehandleraftale", body=legal.dpa_html()))


@admin.get("")
def dpa(db: Session = Depends(get_db), p: Principal = Depends(current)):
    org = legal.org_of(db, p)
    return {"required": legal.required(db, p), "version": legal.version(), "final": settings.dpa_final,
            "org_name": org.name if org else "", "org_kind": "hus" if org is not None and not isinstance(org, Tenant) else "firma",
            "html": legal.dpa_html(org.name if org else ""), **({"status": legal.status(org)} if org else {})}


@admin.post("/accept")
def accept(body: AcceptIn, db: Session = Depends(get_db), p: Principal = Depends(current)):
    org = legal.org_of(db, p)
    if org is None:
        raise HTTPException(422, "Leverandøren accepterer ikke sin egen databehandleraftale")
    if body.version != legal.version():
        raise HTTPException(409, "Aftalen er blevet opdateret. Genindlæs siden og læs den nye version")
    org.dpa_version, org.dpa_accepted_at = body.version, utcnow()
    org.dpa_accepted_by = ((p.user.name + " ") if p.user and p.user.name else "") + (f"<{p.user.email}>" if p.user else "")
    db.commit()
    return {"ok": True, "status": legal.status(org)}


# ---------- gæsternes privatlivsside ----------

PRIVACY_DA = """<p class="lang"><a href="?lang=en">English</a></p>
<h1>Sådan behandler vi dine oplysninger</h1><p class="meta">{firm}</p>
<p>Når du tjekker ind på skærmen hos <b>{firm}</b>, registrerer vi dit navn{phone}{company}, hvem du besøger, og hvornår du
kommer og går.</p>
<h2>Hvorfor</h2><p>For at give den, du besøger, besked om, at du er kommet, og for at vide, hvem der er i huset, hvis
bygningen skal evakueres. Grundlaget er {firm_gen} legitime interesse i sikkerhed og en god modtagelse
(GDPR art. 6, stk. 1, litra f). Har du accepteret husregler, gemmes det også.</p>
<h2>Hvem ser det</h2><p>Den, du besøger, får dit navn{phone_short} på SMS, e-mail eller Teams. Receptionen og
administratorerne hos {firm} kan se besøget. {operator} driver løsningen som databehandler for {firm}.</p>
<h2>Hvor længe</h2><p>Besøget slettes automatisk efter {days} dage. Derefter gemmes kun et antal (fx "120 gæster i
november") uden navne.</p>
<h2>Dine rettigheder</h2><p>Du kan bede om indsigt i, rettelse eller sletning af dine oplysninger. Kontakt
{contact}. Du kan klage til Datatilsynet (datatilsynet.dk).</p>"""

PRIVACY_EN = """<p class="lang"><a href="?lang=da">Dansk</a></p>
<h1>How we handle your information</h1><p class="meta">{firm}</p>
<p>When you check in at <b>{firm}</b>, we record your name{phone}{company}, who you are visiting, and when you arrive
and leave.</p>
<h2>Why</h2><p>To let your host know you have arrived, and to know who is in the building if it has to be evacuated.
The legal basis is {firm}'s legitimate interest in safety and a good reception (GDPR art. 6(1)(f)). If you accept
house rules, that is recorded too.</p>
<h2>Who sees it</h2><p>Your host receives your name{phone_short} by text message, e-mail or Teams. The reception and
the administrators at {firm} can see the visit. {operator} runs the solution as a data processor for {firm}.</p>
<h2>How long</h2><p>The visit is deleted automatically after {days} days. After that only a count (e.g. "120 guests in
November") is kept, without names.</p>
<h2>Your rights</h2><p>You can ask for access to, correction or deletion of your information. Contact {contact}.
You can complain to the Danish Data Protection Agency (datatilsynet.dk).</p>"""


@public.get("/privatliv/{token}", response_class=HTMLResponse, include_in_schema=False)
def privacy(token: str, lang: str = "da", db: Session = Depends(get_db)):
    """Gæsternes privatlivsside for en skærm (link fra skærmen, QR-plakaten og gæstens side)."""
    import html as h
    t = db.scalar(select(Tenant).where(Tenant.kiosk_token == token))
    if t is None:
        raise HTTPException(404, "Siden findes ikke")
    en = lang == "en"
    contact = " / ".join(h.escape(x) for x in (t.reception_email, t.reception_phone) if x) or \
        (f"the reception at {h.escape(t.name)}" if en else f"receptionen hos {h.escape(t.name)}")
    op = h.escape(settings.operator_name) if settings.operator_name else ("The provider of the screen solution" if en else "Leverandøren af skærmløsningen")
    ask_phone, ask_company = t.ask_phone, t.ask_company
    body = (PRIVACY_EN if en else PRIVACY_DA).format(
        firm=h.escape(t.name), firm_gen=h.escape(t.name) + ("'" if t.name.rstrip()[-1:].lower() in "sxz" else "s"), days=t.retention_days, contact=contact, operator=op,
        phone=(", mobile number" if en else ", dit mobilnummer") if ask_phone else "",
        phone_short=(" and mobile number" if en else " og mobilnummer") if ask_phone else "",
        company=(", company" if en else ", firma") if ask_company else "")
    return HTMLResponse(PAGE.format(title="Privacy" if en else "Privatliv", body=body))
