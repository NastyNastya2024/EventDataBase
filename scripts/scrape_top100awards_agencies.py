#!/usr/bin/env python3
"""
Scrape Top100Awards (Moscow 2026 agencies) and extract contacts from each agency page.

Outputs:
  data/agencies/top100awards_agencies_moscow_2026.csv
  data/agencies/top100awards_agencies_moscow_2026.md
"""

from __future__ import annotations

import csv
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "agencies"

SOURCE_URL = "https://top100awards.ru/agency/2026/msk"
BASE_URL = "https://top100awards.ru"

CSV_NAME = "top100awards_agencies_moscow_2026"


PHONE_RE = re.compile(r"(\+7\s*\(?\d{3}\)?\s*\d{2,3}[\s\-–]\d{2}[\s\-–]\d{2}|\+7\s*\(?\d{3}\)?\s*\d{3}[\s\-–]\d{2}[\s\-–]\d{2})")
HANDLE_RE = re.compile(r"@[\w\.\-]{2,}", re.UNICODE)


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
        p = urlparse(url)
        return p.netloc.lower()
    except Exception:
        return ""


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


def scrape() -> list[AgencyRow]:
    from playwright.sync_api import sync_playwright

    rows: list[AgencyRow] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()

        page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(8000)

        # Listing cards contain direct absolute links like:
        # <a class="card_item-title" href="https://top100awards.ru/stay-studio">...</a>
        card_links = page.eval_on_selector_all(
            "a.card_item-title[href]",
            """els => els.map(a => a.href).filter(Boolean)""",
        )

        agency_slugs: list[str] = []
        seen = set()
        for href in card_links:
            href = (href or "").strip()
            if not href.startswith(BASE_URL + "/"):
                continue
            path = urlparse(href).path.strip("/")
            if not path or "/" in path:
                continue
            slug = path
            if slug in ("login", "place", "policy"):
                continue
            if not re.fullmatch(r"[a-z0-9][a-z0-9\-_]{1,80}", slug):
                continue
            if slug in seen:
                continue
            seen.add(slug)
            agency_slugs.append(slug)

        # Heuristic: on the listing page there may be duplicates; keep order.
        if not agency_slugs:
            raise RuntimeError("No agency slugs found on listing page.")

        for idx, slug in enumerate(agency_slugs, start=1):
            agency_url = urljoin(BASE_URL, f"/{slug}")
            ap = ctx.new_page()
            try:
                ap.goto(agency_url, wait_until="domcontentloaded", timeout=90000)
                ap.wait_for_timeout(1500)

                name = _norm_space((ap.locator("h1").first.inner_text() or ""))
                if not name:
                    # fallback: title
                    name = _norm_space(ap.title())

                links = ap.eval_on_selector_all(
                    "a[href]",
                    """els => els.map(a => ({
                      href: a.href || a.getAttribute('href') || '',
                      text: (a.innerText || '').trim()
                    }))""",
                )

                phone = ""
                website = ""
                instagram = ""
                telegram = ""
                whatsapp = ""
                vk = ""
                email = ""
                other: list[str] = []
                media_domains = {
                    "rutube.ru",
                    "www.rutube.ru",
                    "youtube.com",
                    "www.youtube.com",
                    "youtu.be",
                    "vkvideo.ru",
                    "www.vkvideo.ru",
                }

                # scan links first
                for it in links:
                    href = (it.get("href") or "").strip()
                    text = _norm_space(it.get("text") or "")
                    if not href:
                        continue

                    if href.startswith("tel:"):
                        ph = href.replace("tel:", "").strip()
                        phone = phone or _norm_space(ph)
                        continue
                    if href.startswith("mailto:"):
                        em = href.replace("mailto:", "").strip()
                        # ignore site-wide footer email
                        if not em.lower().endswith("@top100awards.ru"):
                            email = email or _norm_space(em)
                        continue

                    hdom = _domain(href)
                    if hdom in media_domains:
                        continue
                    if "t.me" in hdom or href.startswith("tg:"):
                        telegram = telegram or (href if href.startswith("http") else _norm_url(href))
                        continue
                    if "wa.me" in hdom or "whatsapp" in hdom:
                        whatsapp = whatsapp or href
                        continue
                    if "instagram.com" in hdom:
                        instagram = instagram or href
                        continue
                    if "vk.com" in hdom or "vkontakte" in hdom:
                        vk = vk or href
                        continue

                    # candidate for website: keep first non-top100awards link that isn't a social/messenger
                    if "top100awards.ru" not in hdom and href.startswith("http"):
                        if not website:
                            website = href
                        else:
                            # keep only if this still looks like a contact link (not generic external media)
                            other.append(href)

                    if text and HANDLE_RE.search(text) and not instagram:
                        instagram = HANDLE_RE.search(text).group(0)

                # scan page visible text for phone if not found in tel: link
                if not phone:
                    body_text = ap.inner_text("body")
                    m = PHONE_RE.search(body_text or "")
                    if m:
                        phone = _norm_space(m.group(1))

                # scan label blocks (helps when website shown as plain text)
                def find_value_after_label(label: str) -> str:
                    js = """
                    (label) => {
                      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
                      let node;
                      const isLabel = (el) => (el && el.innerText && el.innerText.trim() === label);
                      while (node = walker.nextNode()) {
                        if (isLabel(node)) {
                          // try next elements
                          let cur = node;
                          for (let i = 0; i < 5; i++) {
                            cur = cur.nextElementSibling;
                            if (!cur) break;
                            const t = (cur.innerText || '').trim();
                            if (t) return t;
                          }
                        }
                      }
                      return '';
                    }
                    """
                    try:
                        return _norm_space(ap.evaluate(js, label))
                    except Exception:
                        return ""

                if not website:
                    val = find_value_after_label("Сайт")
                    if val and "http" not in val:
                        val = _norm_url(val)
                    website = website or val

                if not phone:
                    val = find_value_after_label("Телефон")
                    if val:
                        phone = phone or val

                # Normalize website if it's just a domain
                website = _norm_url(website)

                row = AgencyRow(
                    id=str(idx),
                    agency_name=name,
                    website=website,
                    phone=phone,
                    instagram=instagram,
                    telegram=telegram,
                    whatsapp=whatsapp,
                    vk=vk,
                    email=email,
                    other_contacts=" | ".join(dict.fromkeys([o for o in other if o]))[:2000],
                    agency_url=agency_url,
                    source_url=SOURCE_URL,
                )
                rows.append(row)
            except Exception as e:
                print(f"Failed {agency_url}: {e}", file=sys.stderr)
            finally:
                ap.close()
                time.sleep(0.4)

        ctx.close()
        browser.close()

    # de-dupe by agency_url
    uniq: list[AgencyRow] = []
    seen_url = set()
    for r in rows:
        if r.agency_url in seen_url:
            continue
        seen_url.add(r.agency_url)
        uniq.append(r)
    # re-id
    for i, r in enumerate(uniq, start=1):
        r.id = str(i)
    return uniq


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

    lines = [
        "## TOP100AWARDS’26 — ивент-агентства (Москва)",
        f"Источник: `{SOURCE_URL}`",
        "",
        f"Всего: **{len(rows)}** агентств.",
        "",
        "| № | Агентство | Телефон | Сайт | Instagram | Telegram | WhatsApp |",
        "|---:|---|---|---|---|---|---|",
    ]
    for r in rows[:200]:
        lines.append(
            f"| {r.id} | {r.agency_name} | {r.phone or ''} | {r.website or ''} | "
            f"{r.instagram or ''} | {r.telegram or ''} | {r.whatsapp or ''} |"
        )
    if len(rows) > 200:
        lines.append("")
        lines.append(f"Показаны первые 200 строк, полный список — в `{csv_path.name}`.")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rows = scrape()
    write_outputs(rows)
    print(f"Wrote {len(rows)} agencies to {OUT_DIR / (CSV_NAME + '.csv')}")


if __name__ == "__main__":
    main()

