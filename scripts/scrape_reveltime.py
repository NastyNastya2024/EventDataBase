#!/usr/bin/env python3
"""Парсинг лофтов Москвы (вечеринка) с https://www.reveltime.ru/"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "лофтв"
CACHE_PATH = ROOT / "scripts" / ".cache" / "reveltime_venues.json"
LIST_URL = "https://www.reveltime.ru/list/loft/vecherinka/moscow"
EVENT_QUERY = "eventtype=vecherinka"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

COLUMNS = ["название", "тип_лофт", "телефон", "сайт", "ссылка"]

# Телефоны поддержки Revel Time (не площадки)
_SUPPORT_PHONES = frozenset(
    {
        "+79637636633",
        "+78005119343",
        "+74959781642",
        "+74992261382",
        "+79910180824",  # общий WhatsApp/бронь Revel Time
        "+79910172713",
        "+79910174518",
    }
)

_SKIP_SITE_HOSTS = (
    "reveltime.ru",
    "storage.reveltime.ru",
    "reveltime.storage.yandexcloud.net",
    "wa.me",
    "t.me",
    "telegram",
    "whatsapp",
    "api.whatsapp",
    "vk.com",
    "instagram.com",
    "facebook.com",
    "google",
    "yandex",
    "metrika",
    "speedrent",
    "youtube.com",
    "youtu.be",
)


def fetch(url: str, timeout: float = 40) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        },
    )
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def _norm_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("7"):
        return "+" + digits
    return (raw or "").strip()


def _is_support_phone(phone: str) -> bool:
    return _norm_phone(phone) in _SUPPORT_PHONES


def _is_valid_external(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
    except ValueError:
        return False
    if not host or "." not in host:
        return False
    low = url.lower()
    return not any(h in low for h in _SKIP_SITE_HOSTS)


def parse_list_cards(html: str) -> dict[str, dict[str, str]]:
    cards: dict[str, dict[str, str]] = {}
    for m in re.finditer(
        r'<div class="card"\s+[^>]*data-\s*name="([^"]*)"[^>]*data-\s*id="(\d+)"',
        html,
    ):
        vid = m.group(2)
        block = html[m.start() : m.start() + 12000]
        title_m = re.search(
            r'class="card-title-link[^"]*"[^>]*>\s*([^<]+)',
            block,
            re.S,
        )
        addr_m = re.search(r'class="card-address"[^>]*>\s*([^<]+)', block, re.S)
        metro = ""
        if addr_m:
            metro = re.sub(r"\s+", " ", addr_m.group(1)).strip()
            metro = re.sub(r"\(\d+мин\.?\)", "", metro).strip()

        area = ""
        cap = ""
        opt_m = re.search(r'class="card-options"[^>]*>(.*?)</div>\s*</div>', block, re.S)
        if opt_m:
            opts = opt_m.group(1)
            sq = re.search(r"(\d+)\s*м\s*<", opts, re.I)
            if sq:
                area = sq.group(1) + " м²"
            cap = re.search(r"(\d+)\s*человек", opts, re.I)
            cap = cap.group(0) if cap else ""

        loft_type = "Лофт, вечеринка"
        if area or cap:
            parts = [loft_type]
            if area:
                parts.append(area)
            if cap:
                parts.append(cap)
            loft_type = ", ".join(parts)

        name = title_m.group(1).strip() if title_m else m.group(1).strip()
        cards[vid] = {
            "id": vid,
            "название": name,
            "тип_лофт": loft_type,
            "телефон": "",
            "сайт": "N/A",
            "ссылка": f"https://www.reveltime.ru/venue/{vid}?{EVENT_QUERY}",
            "metro": metro,
        }
    return cards


def collect_listing_urls() -> dict[str, dict[str, str]]:
    html = fetch(LIST_URL)
    pages = sorted({int(x) for x in re.findall(r'\?page=(\d+)"', html)})
    max_page = max(pages) if pages else 1

    all_cards = parse_list_cards(html)
    for page in range(2, max_page + 1):
        time.sleep(0.2)
        chunk = fetch(f"{LIST_URL}?page={page}")
        all_cards.update(parse_list_cards(chunk))
    return all_cards


def parse_detail(url: str, html: str) -> tuple[str, str]:
    phone = ""
    candidates: list[str] = []
    m = re.search(r'itemprop="telephone"\s+content="([^"]+)"', html, re.I)
    if m:
        candidates.append(_norm_phone(m.group(1)))
    for tel in re.findall(r'class="contact-preview"[^>]*href="tel:([^"]+)"', html):
        candidates.append(_norm_phone(tel))
    for tel in re.findall(r'href="tel:([^"]+)"', html):
        candidates.append(_norm_phone(tel))
    for p in candidates:
        if p and not _is_support_phone(p):
            phone = p
            break

    site = "N/A"
    for u in re.findall(r'href="(https?://[^"]+)"', html):
        if _is_valid_external(u):
            site = u.split("?")[0].rstrip("/")
            break

    # уточнить название из h1
    title = ""
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
    if h1:
        title = re.sub(r"<[^>]+>", "", h1.group(1)).strip()
        title = title.split("|")[0].strip()

    return phone, site, title


def scrape_detail(row: dict[str, str], delay: float) -> dict[str, str]:
    if delay:
        time.sleep(delay)
    vid = row["id"]
    url = row["ссылка"]
    html = fetch(url)
    phone, site, title = parse_detail(url, html)
    if phone:
        row["телефон"] = phone
    if site != "N/A":
        row["сайт"] = site
    if title:
        row["название"] = title
    return row


def load_cache() -> dict[str, dict[str, str]]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_cache(data: dict[str, dict[str, str]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_outputs(rows: list[dict[str, str]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "reveltime_moscow_vecherinka.csv"
    md_path = OUT_DIR / "reveltime_moscow_vecherinka.md"

    out_rows = [{c: r.get(c, "") for c in COLUMNS} for r in rows]

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
        w.writeheader()
        w.writerows(out_rows)

    lines = [
        "## Лофты Москвы (вечеринка) — reveltime.ru",
        "",
        f"Источник: [{LIST_URL}]({LIST_URL})",
        "",
        f"Всего: **{len(out_rows)}**.",
        "",
        "| № | " + " | ".join(COLUMNS) + " |",
        "|---:|" + "|".join(["---"] * len(COLUMNS)) + "|",
    ]
    for i, row in enumerate(out_rows, 1):
        cells = [str(i)] + [row[c].replace("|", "\\|") for c in COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {csv_path} ({len(out_rows)} rows)")
    print(f"wrote {md_path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--delay", type=float, default=0.12)
    parser.add_argument("--list-only", action="store_true", help="без карточек площадок")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    cache = {} if args.refresh else load_cache()
    listing = collect_listing_urls()
    print(f"listing: {len(listing)} venues")

    for vid, row in listing.items():
        if vid not in cache:
            cache[vid] = row
        else:
            for k in ("название", "тип_лофт", "ссылка"):
                if row.get(k):
                    cache[vid][k] = row[k]

    if not args.list_only:
        todo = [cache[vid] for vid in listing if not cache[vid].get("телефон")]
        print(f"details to fetch: {len(todo)} (cached phones: {len(listing) - len(todo)})")
        if todo:
            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
                futures = {
                    pool.submit(scrape_detail, row, args.delay): row["id"]
                    for row in todo
                }
                done = 0
                for fut in as_completed(futures):
                    vid = futures[fut]
                    try:
                        cache[vid] = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        print(f"  fail {vid}: {exc}", file=sys.stderr)
                    done += 1
                    if done % 50 == 0 or done == len(todo):
                        save_cache(cache)
                        print(f"details {done}/{len(todo)}", flush=True)
            save_cache(cache)

    rows = [cache[vid] for vid in sorted(listing, key=lambda x: listing[x]["название"].lower())]
    write_outputs(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
