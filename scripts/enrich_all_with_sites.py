#!/usr/bin/env python3
"""
Enrich `all/all.md` with a `Сайт` column.

Strategy:
- Read rows (name, type) from `all/all.md`
- Build an index of name -> best site from local `data/**` markdown/csv tables
- If an official site isn't found, fall back to a relevant contacts/source page link
- Write output to `all/all_with_sites.md` (does not overwrite source by default)

By default this script is offline-first (no web requests).
Optionally, you can enable web search fallback to fill remaining N/A rows.
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def _norm_name(s: str) -> str:
    # normalize whitespace and quotes; keep case-insensitive key
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("’", "'").replace("`", "'")
    return s.casefold()

_LEGAL_PREFIX_RE = re.compile(
    r"^(?:"
    r"пао|оао|ао|ооо|зао|оао|пao|pao|llc|inc|ltd|pjsc|jsc"
    r")\s+",
    re.IGNORECASE,
)

def _canon_name(s: str) -> str:
    """
    Aggressive canonicalization for fuzzy matching between variants.
    Examples:
    - 'ПАО «ЛУКОЙЛ»' -> 'лукойл'
    - 'UTair (офисы в МСК)' -> 'utair'
    - 'Alfa Capital' -> 'alfa capital'
    """
    s = s.strip()
    s = s.replace("’", "'")
    # drop bracketed qualifiers
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"«|»|\"|'", " ", s)
    s = s.replace("—", " ")
    s = s.replace("/", " ")
    s = re.sub(r"\b(of(?:is)?|office|hq|events|event|team|org committee|committee|ecosystem|network)\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(представительство|офис|мск|москва|московский|московская|hq|логистика|логистик[аи])\b", " ", s, flags=re.IGNORECASE)
    s = _LEGAL_PREFIX_RE.sub("", s.strip())
    s = re.sub(r"[^\w\s.-]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s.casefold()


def _is_kontur_focus_url(url: str) -> bool:
    u = url.casefold().strip()
    if not u:
        return False
    return "focus.kontur.ru" in u or (
        "kontur.ru" in u and ("/site/" in u or "populyarnye-kompanii" in u)
    )


def _clean_site(s: str) -> str:
    s = s.strip()
    if not s or s in {"—", "N/A"}:
        return ""
    # Strip markdown link: [text](url)
    m = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", s)
    if m:
        s = m.group(2).strip()
    # If someone stored bare domain without scheme, keep as-is (but prefer https)
    if re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/.*)?", s) and not s.startswith(("http://", "https://")):
        s = "https://" + s
    if _is_kontur_focus_url(s):
        return ""
    return s


def _better_site(new: str, old: str) -> bool:
    """Return True if new should replace old."""
    if not new:
        return False
    if not old:
        return True
    # prefer https over http
    if new.startswith("https://") and old.startswith("http://"):
        return True
    # prefer non-placeholder
    if old in {"—", "N/A"}:
        return True
    # otherwise keep existing
    return False


def _is_probably_contact_link(col_name: str) -> bool:
    c = col_name.casefold()
    return any(
        k in c
        for k in (
            "contact",
            "контакт",
            "источник",
            "source",
            "profile",
            "rusprofile",
            "карточка",
            "страница",
        )
    )


def _is_probably_site_link(col_name: str) -> bool:
    c = col_name.casefold()
    return any(k in c for k in ("site", "сайт", "website", "официальный"))


@dataclass(frozen=True)
class AllRow:
    name: str
    typ: str


def read_all_rows(path: Path) -> list[AllRow]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    rows: list[AllRow] = []
    in_table = False
    for line in text.splitlines():
        if line.startswith("| № |") and "Название" in line and "Тип" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) < 3:
            continue
        if parts[0].startswith("---"):
            continue
        if not re.fullmatch(r"\d+", parts[0]):
            continue
        name = parts[1]
        typ = parts[2]
        rows.append(AllRow(name=name, typ=typ))
    return rows


def iter_md_tables_with_site(md_text: str) -> Iterable[tuple[str, str]]:
    """
    Yield (name, site) pairs from markdown tables that contain a 'Сайт' column.
    Works with many table header variants.
    """
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if "|" not in line or not line.strip().startswith("|"):
            i += 1
            continue
        header = [c.strip() for c in line.strip().strip("|").split("|")]
        header_lower = [h.lower() for h in header]
        # detect any site/url-like column
        has_site_col = any(("сайт" in h) or (h in {"site", "website", "url"}) for h in header_lower)
        if not has_site_col:
            i += 1
            continue

        # determine indices
        site_idx: Optional[int] = None
        name_idx: Optional[int] = None
        for j, h in enumerate(header):
            hl = h.lower()
            if (h == "Сайт") or (hl in {"site", "website", "url"}) or ("сайт" in hl):
                site_idx = j
                break

        # choose a likely name column
        preferred_name_headers = {
            "организация",
            "компания",
            "банк",
            "отель",
            "ресторан",
            "площадка",
            "пространство",
            "объект",
            "событие",
            "комьюнити",
            "название",
            "агентство",
        }
        for j, h in enumerate(header):
            if h == "№":
                continue
            if site_idx is not None and j == site_idx:
                continue
            hl = h.lower()
            if any(ph in hl for ph in preferred_name_headers):
                name_idx = j
                break
        if name_idx is None:
            # fallback first non-№ non-site column
            for j, h in enumerate(header):
                if h == "№":
                    continue
                if site_idx is not None and j == site_idx:
                    continue
                if h:
                    name_idx = j
                    break

        if site_idx is None or name_idx is None:
            i += 1
            continue

        # skip separator row
        i += 2
        while i < len(lines) and lines[i].strip().startswith("|") and "|" in lines[i]:
            row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            if len(row) <= max(site_idx, name_idx):
                i += 1
                continue
            name = row[name_idx]
            site = row[site_idx]

            # if picked № column as name, shift
            if re.fullmatch(r"\d+", name) and len(row) > name_idx + 1:
                name = row[name_idx + 1]

            name = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", name).strip()
            site = _clean_site(site)
            if name and site:
                yield name, site
            i += 1
        # continue scanning
    return


def iter_csv_name_site_pairs(csv_path: Path) -> Iterable[tuple[str, str]]:
    with csv_path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        except Exception:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        if not reader.fieldnames:
            return
        lower = {h.lower(): h for h in reader.fieldnames}
        name_key = lower.get("name") or lower.get("название") or lower.get("restaurant") or lower.get("hotel") or lower.get("company_name") or lower.get("company")
        site_key = lower.get("site") or lower.get("сайт") or lower.get("website") or lower.get("url") or lower.get("официальный сайт")
        if not name_key or not site_key:
            return
        for row in reader:
            name = (row.get(name_key) or "").strip()
            site = _clean_site(row.get(site_key) or "")
            if name and site:
                yield name, site


def iter_csv_name_link_pairs(csv_path: Path) -> Iterable[tuple[str, str, str]]:
    """
    Yield (name, link, link_kind) where link_kind is 'site' or 'contact'.
    """
    with csv_path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        except Exception:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        if not reader.fieldnames:
            return
        # name column
        lower = {h.lower(): h for h in reader.fieldnames}
        name_key = (
            lower.get("company_name")
            or lower.get("company")
            or lower.get("name")
            or lower.get("название")
            or lower.get("организация")
            or lower.get("компания")
            or lower.get("restaurant")
            or lower.get("hotel")
        )
        if not name_key:
            return

        # link columns: collect any that look like site/contact
        site_cols = [h for h in reader.fieldnames if _is_probably_site_link(h)]
        contact_cols = [h for h in reader.fieldnames if _is_probably_contact_link(h)]

        # common explicit columns in our datasets
        for extra in ("contact_source_url", "source_url"):
            if extra in lower:
                contact_cols.append(lower[extra])
        # dedupe preserving order
        site_cols = list(dict.fromkeys(site_cols))
        contact_cols = list(dict.fromkeys(contact_cols))

        for row in reader:
            name = (row.get(name_key) or "").strip()
            if not name:
                continue

            for c in site_cols:
                link = _clean_site(row.get(c) or "")
                if link:
                    yield name, link, "site"

            for c in contact_cols:
                link = _clean_site(row.get(c) or "")
                if link:
                    yield name, link, "contact"


def build_link_index() -> tuple[dict[str, str], dict[str, str]]:
    """
    Build ({normalized_name: best_site}, {normalized_name: best_contact_link})
    from local sources.
    """
    site_index: dict[str, str] = {}
    contact_index: dict[str, str] = {}

    # Prefer data folders where we actually store 'Сайт' columns
    data_dirs = [
        ROOT / "data" / "organizations",
        ROOT / "data" / "hotels",
        ROOT / "data" / "restaurants",
        ROOT / "data" / "event_spaces",
        ROOT / "data" / "communities",
        ROOT / "data" / "events",
        ROOT / "data" / "agencies",
    ]

    for d in data_dirs:
        if not d.exists():
            continue
        for md in d.rglob("*.md"):
            text = md.read_text(encoding="utf-8", errors="ignore")
            for name, site in iter_md_tables_with_site(text):
                k = _norm_name(name)
                old = site_index.get(k, "")
                if _better_site(site, old):
                    site_index[k] = site

        for csv_path in d.rglob("*.csv"):
            for name, link, kind in iter_csv_name_link_pairs(csv_path):
                k = _norm_name(name)
                if kind == "site":
                    old = site_index.get(k, "")
                    if _better_site(link, old):
                        site_index[k] = link
                else:
                    old = contact_index.get(k, "")
                    if _better_site(link, old):
                        contact_index[k] = link

    # Add canonical aliases when unambiguous
    def _canon_aliases(src: dict[str, str], prefix: str) -> dict[str, str]:
        canon_map: dict[str, str] = {}
        canon_conflicts: set[str] = set()
        for k, link in src.items():
            c = _canon_name(k)
            if not c:
                continue
            prev = canon_map.get(c)
            if prev and prev != link:
                canon_conflicts.add(c)
            else:
                canon_map[c] = link
        for c in canon_conflicts:
            canon_map.pop(c, None)
        return {f"{prefix}{c}": link for c, link in canon_map.items()}

    site_index.update(_canon_aliases(site_index, "__canon_site__:"))
    contact_index.update(_canon_aliases(contact_index, "__canon_contact__:"))

    return site_index, contact_index


def write_all_with_sites(
    rows: list[AllRow],
    site_index: dict[str, str],
    contact_index: dict[str, str],
    out_path: Path,
    *,
    enable_web_search: bool = False,
    web_max_queries: int = 0,
    web_sleep_s: float = 1.0,
    use_google: bool = False,
    google_backend: str = "auto",
    serper_api_key: str = "",
) -> None:
    out_lines: list[str] = []
    out_lines.append("## ALL — единая таблица")
    out_lines.append("")
    out_lines.append("Источник: `all/all.md` + локальные таблицы `data/**` (без web-поиска).")
    out_lines.append("")
    out_lines.append(f"Всего: **{len(rows)}**.")
    out_lines.append("")
    out_lines.append("| № | Название | Тип | Сайт |")
    out_lines.append("|---:|---|---|---|")
    web_queries_done = 0
    for i, r in enumerate(rows, start=1):
        key = _norm_name(r.name)
        canon = _canon_name(r.name)

        site = site_index.get(key, "") or site_index.get(f"__canon_site__:{canon}", "")
        if not site:
            site = contact_index.get(key, "") or contact_index.get(f"__canon_contact__:{canon}", "")

        if not site and enable_web_search and (web_max_queries <= 0 or web_queries_done < web_max_queries):
            from google_search import build_query, google_first_url

            q = build_query(r.name, "официальный сайт")
            if use_google:
                try:
                    found = google_first_url(
                        q,
                        backend=google_backend,
                        serper_api_key=serper_api_key,
                    )
                except Exception:
                    found = ""
            else:
                found = ddg_first_result_url(q)
            web_queries_done += 1
            if web_sleep_s > 0:
                time.sleep(web_sleep_s)
            if found:
                site = found

        site_cell = site if site else "N/A"
        out_lines.append(f"| {i} | {r.name.replace('|','\\\\|')} | {r.typ} | {site_cell} |")
    out_lines.append("")
    out_path.write_text("\n".join(out_lines), encoding="utf-8")


_DDG_RESULT_A_RE = re.compile(r'class=\"result__a\"[^>]*href=\"([^\"]+)\"')


def ddg_first_result_url(query: str) -> str:
    """
    Lightweight web search via DuckDuckGo HTML endpoint.
    Returns the first external result URL, or '' on failure.

    Notes:
    - This is best-effort and may break if DDG changes markup.
    - Use rate limiting to avoid blocks.
    """
    try:
        url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
                "Accept-Language": "ru,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""

    # Sometimes DDG returns no result__a links for RU queries; try also lite endpoint
    if "result__a" not in html:
        try:
            url2 = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query})
            req2 = urllib.request.Request(
                url2,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
                    "Accept-Language": "ru,en;q=0.8",
                },
            )
            with urllib.request.urlopen(req2, timeout=20) as resp2:
                html = resp2.read().decode("utf-8", errors="ignore")
        except Exception:
            pass

    # Typical result links are /l/?uddg=<urlencoded>
    for m in _DDG_RESULT_A_RE.finditer(html):
        href = m.group(1)
        href = href.replace("&amp;", "&")
        if href.startswith("//"):
            href = "https:" + href
        if "duckduckgo.com/l/?" in href and "uddg=" in href:
            parsed = urllib.parse.urlparse(href)
            qs = urllib.parse.parse_qs(parsed.query)
            uddg = qs.get("uddg", [""])[0]
            if uddg:
                return urllib.parse.unquote(uddg)
        # fallback: if direct external link
        if href.startswith(("http://", "https://")) and "duckduckgo.com" not in href:
            return href
    # Lite endpoint fallback parsing: look for first /l/?uddg=
    m = re.search(r"/l/\?uddg=([^&\"'>\\s]+)", html)
    if m:
        decoded = urllib.parse.unquote(m.group(1))
        if decoded.startswith(("http://", "https://")):
            return decoded

    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(ROOT / "all" / "all.md"))
    parser.add_argument("--output", default=str(ROOT / "all" / "all_with_sites.md"))
    parser.add_argument("--web", action="store_true", help="Enable web-search fallback for remaining N/A rows")
    parser.add_argument("--google", action="store_true", help="With --web: use Google (Serper/CSE/scrape) instead of DuckDuckGo")
    parser.add_argument("--google-backend", default="auto", choices=("auto", "serper", "cse", "scrape"))
    parser.add_argument("--serper-api-key", default="", help="Serper API key (or env SERPER_API_KEY)")
    parser.add_argument("--web-max-queries", type=int, default=0, help="Limit number of web queries (0 = no limit)")
    parser.add_argument("--web-sleep-s", type=float, default=1.0, help="Delay between web queries (seconds)")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    rows = read_all_rows(in_path)
    site_index, contact_index = build_link_index()
    write_all_with_sites(
        rows,
        site_index,
        contact_index,
        out_path,
        enable_web_search=args.web,
        web_max_queries=args.web_max_queries,
        web_sleep_s=args.web_sleep_s,
        use_google=args.google,
        google_backend=args.google_backend,
        serper_api_key=args.serper_api_key,
    )
    print(
        f"Wrote: {out_path} (rows={len(rows)}, indexed_site_links={len(site_index)}, indexed_contact_links={len(contact_index)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

