#!/usr/bin/env python3
"""
Собирает контакты (телефоны, email, соцсети) с сайтов и формирует таблицу-«список»:

| Организация | Вид контакта | Контакт | Описание |

Требование: если у организации несколько телефонов/почт/соцсетей — организация дублируется
отдельной строкой на каждый контакт (email отдельными строками «под телефоном» — т.е. после).

Источники:
- Входная таблица: markdown с колонкой «Сайт» (например `all/all_no_focus.md`)
- Для каждого сайта берём главную страницу и до N внутренних страниц «контакты» на домене.

Выход по умолчанию: `all/all_contacts.md`.
Кэш: `scripts/.cache/site_contacts_rows_cache.json` (по ключу домена/URL сайта).
"""

from __future__ import annotations

import argparse
import html as htmlmod
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DEFAULT = ROOT / "scripts" / ".cache" / "site_contacts_rows_cache.json"

_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_EMPTY = frozenset({"", "—", "n/a", "N/A", "нет"})
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_CONTACT_PATH_RE = re.compile(
    r"(?:^|/)(?:contacts?|kontakt|контакт|about|connect|support|feedback|связ)(?:/|$|\.html)",
    re.I,
)

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9](?:[a-zA-Z0-9._%+-]{0,62}[a-zA-Z0-9])?"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z]{2,})+"
)
_MAILTO_A_RE = re.compile(
    r'<a[^>]+href=["\']mailto:([^"\'>?]+)[^"\'>]*["\'][^>]*>(.*?)</a>',
    re.I | re.S,
)
_TEL_A_RE = re.compile(
    r'<a[^>]+href=["\']tel:([^"\'>]+)["\'][^>]*>(.*?)</a>',
    re.I | re.S,
)
_HREF_RE = re.compile(r"""href=["']([^"'#]+)["']""", re.I)

_SOCIAL_HOSTS = (
    "vk.com",
    "vk.ru",
    "t.me",
    "telegram.me",
    "telegram.org",
    "instagram.com",
    "facebook.com",
    "fb.com",
    "youtube.com",
    "youtu.be",
    "linkedin.com",
    "ok.ru",
    "odnoklassniki.ru",
    "twitter.com",
    "x.com",
    "wa.me",
    "api.whatsapp.com",
    "dzen.ru",
    "tiktok.com",
    "rutube.ru",
)

_EMAIL_BLOCKLIST = (
    "example.com",
    "email.com",
    "domain.com",
    "sentry",
    "wixpress.com",
    "webpack",
)


@dataclass(frozen=True)
class ContactRow:
    kind: str  # phone | email | social
    value: str
    desc: str


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


def _escape_cell(s: str) -> str:
    return s.replace("|", "\\|")


def _norm_url(url: str) -> str:
    url = (url or "").strip()
    if not url or url in _EMPTY:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def _same_site(base: str, link: str) -> bool:
    try:
        b = urllib.parse.urlparse(base)
        u = urllib.parse.urlparse(urllib.parse.urljoin(base, link))
        return b.netloc.casefold() == u.netloc.casefold()
    except Exception:
        return False


def _is_social_url(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.casefold()
    except Exception:
        return False
    if host.startswith("www."):
        host = host[4:]
    return any(host == h or host.endswith("." + h) for h in _SOCIAL_HOSTS)


def _clean_email(raw: str) -> str:
    e = htmlmod.unescape(raw).strip().strip("<>").casefold()
    if not e or "@" not in e:
        return ""
    if any(b in e for b in _EMAIL_BLOCKLIST):
        return ""
    if len(e) > 80:
        return ""
    return e


def _clean_phone(raw: str) -> str:
    s = htmlmod.unescape(raw).strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) < 10 or len(digits) > 15:
        return ""
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("7"):
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    return "+" + digits


def _strip_tags(s: str) -> str:
    s = re.sub(r"<script[^>]*>.*?</script>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmlmod.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _desc_from_anchor_text(text_html: str) -> str:
    t = _strip_tags(text_html)
    t = t.replace("Тел:", "").replace("тел:", "").replace("Телефон:", "").strip()
    if not t or t in {"—", "N/A"}:
        return "N/A"
    if len(t) > 80:
        t = t[:77] + "..."
    return t


def fetch_html(url: str, timeout: float) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA, "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        cset = resp.headers.get_content_charset() or "utf-8"
    try:
        return raw.decode(cset, errors="ignore")
    except Exception:
        return raw.decode("utf-8", errors="ignore")


def discover_contact_urls(html: str, base_url: str, limit: int) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for m in _HREF_RE.finditer(html):
        href = htmlmod.unescape(m.group(1)).strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        abs_url = urllib.parse.urljoin(base_url, href)
        if not _same_site(base_url, abs_url):
            continue
        path = urllib.parse.urlparse(abs_url).path
        if not _CONTACT_PATH_RE.search(path):
            continue
        key = abs_url.split("#")[0].rstrip("/")
        if key not in seen:
            seen.add(key)
            found.append(key)
        if len(found) >= limit:
            break
    return found


def extract_contacts(html: str, page_url: str) -> list[ContactRow]:
    out: list[ContactRow] = []
    seen = set()

    for m in _TEL_A_RE.finditer(html):
        phone = _clean_phone(m.group(1))
        if not phone:
            continue
        desc = _desc_from_anchor_text(m.group(2))
        key = ("phone", phone)
        if key not in seen:
            seen.add(key)
            out.append(ContactRow("phone", phone, desc))

    for m in _MAILTO_A_RE.finditer(html):
        email = _clean_email(m.group(1))
        if not email:
            continue
        desc = _desc_from_anchor_text(m.group(2))
        key = ("email", email)
        if key not in seen:
            seen.add(key)
            out.append(ContactRow("email", email, desc))

    for m in _EMAIL_RE.finditer(html):
        email = _clean_email(m.group(0))
        if not email:
            continue
        key = ("email", email)
        if key not in seen:
            seen.add(key)
            out.append(ContactRow("email", email, "N/A"))

    for m in _HREF_RE.finditer(html):
        href = htmlmod.unescape(m.group(1)).strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:")):
            continue
        abs_url = urllib.parse.urljoin(page_url, href)
        if not _is_social_url(abs_url):
            continue
        norm = abs_url.split("#")[0].rstrip("/")
        try:
            host = urllib.parse.urlparse(norm).netloc
        except Exception:
            host = ""
        desc = host.replace("www.", "") if host else "social"
        key = ("social", norm)
        if key not in seen:
            seen.add(key)
            out.append(ContactRow("social", norm, desc))

    return out


def scrape_site(site_url: str, *, timeout: float, extra_pages: int) -> list[ContactRow]:
    base = _norm_url(site_url)
    if not base:
        return []
    try:
        home_html = fetch_html(base, timeout=timeout)
    except Exception:
        return []
    rows = extract_contacts(home_html, base)
    for sub in discover_contact_urls(home_html, base, limit=extra_pages):
        try:
            sub_html = fetch_html(sub, timeout=timeout)
            rows.extend(extract_contacts(sub_html, sub))
        except Exception:
            continue

    # de-dup preserve order
    seen = set()
    uniq: list[ContactRow] = []
    for r in rows:
        k = (r.kind, r.value)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq


def load_cache(path: Path) -> dict[str, list[dict]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cache(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_input_sites(md_text: str) -> list[tuple[str, str]]:
    lines = md_text.splitlines()
    for i, line in enumerate(lines):
        if not _TABLE_ROW_RE.match(line):
            continue
        headers = _split_cells(line)
        name_col = _find_col(headers, ("название", "организация", "компания", "name"))
        site_col = _find_col(headers, ("сайт", "site", "website"))
        if name_col < 0 or site_col < 0:
            continue
        if i + 1 >= len(lines) or not re.match(r"^\|[\s:|-]+\|\s*$", lines[i + 1]):
            continue
        pairs: list[tuple[str, str]] = []
        for row in lines[i + 2 :]:
            if not row.startswith("|"):
                continue
            cells = _split_cells(row)
            if len(cells) <= max(name_col, site_col):
                continue
            if not (cells[0].strip().isdigit()):
                continue
            name = cells[name_col].strip()
            site = _norm_url(cells[site_col].strip())
            if name and site:
                pairs.append((name, site))
        return pairs
    return []


def write_contacts_md(rows: list[tuple[str, str, ContactRow]], out_path: Path) -> None:
    out: list[str] = []
    out.append("## Контакты — телефоны / email / соцсети")
    out.append("")
    out.append("Источник: сайты из `all/all_no_focus.md` (или другого входного файла).")
    out.append("")
    out.append(f"Всего строк: **{len(rows)}**.")
    out.append("")
    out.append("| Организация | Сайт | Вид контакта | Контакт | Описание |")
    out.append("|---|---|---|---|---|")
    for org, site, c in rows:
        out.append(
            f"| { _escape_cell(org) } | { _escape_cell(site) } | {c.kind} | { _escape_cell(c.value) } | { _escape_cell(c.desc or 'N/A') } |"
        )
    out.append("")
    out_path.write_text("\n".join(out), encoding="utf-8")


def _flush(out_path: Path, rows: list[tuple[str, str, ContactRow]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_contacts_md(rows, out_path)

def _snapshot_if_exists(path: Path) -> None:
    if not path.exists():
        return
    hist_dir = path.parent / "contacts_delta_history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    snap = hist_dir / f"{path.stem}.{ts}{path.suffix}"
    # best-effort snapshot
    try:
        snap.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    except Exception:
        pass


def _parse_existing_contacts_rows(path: Path) -> tuple[list[str], set[str]]:
    """
    Returns (header_lines_up_to_separator, set_of_data_row_lines).
    If file doesn't exist, returns a fresh header and empty set.
    """
    if not path.exists():
        header = [
            "## Контакты — телефоны / email / соцсети",
            "",
            "Источник: сайты из `all/all_no_focus.md` (или другого входного файла).",
            "",
            "Всего строк: **0**.",
            "",
            "| Организация | Сайт | Вид контакта | Контакт | Описание |",
            "|---|---|---|---|---|",
        ]
        return header, set()

    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header: list[str] = []
    rows: set[str] = set()
    in_table = False
    for line in lines:
        if not in_table:
            header.append(line)
            if line.lstrip().startswith("|---"):
                in_table = True
            continue
        if not line.startswith("|") or line.lstrip().startswith("|---"):
            continue
        if "Организация" in line and "Вид контакта" in line:
            continue
        rows.add(line.rstrip())
    return header, rows


def _write_merged_contacts(path: Path, header: list[str], rows: list[str]) -> None:
    # update total count if present
    for i, line in enumerate(header):
        if line.strip().startswith("Всего строк:"):
            header[i] = f"Всего строк: **{len(rows)}**."
            break
    body = "\n".join(header + rows) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def append_to_contacts(all_contacts_path: Path, new_rows: list[tuple[str, str, ContactRow]]) -> int:
    header, existing = _parse_existing_contacts_rows(all_contacts_path)

    added = 0
    for org, site, c in new_rows:
        line = (
            f"| { _escape_cell(org) } | { _escape_cell(site) } | {c.kind} | "
            f"{ _escape_cell(c.value) } | { _escape_cell(c.desc or 'N/A') } |"
        )
        if line not in existing:
            existing.add(line)
            added += 1

    merged_rows = sorted(existing)
    _write_merged_contacts(all_contacts_path, header, merged_rows)
    return added


def main() -> int:
    p = argparse.ArgumentParser(description="Сбор контактов с сайтов в виде списка строк")
    p.add_argument("--input", default="all/all_no_focus.md")
    p.add_argument("--output", default="all/all_contacts.md")
    p.add_argument("--cache", default=str(CACHE_DEFAULT))
    p.add_argument("--sleep", type=float, default=1.0)
    p.add_argument("--timeout", type=float, default=20.0)
    p.add_argument("--limit", type=int, default=0, help="Макс. число НОВЫХ сайтов (0 = все)")
    p.add_argument("--extra-pages", type=int, default=2)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--flush-every", type=int, default=10, help="Как часто сохранять результат (в сайтах)")
    p.add_argument(
        "--skip-cached",
        action="store_true",
        help="Пропускать сайты, которые уже есть в кэше (удобно для продолжения)",
    )
    p.add_argument(
        "--snapshot-output",
        action="store_true",
        help="Перед записью результата сохранять предыдущую версию output в all/contacts_delta_history/",
    )
    p.add_argument(
        "--append-to",
        default="",
        help="Если задано: добавлять найденные строки в этот файл (без затирания), например all/all_contacts.md",
    )
    p.add_argument(
        "--start-from",
        default="",
        help="Начать обработку с названия (case-insensitive, можно подстрокой)",
    )
    args = p.parse_args()

    in_path = Path(args.input)
    if not in_path.is_absolute():
        in_path = ROOT / in_path
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    if args.snapshot_output:
        _snapshot_if_exists(out_path)

    pairs = parse_input_sites(in_path.read_text(encoding="utf-8"))
    if not pairs:
        print("Не нашёл входную таблицу с колонкой «Сайт».", file=sys.stderr)
        return 1

    cache_path = Path(args.cache)
    cache = {} if args.no_cache else load_cache(cache_path)

    all_rows: list[tuple[str, str, ContactRow]] = []
    new_sites = 0
    started = not bool(args.start_from.strip())
    start_key = args.start_from.casefold().strip()

    for org, site in pairs:
        if not started:
            if start_key and start_key not in org.casefold():
                continue
            started = True

        ck = site.casefold()
        if ck in cache:
            if args.skip_cached:
                continue
            items = [
                ContactRow(x.get("kind", ""), x.get("value", ""), x.get("desc", "N/A"))
                for x in (cache.get(ck) or [])
                if (x.get("kind") and x.get("value"))
            ]
        else:
            if args.limit > 0 and new_sites >= args.limit:
                break
            print(f"  [{new_sites + 1}] {org} — {site}", flush=True)
            items = scrape_site(site, timeout=args.timeout, extra_pages=args.extra_pages)
            cache[ck] = [dict(kind=i.kind, value=i.value, desc=i.desc) for i in items]
            new_sites += 1
            if args.sleep > 0:
                time.sleep(args.sleep)
            if args.flush_every > 0 and new_sites % args.flush_every == 0:
                _flush(out_path, all_rows)
                if not args.no_cache:
                    save_cache(cache_path, cache)

        # порядок: телефоны -> email -> соцсети
        phones = [i for i in items if i.kind == "phone"]
        emails = [i for i in items if i.kind == "email"]
        socials = [i for i in items if i.kind == "social"]
        for i in phones + emails + socials:
            all_rows.append((org, site, i))

    write_contacts_md(all_rows, out_path)
    if not args.no_cache:
        save_cache(cache_path, cache)

    if args.append_to:
        target = Path(args.append_to)
        if not target.is_absolute():
            target = ROOT / target
        added = append_to_contacts(target, all_rows)
        print(f"  добавлено в {target}: {added} строк", flush=True)

    print(f"Готово: {out_path}")
    print(f"  обработано новых сайтов: {new_sites}, строк контактов: {len(all_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

