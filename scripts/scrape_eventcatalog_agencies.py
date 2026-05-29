#!/usr/bin/env python3
"""Парсинг event-агентств с https://eventcatalog.ru/agency/event_agentstva/"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "agencies"
CACHE_PATH = ROOT / "scripts" / ".cache" / "eventcatalog_agencies.json"

SOURCE_URL = "https://eventcatalog.ru/agency/event_agentstva/"
BASE_URL = "https://eventcatalog.ru"
CSV_NAME = "eventcatalog_event_agencies"

RESIDENT_RE = re.compile(
    r'<div class="resident-item[^"]*"[^>]*>\s*<div class="name">\s*'
    r'<a[^>]+href="/agency/([^"/]+)/"[^>]*>([^<]+)</a>',
    re.S | re.I,
)
MAX_LIST_PAGE = 107

SKIP_DOMAINS = (
    "eventcatalog.ru",
    "yandex.",
    "google.",
    "facebook.com",
    "adriver.ru",
    "ad.adriver.ru",
    "googletagmanager.com",
    "event.ru",
    "browsehappy.com",
    "gmpg.org",
    "tns-counter.ru",
    "nr-data.net",
)

# Ссылки EventCatalog в шаблоне страницы (не агентства)
SKIP_HREFS = frozenset(
    {
        "https://t.me/+fh-tlZbLZBA5ODYy",
        "https://t.me/+tXgaWGt16IgyNjAy",
    }
)


@dataclass
class AgencyRow:
    id: str = ""
    agency_name: str = ""
    website: str = ""
    phone: str = ""
    instagram: str = ""
    telegram: str = ""
    whatsapp: str = ""
    vk: str = ""
    email: str = ""
    other_contacts: str = ""
    agency_url: str = ""
    source_url: str = SOURCE_URL


def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _norm_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if re.match(r"^[\w\.-]+\.[a-z]{2,}(/.*)?$", u, flags=re.I):
        return "https://" + u
    return u


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _skip_href(href: str) -> bool:
    low = href.lower()
    if href in SKIP_HREFS:
        return True
    if not href.startswith("http"):
        return True
    return any(d in low for d in SKIP_DOMAINS)


def _contact_html(html: str) -> str:
    start = html.find('class="logo_wrap"')
    if start < 0:
        start = html.find("<h1")
    end = html.find("residentQuickLinksWrap")
    if start >= 0 and end > start:
        return html[start:end]
    end = html.find('<div class="footer')
    return html[:end] if end > 0 else html


def fetch_url(url: str, retries: int = 4) -> str:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            proc = subprocess.run(
                ["curl", "-sL", "-A", "Mozilla/5.0", "--max-time", "45", url],
                capture_output=True,
                check=True,
            )
            return proc.stdout.decode("cp1251", errors="replace")
        except subprocess.CalledProcessError as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch failed {url}: {last_err}")


def listing_url(page: int) -> str:
    if page <= 1:
        return SOURCE_URL
    return f"{SOURCE_URL}?page={page}"


def collect_listings() -> dict[str, str]:
    agencies: dict[str, str] = {}

    def load_page(page: int) -> tuple[int, list[tuple[str, str]]]:
        html = fetch_url(listing_url(page))
        rows = [
            (slug, _norm_space(name))
            for slug, name in RESIDENT_RE.findall(html)
            if slug and name
        ]
        return page, rows

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(load_page, p): p for p in range(1, MAX_LIST_PAGE + 1)}
        done = 0
        for fut in as_completed(futs):
            page, rows = fut.result()
            for slug, name in rows:
                agencies.setdefault(slug, name)
            done += 1
            if done % 20 == 0:
                print(f"listing {done}/{MAX_LIST_PAGE}, unique={len(agencies)}", file=sys.stderr)
            time.sleep(0.05)

    print(f"listing done: {len(agencies)} agencies", file=sys.stderr)
    return agencies


def parse_detail(html: str, slug: str, list_name: str) -> AgencyRow:
    agency_url = f"{BASE_URL}/agency/{slug}/"
    contact = _contact_html(html)

    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    name = _norm_space(re.sub(r"<[^>]+>", " ", h1.group(1))) if h1 else list_name
    if not name:
        tm = re.search(r"<title>([^<|]+)", html)
        name = _norm_space(tm.group(1)) if tm else list_name

    phones = []
    for tel in re.findall(r'href="tel:([^"]+)"', contact, re.I):
        tel = _norm_space(tel)
        if tel and tel not in phones:
            phones.append(tel)
    phone = " / ".join(phones)

    website = ""
    sm = re.search(
        r'class="resident-site-address"[^>]*href="([^"]+)"',
        contact,
        re.I,
    )
    if sm:
        website = _norm_url(sm.group(1))

    emails = []
    for em in re.findall(r'href="mailto:([^"]+)"', contact, re.I):
        em = _norm_space(em)
        if em and "eventcatalog" not in em.lower() and em not in emails:
            emails.append(em)
    email = emails[0] if emails else ""

    instagram = telegram = whatsapp = vk = ""
    other: list[str] = []

    for href in re.findall(r'href="(https?://[^"]+)"', contact, re.I):
        if _skip_href(href):
            continue
        dom = _domain(href)
        if "instagram.com" in dom:
            instagram = instagram or href
        elif "t.me" in dom or href.startswith("tg:"):
            telegram = telegram or href
        elif "wa.me" in dom or "whatsapp.com" in dom:
            whatsapp = whatsapp or href
        elif "vk.com" in dom:
            vk = vk or href
        elif not website and href.startswith("http"):
            other.append(href)

    if not website:
        for href in other:
            if "instagram" not in href and "t.me" not in href and "vk.com" not in href:
                website = href
                break

    website = _norm_url(website)
    other_filtered = [o for o in other if o != website][:5]

    return AgencyRow(
        agency_name=name,
        website=website,
        phone=phone,
        instagram=instagram,
        telegram=telegram,
        whatsapp=whatsapp,
        vk=vk,
        email=email,
        other_contacts=" | ".join(other_filtered),
        agency_url=agency_url,
    )


def scrape_details(
    agencies: dict[str, str],
    cache: dict[str, dict],
    workers: int = 5,
    delay: float = 0.25,
) -> list[AgencyRow]:
    todo = [s for s in agencies if s not in cache]

    def load_one(slug: str) -> tuple[str, dict]:
        html = fetch_url(f"{BASE_URL}/agency/{slug}/")
        row = parse_detail(html, slug, agencies[slug])
        return slug, asdict(row)

    if todo:
        print(f"fetching {len(todo)} detail pages...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(load_one, slug): slug for slug in todo}
            done = 0
            for fut in as_completed(futs):
                slug, data = fut.result()
                cache[slug] = data
                done += 1
                if done % 50 == 0:
                    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                    CACHE_PATH.write_text(
                        json.dumps(cache, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print(f"  details {done}/{len(todo)}", file=sys.stderr)
                time.sleep(delay / max(workers, 1))

    rows: list[AgencyRow] = []
    for slug in sorted(agencies, key=lambda s: agencies[s].casefold()):
        data = cache.get(slug)
        if not data:
            continue
        row = AgencyRow(**data)
        rows.append(row)

    for i, row in enumerate(rows, 1):
        row.id = str(i)
    return rows


def write_outputs(rows: list[AgencyRow]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / f"{CSV_NAME}.csv"
    md_path = OUT_DIR / f"{CSV_NAME}.md"

    columns = list(asdict(AgencyRow()).keys())
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))

    with_phone = sum(1 for r in rows if r.phone)
    with_site = sum(1 for r in rows if r.website)

    lines = [
        "## EventCatalog — event-агентства",
        f"Источник: [{SOURCE_URL}]({SOURCE_URL})",
        "",
        f"Всего: **{len(rows)}** агентств.",
        f"С телефоном: **{with_phone}**, с сайтом: **{with_site}**.",
        "",
        "| № | Агентство | Телефон | Сайт | EventCatalog |",
        "|---:|---|---|---|---|",
    ]
    for r in rows[:200]:
        name = r.agency_name
        if r.agency_url:
            name = f"[{name}]({r.agency_url})"
        lines.append(
            f"| {r.id} | {name} | {r.phone or ''} | {r.website or ''} | {r.agency_url or ''} |"
        )
    if len(rows) > 200:
        lines.append("")
        lines.append(f"Показаны первые 200 строк, полный список — в `{csv_path.name}`.")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} -> {csv_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--delay", type=float, default=0.25)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--list-only", action="store_true")
    args = ap.parse_args()

    cache: dict[str, dict] = {}
    if not args.no_cache and CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    agencies = collect_listings()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    meta = {"listings": agencies, "fetched_at": time.strftime("%Y-%m-%d")}
    if args.list_only:
        CACHE_PATH.write_text(json.dumps(meta | cache, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"listings only: {len(agencies)}")
        return 0

    rows = scrape_details(agencies, cache, workers=args.workers, delay=args.delay)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    write_outputs(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
