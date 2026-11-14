"""Kopiér de billeder, der allerede ligger som filer (DATA_DIR/media), op i Azure Blob Storage.

Nemmest: knappen "Kopiér billeder til Blob" under Fakturering > Klar til prod i admin. Eller lokalt med prod-indstillinger:
  python tools/media_til_blob.py
Billeder, der allerede findes i Blob, springes over. Filerne på disken bliver liggende som lokal kopi.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ops import copy_media_to_blob  # noqa: E402


def main() -> None:
    r = copy_media_to_blob()
    print(r["message"])
    if not r["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
