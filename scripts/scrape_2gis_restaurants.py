#!/usr/bin/env python3
"""Scrape 2GIS search results for 'ресторан' in Moscow via browser API interception."""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

SEARCH_URL = (
    "https://2gis.ru/moscow/search/%D1%80%D0%B5%D1%81%D1%82%D0%BE%D1%80%D0%B0%D0%BD%20"
    "?m=37.62017%2C55.753836%2F11"
)
OUT_CSV = Path(__file__).resolve().parents[1] / "data" / "2gis_restaurants_moscow.csv"

CSV_FIELDS = [
    "id_2gis",
    "name",
    "type_name",
    "address",
    "rating",
    "reviews_count",
    "branches_count",
    "rubrics",
    "avg_check",
    "business_lunch",
    "cuisines",
    "tags",
    "phone",
    "website",
    "url_2gis",
    "lat",
    "lon",
    "schedule",
    "is_ad",
    "query",
    "source",
]


def _first(*values):
    for v in values:
        if v is not None and v != "":
            return v
    return ""


def _phones(contact_groups) -> str:
    if not contact_groups:
        return ""
    nums = []
    for g in contact_groups:
        for c in g.get("contacts") or []:
            if c.get("type") == "phone":
                t = (c.get("text") or "").strip()
                if t:
                    nums.append(t)
    return "; ".join(dict.fromkeys(nums))


def _sites(contact_groups) -> str:
    if not contact_groups:
        return ""
    urls = []
    for g in contact_groups:
        for c in g.get("contacts") or []:
            if c.get("type") in ("website", "url"):
                u = (c.get("url") or c.get("text") or "").strip()
                if u:
                    urls.append(u)
    return "; ".join(dict.fromkeys(urls))


def _rubrics_text(rubrics) -> str:
    if not rubrics:
        return ""
    return "; ".join(r.get("name", "") for r in rubrics if r.get("name"))


def _attr(attrs, key: str) -> str:
    if not attrs:
        return ""
    for a in attrs:
        if a.get("tag") == key or a.get("name") == key:
            return str(a.get("text") or a.get("value") or "")
    return ""


def item_to_row(item: dict) -> dict:
    point = item.get("point") or {}
    reviews = item.get("reviews") or {}
    org = item.get("org") or {}
    links = item.get("links") or {}
    schedule = item.get("schedule") or {}
    attrs = item.get("attributes") or item.get("attribute_groups") or []

    gid = _first(item.get("id"), item.get("branch_id"))
    url = links.get("self") or (f"https://2gis.ru/firm/{gid}" if gid else "")

    sched_parts = []
    if isinstance(schedule, dict):
        for day, hours in schedule.items():
            if isinstance(hours, dict) and hours.get("working_hours"):
                sched_parts.append(f"{day}: {hours['working_hours']}")
    sched = "; ".join(sched_parts[:7])

    return {
        "id_2gis": gid,
        "name": _first(item.get("name"), org.get("name")),
        "type_name": _first(item.get("type"), item.get("subtype")),
        "address": _first(
            (item.get("address_name") or ""),
            (item.get("full_address_name") or ""),
            ((item.get("address") or {}).get("name") if isinstance(item.get("address"), dict) else ""),
        ),
        "rating": reviews.get("rating") or reviews.get("general_rating") or "",
        "reviews_count": reviews.get("count") or reviews.get("general_review_count") or "",
        "branches_count": org.get("branch_count") or item.get("branch_count") or "",
        "rubrics": _rubrics_text(item.get("rubrics")),
        "avg_check": _attr(attrs, "average_bill") or _attr(attrs, "check"),
        "business_lunch": _attr(attrs, "business_lunch"),
        "cuisines": _attr(attrs, "cuisine") or _rubrics_text(item.get("rubrics")),
        "tags": _attr(attrs, "features"),
        "phone": _phones(item.get("contact_groups")),
        "website": _sites(item.get("contact_groups")),
        "url_2gis": url,
        "lat": point.get("lat") or "",
        "lon": point.get("lon") or "",
        "schedule": sched,
        "is_ad": "1" if item.get("ads") or item.get("is_advertising") else "",
        "query": "ресторан",
        "source": "2gis.ru/moscow",
    }


def extract_items(payload: dict) -> list[dict]:
    if not payload:
        return []
    result = payload.get("result") or payload
    items = result.get("items")
    if items:
        return items
    if isinstance(result.get("items"), list):
        return result["items"]
    return []


def merge_items(store: dict[str, dict], items: list[dict]) -> None:
    for raw in items:
        row = item_to_row(raw)
        key = row["id_2gis"] or f"{row['name']}|{row['address']}"
        if not key:
            continue
        if key not in store or len(json.dumps(raw, ensure_ascii=False)) > len(
            json.dumps(store[key], ensure_ascii=False)
        ):
            store[key] = row


def scroll_results(page, rounds: int = 80) -> None:
    """Scroll the results panel to trigger lazy loading."""
    page.wait_for_timeout(3000)
    for i in range(rounds):
        page.evaluate(
            """() => {
            const sel = [
              '[class*="_scroll"]',
              '[class*="scroll"]',
              'div[role="list"]',
              'aside',
              '[data-testid="searchResults"]',
            ];
            let el = null;
            for (const s of sel) {
              const nodes = document.querySelectorAll(s);
              for (const n of nodes) {
                if (n.scrollHeight > n.clientHeight + 100) { el = n; break; }
              }
              if (el) break;
            }
            if (!el) el = document.scrollingElement || document.body;
            el.scrollTop = el.scrollHeight;
            }"""
        )
        page.wait_for_timeout(800)
        if i % 10 == 9:
            print(f"  scroll {i + 1}/{rounds}", flush=True)


def run(headless: bool = True, scroll_rounds: int = 120) -> Path:
    collected: dict[str, dict] = {}
    api_urls: list[str] = []

    def on_response(response):
        url = response.url
        if "catalog.api.2gis" not in url and "catalog.api.2gis.ru" not in url:
            return
        if response.status != 200:
            return
        try:
            data = response.json()
        except Exception:
            return
        items = extract_items(data)
        if items:
            before = len(collected)
            merge_items(collected, items)
            added = len(collected) - before
            if added:
                print(f"  +{added} from API (total {len(collected)})", flush=True)
        api_urls.append(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            locale="ru-RU",
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.on("response", on_response)

        print(f"Opening {SEARCH_URL}", flush=True)
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(5000)

        # Try pagination via API key from captured URLs
        keys = set()
        for u in api_urls:
            qs = parse_qs(urlparse(u).query)
            if "key" in qs:
                keys.add(qs["key"][0])

        scroll_results(page, scroll_rounds)

        # Re-scan responses after scroll
        page.wait_for_timeout(2000)

        # Parse visible cards as fallback
        cards = page.locator('a[href*="/firm/"]').all()
        print(f"DOM firm links: {len(cards)}", flush=True)

        browser.close()

    # If we captured an API key, paginate programmatically
    if keys and len(collected) < 500:
        import urllib.request

        key = next(iter(keys))
        page_num = 1
        while page_num <= 200:
            api = (
                "https://catalog.api.2gis.com/3.0/items"
                f"?q=%D1%80%D0%B5%D1%81%D1%82%D0%BE%D1%80%D0%B0%D0%BD"
                f"&city_id=4504222397630173&type=branch&page_size=50&page={page_num}"
                f"&key={key}"
                "&fields=items.point,items.address,items.rubrics,items.contact_groups,"
                "items.reviews,items.org,items.schedule,items.link,items.attributes"
            )
            try:
                with urllib.request.urlopen(api, timeout=30) as resp:
                    data = json.loads(resp.read().decode())
            except Exception as e:
                print(f"API page {page_num} failed: {e}", flush=True)
                break
            items = extract_items(data)
            if not items:
                break
            before = len(collected)
            merge_items(collected, items)
            print(f"API page {page_num}: +{len(collected) - before} (total {len(collected)})", flush=True)
            meta = (data.get("result") or {}).get("total") or data.get("result", {}).get("total")
            if len(items) < 50:
                break
            page_num += 1

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter=";")
        w.writeheader()
        for i, row in enumerate(sorted(collected.values(), key=lambda r: (r["name"], r["address"])), 1):
            w.writerow(row)

    print(f"Wrote {len(collected)} rows -> {OUT_CSV}", flush=True)
    return OUT_CSV


if __name__ == "__main__":
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    run(scroll_rounds=rounds)
