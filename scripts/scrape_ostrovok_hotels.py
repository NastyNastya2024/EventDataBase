#!/usr/bin/env python3
"""Parse/scrape Ostrovok Moscow 4-5 star hotels into CSV."""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "hotels"
DEFAULT_MD = (
    Path.home()
    / ".cursor/projects/Users-a1-Documents-GitHub-EventDataBase/uploads/moscow-0.md"
)
CONTACTS_CSV = ROOT / "data" / "hotels" / "moscow_hotels_contacts.csv"
SOURCE_URL = (
    "https://ostrovok.ru/hotel/russia/moscow/?stars=5.4"
)

LISTING_URL = (
    "https://ostrovok.ru/hotel/russia/moscow/"
    "?stars=5.4&sort=popularity&page={page}"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)

COLUMNS = [
    "id",
    "hotel_name",
    "address",
    "stars",
    "phone",
    "website",
    "ostrovok_url",
    "source_url",
    "enrichment_source",
]

HOTEL_PREFIX = re.compile(
    r"^(Отель|Гостиница|Бутик-отель|Сафмар|AZIMUT|Отель-)"
)


def normalize_name(name: str) -> str:
    n = name.lower()
    n = re.sub(r"\s+", " ", n)
    n = re.sub(r"[«»\"']", "", n)
    n = re.sub(r"\(.*?\)", "", n)
    for old, new in [
        ("бывший", ""),
        ("гостиница", ""),
        ("отель", ""),
        ("бутик-отель", ""),
    ]:
        n = n.replace(old, "")
    return re.sub(r"\s+", " ", n).strip()


def load_contacts_index() -> dict[str, dict]:
    if not CONTACTS_CSV.exists():
        return {}
    index: dict[str, dict] = {}
    with CONTACTS_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            name = row.get("hotel_name", "")
            key = normalize_name(name)
            if key:
                index[key] = row
            main = row.get("main_contact", "")
            m = re.search(r"\+7[\d\s\-()]+", main)
            if m and key:
                index[key].setdefault("_phone", m.group(0).strip())
            for part in main.split("/"):
                part = part.strip()
                if "@" in part:
                    domain = part.split("@")[-1].strip()
                    if "." in domain and " " not in domain:
                        index[key].setdefault(
                            "_website",
                            part if part.startswith("http") else f"https://{domain}",
                        )
    return index


def enrich_from_contacts(hotel: dict, index: dict[str, dict]) -> None:
    key = normalize_name(hotel["hotel_name"])
    for candidate in (key, normalize_name(hotel["hotel_name"].split("(")[0])):
        if not candidate or candidate not in index:
            continue
        ref = index[candidate]
        if not hotel.get("phone"):
            phone = ref.get("phone") or ref.get("_phone", "")
            if not phone and ref.get("main_contact"):
                m = re.search(r"\+7[\d\s\-()]+", ref["main_contact"])
                phone = m.group(0).strip() if m else ""
            if phone:
                hotel["phone"] = phone
                hotel["enrichment_source"] = "moscow_hotels_contacts.csv"
        if not hotel.get("website"):
            site = ref.get("website", "") or ref.get("_website", "")
            if not site and ref.get("main_contact"):
                for part in ref["main_contact"].split("/"):
                    p = part.strip()
                    if "." in p and " " not in p and "@" not in p:
                        site = f"https://{p}" if not p.startswith("http") else p
                        break
            if site:
                hotel["website"] = site
                hotel["enrichment_source"] = hotel.get(
                    "enrichment_source", ""
                ) or "moscow_hotels_contacts.csv"
        break


def fetch_listing_page(page: int) -> list[dict]:
    url = LISTING_URL.format(page=page)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise

    match = NEXT_DATA_RE.search(html)
    if not match:
        return []
    data = json.loads(match.group(1))
    return data["props"]["pageProps"]["serpData"]["hotels"]


def scrape_listing_pages(max_pages: int = 20, delay: float = 0.5) -> list[dict]:
    hotels: list[dict] = []
    seen_ids: set[int] = set()

    for page in range(1, max_pages + 1):
        raw = fetch_listing_page(page)
        if not raw:
            print(f"page {page}: empty, stopping", file=sys.stderr)
            break
        added = 0
        for item in raw:
            master_id = item.get("masterId")
            if not master_id or master_id in seen_ids:
                continue
            seen_ids.add(master_id)
            slug = item.get("id", "")
            name = (item.get("name") or "").strip()
            if not name:
                continue
            location = item.get("location") or {}
            address = (location.get("address") or "").strip()
            stars = item.get("stars")
            ostrovok_url = (
                f"https://ostrovok.ru/hotel/russia/moscow/"
                f"mid{master_id}/{slug}/"
                if slug
                else f"https://ostrovok.ru/hotel/russia/moscow/mid{master_id}/"
            )
            hotels.append(
                {
                    "hotel_name": name,
                    "address": address,
                    "stars": str(stars) if stars is not None else "4-5",
                    "phone": "",
                    "website": "",
                    "ostrovok_url": ostrovok_url,
                    "source_url": SOURCE_URL,
                    "enrichment_source": "ostrovok_listing",
                }
            )
            added += 1
        print(f"page {page}: +{added} (total {len(hotels)})", file=sys.stderr)
        if added == 0:
            break
        if page < max_pages:
            time.sleep(delay)

    return hotels


def parse_md_dump(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    hotels: list[dict] = []
    seen: set[str] = set()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if (
            line
            and not line.startswith("*")
            and HOTEL_PREFIX.match(line)
            and "от метро" not in line
            and "км от центра" not in line
            and "отзыв" not in line.lower()
            and "₽" not in line
            and line != "Показать все номера"
            and not line.startswith("от ")
        ):
            name = line
            if name in seen:
                i += 1
                continue
            seen.add(name)
            address = ""
            if i + 2 < len(lines):
                nxt = lines[i + 2].strip()
                if (
                    nxt
                    and "км от" not in nxt
                    and "от метро" not in nxt
                    and "отзыв" not in nxt.lower()
                    and not HOTEL_PREFIX.match(nxt)
                ):
                    address = nxt
            hotels.append(
                {
                    "hotel_name": name,
                    "address": address,
                    "stars": "4-5",
                    "phone": "",
                    "website": "",
                    "ostrovok_url": "",
                    "source_url": SOURCE_URL,
                    "enrichment_source": "",
                }
            )
        i += 1
    return hotels


def scrape_with_playwright(max_pages: int = 13) -> list[dict]:
    from playwright.sync_api import sync_playwright

    hotels: list[dict] = []
    seen_slugs: set[str] = set()
    api_payloads: list = []

    def on_response(response):
        url = response.url
        if "ostrovok" not in url:
            return
        if response.request.resource_type not in ("xhr", "fetch"):
            return
        try:
            if "application/json" not in (response.headers.get("content-type") or ""):
                return
            data = response.json()
            api_payloads.append(data)
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("response", on_response)
        for page_num in range(1, max_pages + 1):
            url = LISTING_URL.format(page=page_num)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"page {page_num} error: {e}", file=sys.stderr)
                continue
            cards = page.query_selector_all('a[href*="/hotel/russia/moscow/"]')
            for card in cards:
                href = card.get_attribute("href") or ""
                if "/mid" not in href and "/hotel/russia/moscow/mid" not in href:
                    if re.search(r"/hotel/russia/moscow/[^/?]+", href):
                        slug_m = re.search(r"/hotel/russia/moscow/([^/?]+)", href)
                        if slug_m:
                            slug = slug_m.group(1)
                            if slug in seen_slugs or slug in (
                                "russia",
                                "moscow",
                            ):
                                continue
                            seen_slugs.add(slug)
                name = (card.inner_text() or "").strip().split("\n")[0]
                if not name or len(name) < 3:
                    continue
                full_url = urljoin("https://ostrovok.ru", href.split("?")[0])
                hotels.append(
                    {
                        "hotel_name": name[:200],
                        "address": "",
                        "stars": "4-5",
                        "phone": "",
                        "website": "",
                        "ostrovok_url": full_url,
                        "source_url": SOURCE_URL,
                        "enrichment_source": "playwright_listing",
                    }
                )
        browser.close()

    # Try extract from API JSON blobs
    for payload in api_payloads:
        _extract_from_json(payload, hotels, seen_slugs)

    return _dedupe_hotels(hotels)


def _extract_from_json(obj, hotels: list, seen_slugs: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("name", "hotel_name", "title") and isinstance(v, str) and len(v) > 3:
                slug = obj.get("slug") or obj.get("ota_hotel_id") or ""
                url = ""
                if slug:
                    url = f"https://ostrovok.ru/hotel/russia/moscow/mid/{slug}/"
                hotels.append(
                    {
                        "hotel_name": v,
                        "address": obj.get("address", "") or "",
                        "stars": "4-5",
                        "phone": "",
                        "website": "",
                        "ostrovok_url": url,
                        "source_url": SOURCE_URL,
                        "enrichment_source": "api_json",
                    }
                )
            else:
                _extract_from_json(v, hotels, seen_slugs)
    elif isinstance(obj, list):
        for item in obj:
            _extract_from_json(item, hotels, seen_slugs)


def _dedupe_hotels(hotels: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for h in hotels:
        key = normalize_name(h["hotel_name"])
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def write_outputs(hotels: list[dict], base_name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / f"{base_name}.csv"
    md_path = OUT_DIR / f"{base_name}.md"

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
        w.writeheader()
        for n, h in enumerate(hotels, 1):
            row = {**h, "id": str(n)}
            w.writerow(row)

    lines = [
        "## Ostrovok — отели Москвы 4–5★",
        f"Источник: `{SOURCE_URL}`",
        "",
        f"Всего: **{len(hotels)}** отелей.",
        "",
        "| № | Отель | Телефон | Сайт | Адрес | Ostrovok |",
        "|---:|---|---|---|---|---|",
    ]
    for h in hotels:
        name = h["hotel_name"]
        if h.get("ostrovok_url"):
            name = f"[{name}]({h['ostrovok_url']})"
        addr = (h.get("address") or "")[:50]
        if len(h.get("address") or "") > 50:
            addr += "…"
        lines.append(
            f"| {h['id']} | {name} | {h.get('phone','')} | {h.get('website','')} | "
            f"{addr} | {h.get('ostrovok_url','')} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(hotels)} -> {csv_path}")


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=None)
    p.add_argument("--browser", action="store_true")
    p.add_argument("--pages", type=int, default=20)
    p.add_argument("--out", default="ostrovok_moscow_4_5_stars")
    args = p.parse_args()

    hotels: list[dict] = []

    try:
        hotels = scrape_listing_pages(max_pages=args.pages)
        print(f"Scraped {len(hotels)} hotels from Ostrovok listings")
    except Exception as e:
        print(f"Listing scrape failed: {e}", file=sys.stderr)

    md_path = args.input or DEFAULT_MD
    if len(hotels) < 50 and md_path.exists():
        parsed = parse_md_dump(md_path)
        print(f"Parsed {len(parsed)} hotels from {md_path}")
        if len(parsed) > len(hotels):
            hotels = parsed

    if args.browser:
        try:
            scraped = scrape_with_playwright(args.pages)
            print(f"Scraped {len(scraped)} hotels via browser")
            if len(scraped) > len(hotels):
                hotels = scraped
        except Exception as e:
            print(f"Browser scrape failed: {e}", file=sys.stderr)

    hotels = _dedupe_hotels(hotels)
    index = load_contacts_index()
    for h in hotels:
        enrich_from_contacts(h, index)

    for n, h in enumerate(hotels, 1):
        h["id"] = str(n)

    write_outputs(hotels, args.out)


if __name__ == "__main__":
    main()
