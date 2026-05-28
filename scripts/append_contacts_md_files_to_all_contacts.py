#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scrape_site_contacts_rows import ContactRow, append_to_contacts  # noqa: E402

_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _find_col(headers: list[str], candidates: tuple[str, ...]) -> int:
    lowered = [h.casefold() for h in headers]
    for cand in candidates:
        c = cand.casefold()
        for i, h in enumerate(lowered):
            if c == h or c in h:
                return i
    return -1


def read_contacts_md(path: Path) -> list[tuple[str, str, ContactRow]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    header_i = -1
    for i, ln in enumerate(lines):
        if ln.startswith("|") and "Организация" in ln and "Вид контакта" in ln and "Контакт" in ln:
            if i + 1 < len(lines) and _SEP_RE.match(lines[i + 1]):
                header_i = i
                break
    if header_i < 0:
        raise SystemExit(f"No contacts table found in {path}")

    headers = _split_cells(lines[header_i])
    org_col = _find_col(headers, ("организация", "org"))
    site_col = _find_col(headers, ("сайт", "site", "website"))
    kind_col = _find_col(headers, ("вид контакта", "type", "kind"))
    value_col = _find_col(headers, ("контакт", "value"))
    desc_col = _find_col(headers, ("описание", "desc", "description"))

    if min(org_col, site_col, kind_col, value_col) < 0:
        raise SystemExit(f"Missing required columns in {path}")

    out: list[tuple[str, str, ContactRow]] = []
    for ln in lines[header_i + 2 :]:
        if not ln.startswith("|"):
            break
        if ln.lstrip().startswith("|---"):
            continue
        cells = _split_cells(ln)
        if len(cells) <= max(org_col, site_col, kind_col, value_col, desc_col):
            continue
        org = cells[org_col].strip()
        site = cells[site_col].strip()
        kind = cells[kind_col].strip()
        value = cells[value_col].strip()
        desc = (cells[desc_col].strip() if desc_col >= 0 else "N/A") or "N/A"
        if not (org and site and kind and value):
            continue
        out.append((org, site, ContactRow(kind=kind, value=value, desc=desc)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Append contacts from md files into all/all_contacts.md (dedup)")
    ap.add_argument("--all-contacts", default="all/all_contacts.md")
    ap.add_argument("inputs", nargs="+", help="One or more contacts md files")
    args = ap.parse_args()

    all_contacts = ROOT / args.all_contacts
    total_in = 0
    total_added = 0

    for p in args.inputs:
        path = Path(p)
        if not path.is_absolute():
            path = ROOT / path
        rows = read_contacts_md(path)
        total_in += len(rows)
        total_added += append_to_contacts(all_contacts, rows)

    print(f"Inputs rows: {total_in}; added to {all_contacts}: {total_added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

