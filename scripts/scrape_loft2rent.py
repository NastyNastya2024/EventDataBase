#!/usr/bin/env python3
"""Парсинг каталога лофтов Москвы с https://www.loft2rent.ru/"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "лофтв"
CACHE_PATH = ROOT / "scripts" / ".cache" / "loft2rent_lofts.json"
SOURCE = "https://www.loft2rent.ru/"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

COLUMNS = ["название", "тип_лофт", "телефон", "сайт", "ссылка"]

_AZ_LETTERS = (
    list("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    + ["."]
    + ["Ú"]
    + list("АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЬЭЮЯ")
    + ["№"]
)

_LOFT_PATH_RE = re.compile(r"/loft/\d+/\d+/?")
_SKIP_HOSTS = (
    "loft2rent.ru",
    "google",
    "bootstrap",
    "fontawesome",
    "caterme.ru",
    "rutube.ru",
    "yandex.",
    "stackpath",
    "fonts.googleapis",
    "use.fontawesome",
    "t.me",
    "telegram.",
    "vk.com",
    "vk.ru",
    "instagram.com",
    "facebook.com",
    "fb.com",
    "wa.me",
    "whatsapp",
    "api.whatsapp",
    "max.ru",
    "youtube.com",
    "youtu.be",
    "odnoklassniki",
    "ok.ru",
    "dzen.ru",
    "tiktok.com",
)


def fetch(url: str, timeout: float = 40) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def collect_listing_urls() -> list[str]:
    urls: set[str] = set()

    # A–Z индекс (Москва)
    for letter in _AZ_LETTERS:
        q = urllib.parse.quote(letter, safe="")
        page = fetch(f"{SOURCE}loft/a-z/?letter={q}")
        for path in _LOFT_PATH_RE.findall(page):
            urls.add(path if path.endswith("/") else path + "/")

    # sitemap — дополнительные карточки
    try:
        xml = fetch(f"{SOURCE}sitemap.xml", timeout=120)
        for loc in re.findall(
            r"<loc>(https://www\.loft2rent\.ru/loft/\d+/\d+/?)</loc>", xml
        ):
            path = urllib.parse.urlparse(loc).path
            urls.add(path if path.endswith("/") else path + "/")
    except urllib.error.URLError as exc:
        print(f"warning: sitemap unavailable: {exc}", file=sys.stderr)

    return sorted(
        f"{SOURCE.rstrip('/')}{p}" if p.startswith("/") else p for p in urls
    )


def _parse_json_ld(html: str) -> dict | None:
    for block in re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.S
    ):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and item.get("@type") in (
                "EventVenue",
                "LocalBusiness",
                ["EventVenue", "LocalBusiness"],
            ):
                return item
            if isinstance(item, dict) and "telephone" in item and "name" in item:
                return item
    return None


def _type_from_description(desc: str) -> str:
    # «Название - Лофт, зал . Аренда...»
    m = re.search(r"\s-\s(.+?)\s*\.\s*Аренда", desc)
    if m:
        return m.group(1).strip(" .")
    return ""


def _brand_url(html: str) -> str:
    m = re.search(
        r'<div class="h2[^"]*">\s*<a href="(/loft/[^"]+)"',
        html,
        re.I,
    )
    if m:
        path = m.group(1)
        if re.fullmatch(r"/loft/[^/]+/?", path):
            return urllib.parse.urljoin(SOURCE, path)
    return ""


def _is_valid_external(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.netloc.lower().lstrip("www.")
    if not host or "." not in host or "@" in host:
        return False
    return True


def _external_site(html: str) -> str:
    for url in re.findall(r'href="(https?://[^"]+)"', html, re.I):
        low = url.lower()
        if any(h in low for h in _SKIP_HOSTS):
            continue
        if "loft2rent.ru" in low:
            continue
        clean = url.split("?")[0].rstrip("/")
        if _is_valid_external(clean):
            return clean
    return ""


def parse_loft_page(url: str, html: str) -> dict[str, str]:
    ld = _parse_json_ld(html) or {}
    name = (ld.get("name") or "").strip()

    if not name:
        m = re.search(r'<h1[^>]*itemprop="name"[^>]*>(.*?)</h1>', html, re.S | re.I)
        if not m:
            m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
        if m:
            name = re.sub(r"<[^>]+>", "", m.group(1)).strip()

    loft_type = ""
    desc = (ld.get("description") or "").strip()
    if desc:
        loft_type = _type_from_description(desc)
    if not loft_type:
        m = re.search(
            r'<h2 class="lead[^"]*grey-text[^"]*"[^>]*>(.*?)</h2>',
            html,
            re.S | re.I,
        )
        if m:
            loft_type = re.sub(r"<[^>]+>", "", m.group(1)).strip()

    phone = (ld.get("telephone") or "").strip()
    if not phone:
        tels = re.findall(r'href="tel:([^"]+)"', html)
        phone = next((t.strip() for t in tels if len(re.sub(r"\D", "", t)) >= 10), "")

    site = _external_site(html) or _brand_url(html) or "N/A"
    canonical = (ld.get("url") or "").strip()
    if not canonical:
        m = re.search(r'<link rel="canonical" href="([^"]+)"', html, re.I)
        canonical = m.group(1).strip() if m else url

    return {
        "название": name,
        "тип_лофт": loft_type,
        "телефон": phone,
        "сайт": site,
        "ссылка": canonical,
    }


def scrape_one(url: str, delay: float) -> dict[str, str]:
    if delay:
        time.sleep(delay)
    html = fetch(url)
    row = parse_loft_page(url, html)
    if not row["название"]:
        raise ValueError(f"no name parsed for {url}")
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
    CACHE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_outputs(rows: list[dict[str, str]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "loft2rent_moscow.csv"
    md_path = OUT_DIR / "loft2rent_moscow.md"

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
        w.writeheader()
        w.writerows(rows)

    lines = [
        "## Лофты Москвы — loft2rent.ru",
        "",
        f"Источник: [{SOURCE}]({SOURCE})",
        "",
        f"Всего: **{len(rows)}**.",
        "",
        "| № | " + " | ".join(COLUMNS) + " |",
        "|---:|" + "|".join(["---"] * len(COLUMNS)) + "|",
    ]
    for i, row in enumerate(rows, 1):
        cells = [str(i)] + [row[c].replace("|", "\\|") for c in COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {csv_path} ({len(rows)} rows)")
    print(f"wrote {md_path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument("--limit", type=int, default=0, help="0 = all")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    cache = {} if args.refresh else load_cache()
    urls = collect_listing_urls()
    if args.limit:
        urls = urls[: args.limit]
    print(f"listing urls: {len(urls)} (cached: {len(cache)})")

    todo = [u for u in urls if u not in cache]
    failed: list[tuple[str, str]] = []

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {
                pool.submit(scrape_one, url, args.delay): url for url in todo
            }
            done = 0
            for fut in as_completed(futures):
                url = futures[fut]
                done += 1
                try:
                    cache[url] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    failed.append((url, str(exc)))
                if done % 50 == 0 or done == len(todo):
                    save_cache(cache)
                    print(f"scraped {done}/{len(todo)}", flush=True)
        save_cache(cache)

    rows = [cache[u] for u in urls if u in cache]
    rows.sort(key=lambda r: r["название"].lower())
    write_outputs(rows)

    if failed:
        print(f"failed: {len(failed)}", file=sys.stderr)
        for url, err in failed[:10]:
            print(f"  {url}: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
