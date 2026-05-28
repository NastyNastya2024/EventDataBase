#!/usr/bin/env python3
"""Парсинг ресторанов Москвы с https://greatlist.ru/msk/"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "restaurants"
CACHE_PATH = ROOT / "scripts" / ".cache" / "greatlist_moscow.json"
SITEMAP_URL = "https://greatlist.ru/restaurant-sitemap.xml"
SOURCE_URL = "https://greatlist.ru/msk/"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

COLUMNS = ["name", "website", "phone", "greatlist_url", "notes"]

_SKIP_SITE_HOSTS = (
    "greatlist.",
    "google",
    "facebook.com",
    "yandex.",
    "gmpg.org",
    "deluxe-interactive.com",
    "weinberg.digital",
    "alfabank.ru",
    "netmonet.co",
    "open.spotify.com",
    "googletagmanager.com",
)

_NAME_PREFIX_RE = re.compile(
    r"^(Ресторан|Бар|Кофейня|Кафе|Гостиница|Restaurant)\s+",
    re.I,
)
_BREADCRUMB_CAT_RE = re.compile(
    r'"@type"\s*:\s*"ListItem"[^}]*"position"\s*:\s*2[^}]*"name"\s*:\s*"([^"]+)"',
    re.S,
)
_BREADCRUMB_NAME_RE = re.compile(
    r'"@type"\s*:\s*"ListItem"[^}]*"position"\s*:\s*3[^}]*"name"\s*:\s*"([^"]+)"',
    re.S,
)
_PARTNER_SITE_RE = re.compile(
    r'href="(https?://[^"]+utm_source=greatlist[^"]*)"',
    re.I,
)
_TEL_RE = re.compile(r'href="tel:([^"]+)"', re.I)
_CANDIDATE_RE = re.compile(r'class="label-new"\s*>\s*Кандидат\s*<', re.I)


def fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_sitemap_urls() -> list[str]:
    xml = fetch(SITEMAP_URL, timeout=60)
    urls = sorted(
        {
            u.rstrip("/") + "/"
            for u in re.findall(r"<loc>([^<]+)</loc>", xml)
            if re.match(r"https://greatlist\.ru/msk/restaurant/", u)
        }
    )
    if not urls:
        raise RuntimeError("No Moscow restaurant URLs in sitemap")
    return urls


def _clean_name(raw: str) -> str:
    name = _NAME_PREFIX_RE.sub("", raw.strip())
    return re.sub(r"\s+", " ", name).strip()


def _pick_site(html: str) -> str:
    m = _PARTNER_SITE_RE.search(html)
    if m:
        return m.group(1).strip()
    for pat in (
        r'href="(https://alfa\.me/[^"]+)"',
        r'href="(https?://(?:www\.)?instagram\.com/[^"]+)"',
        r'href="(https://t\.me/[^"]+)"',
    ):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1).strip()
    for link in re.findall(r'href="(https?://[^"]+)"', html):
        low = link.lower()
        if any(h in low for h in _SKIP_SITE_HOSTS):
            continue
        if low.startswith("mailto:"):
            continue
        return link.strip()
    return ""


def parse_restaurant(url: str) -> dict:
    html = fetch(url)
    slug = url.rstrip("/").split("/")[-1]

    name = ""
    bm = _BREADCRUMB_NAME_RE.search(html)
    if bm:
        name = bm.group(1).strip()
    if not name:
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        if h1:
            name = _clean_name(re.sub(r"<[^>]+>", " ", h1.group(1)))

    category = ""
    cm = _BREADCRUMB_CAT_RE.search(html)
    if cm:
        category = cm.group(1).strip()

    notes: list[str] = []
    if _CANDIDATE_RE.search(html):
        notes.append("Кандидат")
    if category:
        notes.append(category)

    phone = ""
    tm = _TEL_RE.search(html)
    if tm:
        phone = re.sub(r"[\s\-()]", "", tm.group(1).strip())

    return {
        "name": name or slug,
        "website": _pick_site(html),
        "phone": phone,
        "greatlist_url": url,
        "notes": "; ".join(notes),
        "slug": slug,
        "category": category,
    }


def write_outputs(rows: list[dict], base_name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / f"{base_name}.csv"
    md_path = OUT_DIR / f"{base_name}.md"

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)

    lines = [
        "## GreatList — рестораны Москвы",
        f"Источник: [{SOURCE_URL}]({SOURCE_URL})",
        "",
        f"Всего: **{len(rows)}**.",
        "",
        "| № | name | website | phone | greatlist_url | notes |",
        "|---:|---|---|---|---|---|",
    ]
    for i, row in enumerate(rows, 1):
        name = row["name"]
        if row.get("greatlist_url"):
            name = f"[{name}]({row['greatlist_url']})"
        lines.append(
            f"| {i} | {name} | {row.get('website','')} | {row.get('phone','')} | "
            f"{row.get('greatlist_url','')} | {row.get('notes','')} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} -> {csv_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--delay", type=float, default=0.15)
    ap.add_argument("--out", default="greatlist_moscow_restaurants")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    urls = load_sitemap_urls()
    print(f"Found {len(urls)} restaurants in sitemap", file=sys.stderr)

    cache: dict[str, dict] = {}
    if not args.no_cache and CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    cached_urls = {v.get("greatlist_url") for v in cache.values()}
    todo = [u for u in urls if u not in cached_urls]
    if todo:
        print(f"Fetching {len(todo)} pages...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(parse_restaurant, u): u for u in todo}
            done = 0
            for fut in as_completed(futs):
                url = futs[fut]
                try:
                    row = fut.result()
                    cache[row["slug"]] = row
                except Exception as e:
                    print(f"error {url}: {e}", file=sys.stderr)
                done += 1
                if done % 20 == 0:
                    print(f"  {done}/{len(todo)}", file=sys.stderr)
                time.sleep(args.delay / max(args.workers, 1))

        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    slug_by_url = {u.rstrip("/").split("/")[-1]: u for u in urls}
    rows: list[dict] = []
    for url in urls:
        slug = url.rstrip("/").split("/")[-1]
        row = cache.get(slug)
        if not row:
            print(f"missing cache for {slug}", file=sys.stderr)
            continue
        rows.append({k: row.get(k, "") for k in COLUMNS})

    rows.sort(key=lambda r: r["name"].casefold())
    write_outputs(rows, args.out)

    with_phone = sum(1 for r in rows if r.get("phone"))
    with_site = sum(1 for r in rows if r.get("website"))
    print(f"with phone: {with_phone}, with website: {with_site}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
