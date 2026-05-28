#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from urllib.parse import urlparse

from scrape_site_contacts_rows import ContactRow, append_to_contacts  # type: ignore

ROOT = Path(__file__).resolve().parents[1]


def _clean_url(s: str) -> str:
    s = (s or "").strip()
    if not s or s in {"—", "N/A"}:
        return ""
    if s.startswith("//"):
        s = "https:" + s
    if re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/.*)?", s) and not s.startswith(("http://", "https://")):
        s = "https://" + s
    if not s.startswith(("http://", "https://")):
        return ""
    return s


def _desc_from_url(u: str) -> str:
    try:
        host = urlparse(u).netloc.casefold()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host or "social"


def _iter_csv_rows(path: Path):
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        except Exception:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        for row in reader:
            if row:
                yield {k.strip(): (v or "").strip() for k, v in row.items() if k}


def import_pr_agencies(csv_path: Path) -> list[tuple[str, str, ContactRow]]:
    out: list[tuple[str, str, ContactRow]] = []
    for r in _iter_csv_rows(csv_path):
        name = r.get("company_name", "") or r.get("Компания", "") or r.get("Компания ", "")
        site = _clean_url(r.get("website", "") or r.get("Сайт", ""))
        phone = (r.get("phone", "") or r.get("Телефон", "")).strip()
        if not name:
            continue
        base_site = site or "N/A"
        if phone:
            out.append((name, base_site, ContactRow("phone", phone, "pr_agencies_contacts")))
        # PR table doesn't have emails/socials, so only phone here.
    return out


def import_top100(csv_path: Path) -> list[tuple[str, str, ContactRow]]:
    out: list[tuple[str, str, ContactRow]] = []
    for r in _iter_csv_rows(csv_path):
        name = r.get("agency_name", "") or r.get("Агентство", "") or r.get("agency", "")
        site = _clean_url(r.get("website", "") or r.get("Сайт", ""))
        agency_url = _clean_url(r.get("agency_url", "") or "")
        source_url = _clean_url(r.get("source_url", "") or "")
        base_site = site or agency_url or source_url or "N/A"

        if not name:
            continue

        phone = (r.get("phone", "") or r.get("Телефон", "")).strip()
        email = (r.get("email", "") or r.get("Email", "")).strip()

        if phone:
            out.append((name, base_site, ContactRow("phone", phone, "top100awards")))
        if email:
            out.append((name, base_site, ContactRow("email", email, "top100awards")))

        for key in ("instagram", "telegram", "whatsapp", "vk", "other_contacts"):
            u = _clean_url(r.get(key, ""))
            if not u:
                continue
            out.append((name, base_site, ContactRow("social", u, _desc_from_url(u))))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Import agency contacts into all/all_contacts.md")
    ap.add_argument("--all-contacts", default="all/all_contacts.md")
    ap.add_argument("--pr", default="data/agencies/pr_agencies_contacts.csv")
    ap.add_argument("--top100", default="data/agencies/top100awards_agencies_moscow_2026.csv")
    args = ap.parse_args()

    all_contacts = ROOT / args.all_contacts
    pr_csv = ROOT / args.pr
    top_csv = ROOT / args.top100

    new_rows: list[tuple[str, str, ContactRow]] = []
    if pr_csv.exists():
        new_rows.extend(import_pr_agencies(pr_csv))
    if top_csv.exists():
        new_rows.extend(import_top100(top_csv))

    added = append_to_contacts(all_contacts, new_rows)
    print(f"Imported rows: {len(new_rows)}; added to {all_contacts}: {added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

