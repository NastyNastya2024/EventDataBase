#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scrape_site_contacts_rows import ContactRow, append_to_contacts  # noqa: E402


def _norm_url(s: str) -> str:
    s = (s or "").strip()
    if not s or s in {"—", "N/A"}:
        return ""
    if s.startswith("//"):
        s = "https:" + s
    if re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/.*)?", s) and not s.startswith(("http://", "https://")):
        s = "https://" + s
    if not s.startswith(("http://", "https://")):
        return ""
    return s.rstrip("/")


def _clean_phone(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    if len(digits) < 10 or len(digits) > 15:
        return ""
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("7"):
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    return "+" + digits


def _clean_email(raw: str) -> str:
    e = (raw or "").strip().strip("<>").casefold()
    if not e or "@" not in e:
        return ""
    if len(e) > 120:
        return ""
    return e


def _social_desc(url: str) -> str:
    try:
        host = urlparse(url).netloc.casefold()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host or "social"


def main() -> int:
    ap = argparse.ArgumentParser(description="Import novikovgroup_contacts.csv into all/all_contacts.md")
    ap.add_argument("--input", default="data/restaurants/novikovgroup_contacts.csv")
    ap.add_argument("--all-contacts", default="all/all_contacts.md")
    ap.add_argument("--org-name", default="Novikov Group")
    args = ap.parse_args()

    in_path = ROOT / args.input
    out_path = ROOT / args.all_contacts

    if not in_path.exists():
        raise SystemExit(f"Missing: {in_path}")

    rows_to_add: list[tuple[str, str, ContactRow]] = []

    with in_path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            dept = (r.get("department") or "").strip()
            contact_name = (r.get("contact_name") or "").strip()
            phone = _clean_phone(r.get("phone") or "")
            email = _clean_email(r.get("email") or "")
            source_url = _norm_url(r.get("source_url") or "") or "N/A"
            notes = (r.get("notes") or "").strip()

            desc_bits = [b for b in (dept, contact_name, notes) if b]
            desc = " — ".join(desc_bits) if desc_bits else "N/A"

            if phone:
                rows_to_add.append((args.org_name, source_url, ContactRow("phone", phone, desc)))
            if email:
                rows_to_add.append((args.org_name, source_url, ContactRow("email", email, desc)))

            # socials are stored in email field for section=social in this csv
            maybe_url = _norm_url(r.get("email") or "")
            if maybe_url:
                rows_to_add.append(
                    (args.org_name, source_url, ContactRow("social", maybe_url, _social_desc(maybe_url)))
                )

    added = append_to_contacts(out_path, rows_to_add)
    print(f"Imported rows: {len(rows_to_add)}; added to {out_path}: {added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

