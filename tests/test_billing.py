"""Pakker, tilkøb, rabatter og fakturagrundlag. Beregningerne testes med faste datoer langt ude i fremtiden."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import billing
from app.db import SessionLocal
from app.main import app
from app.models import BillingAccount, Notification


def test_month_fraction_and_periods():
    assert billing.month_fraction(date(2030, 11, 14), date(2030, 12, 1)) == pytest.approx(17 / 30)
    assert billing.month_fraction(date(2030, 12, 1), date(2031, 1, 1)) == 1
    assert billing.month_fraction(date(2030, 1, 15), date(2030, 3, 15)) == pytest.approx(17 / 31 + 1 + 14 / 31)
    assert billing.period_of(date(2030, 5, 20), "quarter") == (date(2030, 4, 1), date(2030, 7, 1))
    assert billing.period_of(date(2030, 5, 20), "year") == (date(2030, 1, 1), date(2031, 1, 1))
    assert billing.next_period(date(2030, 12, 20), "month") == (date(2031, 1, 1), date(2031, 2, 1))
    assert billing.kr(123456) == "1.234,56 kr." and billing.kr(-500) == "-5,00 kr."


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


@pytest.fixture()
def firm(plat):
    t = plat.post("/api/admin/tenants", json={"name": "Fakturafirma"}).json()
    yield t
    plat.delete(f"/api/admin/tenants/{t['id']}")


def acc_url(t, path=""):
    return f"/api/admin/billing/account{path}?tenant_id={t['id']}"


def run(plat, day: str):
    r = plat.post("/api/admin/billing/run", json={"period_start": day})
    assert r.status_code == 200, r.text
    return r.json()


def draft_for(plat, t, day):
    name = t["name"]
    return next(i for i in run(plat, day)["invoices"] if i["customer"] == name)


def amounts(inv):
    return {ln["description"].split(" ")[0]: ln["amount"] for ln in inv["lines"]}


def test_prorated_start_addon_credit_and_one_time_items(plat, firm):
    r = plat.post(acc_url(firm, "/subscriptions"), json={"product": "plus", "start": "2030-03-15"})
    assert r.status_code == 200, r.text
    inv = draft_for(plat, firm, "2030-04-01")
    # Plus fra 15.3 til 30.4: 17/31 + 1 måned forud.
    assert inv["lines"][0]["description"].startswith("Plus 15.3.2030–30.4.2030")
    assert inv["lines"][0]["amount"] == round(64900 * (17 / 31 + 1))
    assert inv["vat"] == round(inv["subtotal"] * 0.25) and inv["total"] == inv["subtotal"] + inv["vat"]
    # En ny kørsel laver kladden om i stedet for at lave en til.
    run(plat, "2030-04-01")
    drafts = [i for i in plat.get("/api/admin/billing/invoices?status=draft").json() if i["customer"] == firm["name"]]
    assert len(drafts) == 1
    fin = plat.post(f"/api/admin/billing/invoices/{drafts[0]['id']}/finalize").json()
    assert fin["status"] == "final" and fin["number"] >= 1001

    # Tilkøb midt i april med 50 % rabat, engangsposter og fast rabat på kunden.
    plat.post(acc_url(firm, "/subscriptions"), json={"product": "rooms", "start": "2030-04-10", "discount_pct": 50})
    plat.post(acc_url(firm, "/adjustments"), json={"product": "setup"})
    plat.post(acc_url(firm, "/adjustments"), json={"description": "Velkomstrabat", "amount": -500})
    plat.patch(acc_url(firm), json={"discount_pct": 10, "cvr": "12345678", "invoice_email": "bogholderi@firma.dk"})
    may = draft_for(plat, firm, "2030-05-01")
    a = amounts(may)
    assert a["Plus"] == 64900  # kun maj; april er betalt
    assert a["Mødelokaler"] == round(34900 * (21 / 30 + 1) * 0.5)  # 10.4–31.5 forud med 50 %
    assert a["Fast"] == -round((64900 + a["Mødelokaler"]) * 0.10)
    assert a["Opsætning"] == 149500 and a["Velkomstrabat"] == -50000
    plat.post(f"/api/admin/billing/invoices/{may['id']}/finalize")

    # Plus opsiges midt i maj, som allerede er betalt: resten krediteres. Engangsposter kommer ikke igen.
    acc = plat.get(acc_url(firm)).json()
    plus = next(s for s in acc["subscriptions"] if s["product"]["code"] == "plus")
    plat.post(f"/api/admin/billing/subscriptions/{plus['id']}/end", json={"end": "2030-05-15"})
    june = draft_for(plat, firm, "2030-06-01")
    a = amounts(june)
    assert a["Kreditering:"] == -round(64900 * 17 / 31)
    assert a["Mødelokaler"] == round(34900 * 0.5) and "Opsætning" not in a and "Velkomstrabat" not in a


def test_package_switch_and_yearly_billing(plat, firm):
    plat.patch(acc_url(firm), json={"interval": "year"})
    plat.post(acc_url(firm, "/subscriptions"), json={"product": "start", "start": "2031-01-01"})
    # Pakkeskift 1. juli: Start til 30.6, Komplet derefter.
    r = plat.post(acc_url(firm, "/subscriptions"), json={"product": "komplet", "start": "2031-07-01"})
    subs = {s["product"]["code"]: s for s in r.json()["subscriptions"]}
    assert subs["start"]["end"] == "2031-07-01" and subs["komplet"]["start"] == "2031-07-01"
    inv = draft_for(plat, firm, "2031-01-01")
    a = amounts(inv)
    assert a["Start"] == 34900 * 6 and a["Komplet"] == 119500 * 6
    assert a["Årsbetaling:"] == -round((34900 * 6 + 119500 * 6) * 2 / 12)
    # Husets pakke kan ikke sælges til et firma, og samme tilkøb kan ikke tilmeldes to gange.
    assert plat.post(acc_url(firm, "/subscriptions"), json={"product": "hus"}).status_code == 422
    plat.post(acc_url(firm, "/subscriptions"), json={"product": "catering", "start": "2031-02-01"})
    assert plat.post(acc_url(firm, "/subscriptions"), json={"product": "catering", "start": "2031-03-01"}).status_code == 409


def test_change_price_from_date_and_special_price(plat, firm):
    r = plat.post(acc_url(firm, "/subscriptions"), json={"product": "extra_screen", "start": "2032-01-01", "qty": 2,
                                                         "price": 79})
    s = r.json()["subscriptions"][0]
    assert s["unit_price"] == 7900 and s["monthly"] == 15800
    r = plat.post(f"/api/admin/billing/subscriptions/{s['id']}/change", json={"start": "2032-01-16", "qty": 3})
    subs = r.json()["subscriptions"]
    assert [(x["qty"], x["start"], x["end"]) for x in subs] == [(2, "2032-01-01", "2032-01-16"), (3, "2032-01-16", None)]
    inv = draft_for(plat, firm, "2032-01-01")
    assert [ln["amount"] for ln in inv["lines"]] == [round(15800 * 15 / 31), round(23700 * 16 / 31)]


def test_sms_overage_billed_in_arrears(plat, firm):
    plat.post(acc_url(firm, "/subscriptions"), json={"product": "start", "start": "2033-01-01"})
    with SessionLocal() as db:
        acc = db.query(BillingAccount).filter(BillingAccount.tenant_id == firm["id"]).one()
        acc.usage_billed_through = date(2033, 1, 1)
        for i in range(130):  # 130 SMS i januar, 100 er med i Start
            db.add(Notification(tenant_id=firm["id"], channel="sms", recipient="1", status="sendt",
                                created_at=__import__("datetime").datetime(2033, 1, 10, 12, 0)))
        db.add(Notification(tenant_id=firm["id"], channel="sms", recipient="1", status="test",
                            created_at=__import__("datetime").datetime(2033, 1, 11)))  # tæller ikke
        db.commit()
    inv = draft_for(plat, firm, "2033-02-01")
    sms = next(ln for ln in inv["lines"] if ln["kind"] == "usage")
    assert sms["qty"] == 30 and sms["amount"] == 30 * 39 and "130 sendt, 100 inkluderet" in sms["description"]


def test_catalog_prices_and_csv(plat, firm):
    prods = plat.get("/api/admin/billing/products").json()
    plus = next(p for p in prods if p["code"] == "plus")
    assert plus["price"] == 64900 and plus["kind"] == "package" and "reports" in plus["modules"]
    r = plat.patch(f"/api/admin/billing/products/{plus['id']}", json={"price": 699, "features": ["A", " ", "B"]})
    assert r.json()["price"] == 69900 and r.json()["features"] == ["A", "B"]
    plat.patch(f"/api/admin/billing/products/{plus['id']}", json={"price": 649, "features": plus["features"]})
    plat.patch(acc_url(firm), json={"cvr": "87654321"})
    plat.post(acc_url(firm, "/subscriptions"), json={"product": "start", "start": "2034-01-01"})
    inv = draft_for(plat, firm, "2034-01-01")
    plat.post(f"/api/admin/billing/invoices/{inv['id']}/finalize")
    assert plat.post(f"/api/admin/billing/invoices/{inv['id']}/finalize").status_code == 409
    assert plat.delete(f"/api/admin/billing/invoices/{inv['id']}").status_code == 409
    csv = plat.get("/api/admin/billing/invoices.csv").text
    assert "Fakturafirma" in csv and "87654321" in csv and "349,00" in csv
    assert plat.post(f"/api/admin/billing/invoices/{inv['id']}/paid").json()["status"] == "paid"
