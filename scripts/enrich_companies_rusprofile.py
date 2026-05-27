#!/usr/bin/env python3
"""
Enrich Kontur Focus Moscow companies list with website/phone by scraping Rusprofile.

Inputs:
  data/organizations/kontur_focus_moscow_popular_companies.csv

Outputs:
  Updates same CSV with columns:
    website, phone, contact_source_url, enriched_batch
  Rewrites:
    data/organizations/kontur_focus_moscow_popular_companies.md

Strategy:
  - Map company_name -> OGRN via focus.kontur.ru list HTML (/tmp/kontur_moskva.html) entity links.
  - For each company with missing website+phone, request:
      https://www.rusprofile.ru/search?query=<OGRN>&type=ul
    (this often returns the company page directly)
  - Parse "Сайт" and first tel: link as phone.
"""

from __future__ import annotations

import csv
import html as htmlmod
import re
import time
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "organizations" / "kontur_focus_moscow_popular_companies.csv"
MD_PATH = ROOT / "data" / "organizations" / "kontur_focus_moscow_popular_companies.md"

KONTUR_LIST_HTML = Path("/tmp/kontur_moskva.html")  # created earlier via curl


def build_name_to_ogrn() -> dict[str, str]:
    if not KONTUR_LIST_HTML.exists():
        raise FileNotFoundError(f"Missing {KONTUR_LIST_HTML}. Re-fetch Kontur list page first.")
    html = KONTUR_LIST_HTML.read_text(encoding="utf-8", errors="ignore")
    pairs: list[tuple[str, str]] = []
    # anchor text spans multiple lines; collapse whitespace
    for m in re.finditer(
        r'href="/entity\?query=(\d{10,15})"[^>]*>\s*([^<]+?)\s*</a>',
        html,
        re.S,
    ):
        ogrn = m.group(1)
        text = re.sub(r"\s+", " ", m.group(2)).strip()
        pairs.append((htmlmod.unescape(text), ogrn))
    return {name: ogrn for name, ogrn in pairs}


def parse_rusprofile_contacts(page_html: str) -> tuple[str, str]:
    website = ""
    phone = ""

    m = re.search(r'Сайт\s*</span>\s*<[^>]*>\s*<a[^>]*href="(https?://[^"]+)"', page_html)
    if m:
        website = m.group(1).strip()

    m = re.search(r'href="tel:([+0-9]+)"[^>]*>\s*([^<]+)\s*</a>', page_html)
    if m:
        phone = m.group(2).strip()

    return website, phone


def rewrite_md(rows: list[dict[str, str]]) -> None:
    md: list[str] = []
    md.append("## Kontur Focus — популярные компании (Москва)\n")
    md.append("Источник: `https://focus.kontur.ru/site/populyarnye-kompanii-v-focuse/moskva`\n\n")
    md.append("Колонки `website/phone` заполняются партиями по 100.\n\n")
    md.append(f"Всего названий: **{len(rows)}**\n\n")
    md.append("| № | Компания | Сайт | Телефон | Источник контакта |\n")
    md.append("|---:|---|---|---|---|\n")
    for row in rows:
        i = row["id"]
        name = row["company_name"]
        web = (row.get("website") or "").strip()
        phone = (row.get("phone") or "").strip()
        src = (row.get("contact_source_url") or "").strip()
        web_md = f"[{web}]({web})" if web else ""
        src_md = f"[{src}]({src})" if src else ""
        md.append(f"| {i} | {name} | {web_md} | {phone} | {src_md} |\n")
    MD_PATH.write_text("".join(md), encoding="utf-8")


def main(batch_size: int = 100, delay_s: float = 0.35) -> None:
    name_to_ogrn = build_name_to_ogrn()

    rows: list[dict[str, str]] = []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f, delimiter=";")
        fieldnames = list(r.fieldnames or [])
        for row in r:
            rows.append(row)

    for col in ["website", "phone", "contact_source_url", "enriched_batch"]:
        if col not in fieldnames:
            fieldnames.append(col)

    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0"})

    # Determine next batch number
    max_batch = 0
    for row in rows:
        b = (row.get("enriched_batch") or "").strip()
        if b.isdigit():
            max_batch = max(max_batch, int(b))
    batch_num = max_batch + 1

    updated = 0
    for row in rows:
        if updated >= batch_size:
            break
        if (row.get("website") or "").strip() and (row.get("phone") or "").strip():
            continue
        ogrn = name_to_ogrn.get(row["company_name"])
        if not ogrn:
            continue
        url = f"https://www.rusprofile.ru/search?query={ogrn}&type=ul"
        try:
            resp = sess.get(url, timeout=25, allow_redirects=True)
            html = resp.text
        except Exception:
            continue

        website, phone = parse_rusprofile_contacts(html)
        if not website and not phone:
            continue

        if website:
            row["website"] = website
        if phone:
            row["phone"] = phone
        row["contact_source_url"] = resp.url
        row["enriched_batch"] = str(batch_num)
        updated += 1
        time.sleep(delay_s)

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        w.writeheader()
        w.writerows(rows)

    rewrite_md(rows)
    print(f"batch {batch_num}: updated {updated} rows")


if __name__ == "__main__":
    main()

