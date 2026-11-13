"""Creates one fictional demo customer on first start so the kiosk has something to show."""
import io
import uuid

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .media import storage
from .models import Host, Tenant

DEMO_LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 90">
<path d="M10 66q14-16 28 0t28 0" stroke="#2a5bd7" stroke-width="8" fill="none" stroke-linecap="round"/>
<path d="M10 44q14-16 28 0t28 0" stroke="#2a5bd7" stroke-width="8" fill="none" stroke-linecap="round" opacity=".45"/>
<text x="84" y="46" font-family="Helvetica,Arial,sans-serif" font-weight="800" font-size="30" letter-spacing="2" fill="#14171f">HAVNENS</text>
<text x="84" y="74" font-family="Georgia,serif" font-style="italic" font-size="23" fill="#2a5bd7">Rådgivning</text></svg>"""

PEOPLE = [
    ("Anne Kjær", "Partner", "anne@example.com", "+45 20 00 00 01", ("#c7d2fe", "#3730a3")),
    ("Mikkel Holm", "Økonomichef", "mikkel@example.com", "+45 20 00 00 02", ("#bbf7d0", "#166534")),
    ("Sofie Lund", "HR", "sofie@example.com", "", ("#fecdd3", "#9f1239")),
    ("Jonas Bach", "Rådgiver", "jonas@example.com", "+45 20 00 00 04", ("#fde68a", "#92400e")),
    ("Line Vestergaard", "Rådgiver", "", "+45 20 00 00 05", ("#bae6fd", "#075985")),
    ("Thomas Berg", "IT", "thomas@example.com", "+45 20 00 00 06", ("#e9d5ff", "#6b21a8")),
]


def _placeholder_portrait(name: str, bg: str, fg: str) -> str:
    """Simple illustrated placeholder (not a real person). Replace with real photos in admin."""
    s = 600
    img = Image.new("RGB", (s, s), bg)
    d = ImageDraw.Draw(img)
    d.ellipse((s * .30, s * .16, s * .70, s * .56), fill=fg)          # head
    d.ellipse((s * .10, s * .60, s * .90, s * 1.30), fill=fg)         # shoulders
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
    except OSError:
        font = ImageFont.load_default()
    initials = "".join(w[0] for w in name.split())[:2]
    d.text((s / 2, s * .36), initials, fill=bg, font=font, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    fname = f"{uuid.uuid4().hex}.jpg"
    storage.save(fname, buf.getvalue())
    return fname


def seed_if_empty(db: Session) -> None:
    if not settings.seed_demo or db.scalar(select(Tenant.id).limit(1)) is not None:
        return
    logo = f"{uuid.uuid4().hex}.svg"
    storage.save(logo, DEMO_LOGO.encode("utf-8"))
    t = Tenant(name="Havnens Rådgivning (demo)", color="#2a5bd7", logo_path=logo,
               welcome_text="Velkommen til Havnens Rådgivning", sms_sender="Havnen", kiosk_token="demo")
    db.add(t)
    db.flush()
    for i, (name, title, email, phone, (bg, fg)) in enumerate(PEOPLE):
        db.add(Host(tenant_id=t.id, name=name, title=title, email=email, phone=phone, sort_order=i,
                    notify_sms=bool(phone), notify_email=bool(email),
                    photo_path=_placeholder_portrait(name, bg, fg)))
    t.reception_email = "reception@example.com"
    db.commit()
