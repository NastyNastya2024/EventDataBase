#!/usr/bin/env python3
"""
Собирает телефоны, email и соцсети с сайтов из markdown-таблицы (колонка «Сайт»).

Обходит главную страницу и до 2 внутренних страниц «контакты» на том же домене.
Результат пишет в колонки «Телефон», «Email», «Соцсети» (добавляет, если их нет).

Примеры:
  python scripts/scrape_site_contacts.py --input all/all_no_focus.md --limit 20 --sleep 1
  python scripts/scrape_site_contacts.py --input all/all_no_focus.md --output all/all_no_focus.md
"""

from __future__ import annotations

import argparse
import html as htmlmod
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DEFAULT = ROOT / "scripts" / ".cache" / "site_contacts_cache.json"

_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_EMPTY = frozenset({"", "—", "n/a", "N/A", "нет"})
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9](?:[a-zA-Z0-9._%+-]{0,62}[a-zA-Z0-9])?"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z]{2,})+"
)
_PHONE_RE = re.compile(
    r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
    r"|\+?\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{2,4}[\s\-]?\d{2,4}[\s\-]?\d{0,4}"
)
_TEL_HREF_RE = re.compile(r'href=["\']tel:([^"\']+)["\']', re.I)
_MAILTO_RE = re.compile(r'href=["\']mailto:([^"\'?]+)', re.I)
_HREF_RE = re.compile(r"""href=["']([^"'#]+)["']""", re.I)

_CONTACT_PATH_RE = re.compile(
    r"(?:^|/)(?:contacts?|kontakt|контакт|about|connect|support|feedback|связ)(?:/|$|\.html)",
    re.I,
)

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
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "svg",
    "webpack",
)
_MAX_PHONES = 8
_MAX_EMAILS = 5
_MAX_SOCIALS = 12


@dataclass
class Contacts:
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    socials: list[str] = field(default_factory=list)

    def merge(self, other: Contacts) -> None:
        for p in other.phones:
            if p not in self.phones:
                self.phones.append(p)
        for e in other.emails:
            if e not in self.emails:
                self.emails.append(e)
        for s in other.socials:
            if s not in self.socials:
                self.socials.append(s)


@dataclass
class TableSpec:
    header_line_idx: int
    sep_line_idx: int
    name_col: int
    site_col: int
    phone_col: int
    email_col: int
    social_col: int
    lines: list[str]


def _split_cells(line: str) -> list[str]:
    inner = line.strip().strip("|")
    return [c.strip() for c in inner.split("|")]


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
    url = url.strip()
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
    e = raw.strip().strip("<>").casefold()
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
    if 10 <= len(digits) <= 15:
        return "+" + digits
    return ""


def _phone_key(p: str) -> str:
    return re.sub(r"\D", "", p)


def _extract_from_html(html: str, page_url: str) -> Contacts:
    out = Contacts()
    seen_phones: set[str] = set()
    seen_emails: set[str] = set()
    seen_socials: set[str] = set()

    for m in _TEL_HREF_RE.finditer(html):
        p = _clean_phone(m.group(1))
        k = _phone_key(p)
        if p and k not in seen_phones:
            seen_phones.add(k)
            out.phones.append(p)

    for m in _MAILTO_RE.finditer(html):
        e = _clean_email(m.group(1))
        if e and e not in seen_emails:
            seen_emails.add(e)
            out.emails.append(e)

    for m in _EMAIL_RE.finditer(html):
        e = _clean_email(m.group(0))
        if e and e not in seen_emails:
            seen_emails.add(e)
            out.emails.append(e)

    for m in _PHONE_RE.finditer(html):
        p = _clean_phone(m.group(0))
        k = _phone_key(p)
        if p and k not in seen_phones:
            seen_phones.add(k)
            out.phones.append(p)

    for m in _HREF_RE.finditer(html):
        href = htmlmod.unescape(m.group(1)).strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:")):
            continue
        abs_url = urllib.parse.urljoin(page_url, href)
        if _is_social_url(abs_url):
            norm = abs_url.split("#")[0].rstrip("/")
            if norm not in seen_socials:
                seen_socials.add(norm)
                out.socials.append(norm)

    return out


def _discover_contact_urls(html: str, base_url: str, limit: int = 2) -> list[str]:
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


def fetch_html(url: str, timeout: float) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA, "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        ctype = resp.headers.get_content_charset() or "utf-8"
    try:
        return raw.decode(ctype, errors="ignore")
    except Exception:
        return raw.decode("utf-8", errors="ignore")


def scrape_site(url: str, *, timeout: float, extra_pages: int) -> Contacts:
    base = _norm_url(url)
    if not base:
        return Contacts()

    total = Contacts()
    try:
        home_html = fetch_html(base, timeout)
    except Exception:
        return total

    total.merge(_extract_from_html(home_html, base))
    for sub in _discover_contact_urls(home_html, base, limit=extra_pages):
        try:
            sub_html = fetch_html(sub, timeout)
            total.merge(_extract_from_html(sub_html, sub))
        except Exception:
            continue
    total.phones = total.phones[:_MAX_PHONES]
    total.emails = total.emails[:_MAX_EMAILS]
    total.socials = total.socials[:_MAX_SOCIALS]
    return total


def _join_cell(items: list[str]) -> str:
    return "; ".join(items) if items else "N/A"


def ensure_contact_columns(spec: TableSpec) -> None:
    headers = _split_cells(spec.lines[spec.header_line_idx])
    n = len(headers)

    def _ensure_col(name: str, attr: str, candidates: tuple[str, ...]) -> int:
        col = _find_col(headers, candidates)
        if col < 0:
            headers.append(name)
            col = len(headers) - 1
        setattr(spec, attr, col)
        return col

    _ensure_col("Телефон", "phone_col", ("телефон", "phone", "тел"))
    _ensure_col("Email", "email_col", ("email", "e-mail", "почта", "mail"))
    _ensure_col("Соцсети", "social_col", ("соцсети", "social", "соц", "социальные"))

    spec.lines[spec.header_line_idx] = "| " + " | ".join(headers) + " |"
    spec.lines[spec.sep_line_idx] = "| " + " | ".join(
        ["---:"] + ["---"] * (len(headers) - 1)
    ) + " |"

    for row_idx in range(spec.sep_line_idx + 1, len(spec.lines)):
        line = spec.lines[row_idx]
        if not _TABLE_ROW_RE.match(line):
            continue
        cells = _split_cells(line)
        if not cells or cells[0].startswith("---"):
            continue
        while len(cells) < len(headers):
            cells.append("N/A")
        spec.lines[row_idx] = "| " + " | ".join(_escape_cell(c) for c in cells) + " |"


def parse_table(text: str) -> TableSpec | None:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not _TABLE_ROW_RE.match(line):
            continue
        cells = _split_cells(line)
        name_col = _find_col(cells, ("название", "организация", "компания", "name"))
        site_col = _find_col(cells, ("сайт", "site", "website"))
        if name_col < 0 or site_col < 0:
            continue
        if i + 1 >= len(lines) or not re.match(r"^\|[\s:|-]+\|\s*$", lines[i + 1]):
            continue
        spec = TableSpec(
            header_line_idx=i,
            sep_line_idx=i + 1,
            name_col=name_col,
            site_col=site_col,
            phone_col=_find_col(cells, ("телефон", "phone")),
            email_col=_find_col(cells, ("email", "почта", "mail")),
            social_col=_find_col(cells, ("соцсети", "social")),
            lines=lines,
        )
        ensure_contact_columns(spec)
        return spec
    return None


def load_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_table(path: Path, spec: TableSpec) -> None:
    body = "\n".join(spec.lines)
    if body and not body.endswith("\n"):
        body += "\n"
    path.write_text(body, encoding="utf-8")


def run(
    spec: TableSpec,
    *,
    cache: dict,
    cache_path: Path,
    out_path: Path,
    sleep_s: float,
    limit: int,
    timeout: float,
    extra_pages: int,
    only_empty: bool,
    flush_every: int,
) -> tuple[int, int]:
    scraped = 0
    filled = 0
    max_col = max(spec.phone_col, spec.email_col, spec.social_col)

    for row_idx in range(spec.sep_line_idx + 1, len(spec.lines)):
        line = spec.lines[row_idx]
        if not _TABLE_ROW_RE.match(line):
            continue
        cells = _split_cells(line)
        if len(cells) <= max(spec.site_col, max_col):
            continue

        site = _norm_url(cells[spec.site_col])
        if not site:
            continue

        if only_empty:
            if (
                cells[spec.phone_col].strip() not in _EMPTY
                and cells[spec.email_col].strip() not in _EMPTY
                and cells[spec.social_col].strip() not in _EMPTY
            ):
                continue

        if limit > 0 and scraped >= limit:
            break

        cache_key = site.casefold()
        if cache_key in cache:
            data = cache[cache_key]
            c = Contacts(
                phones=list(data.get("phones") or []),
                emails=list(data.get("emails") or []),
                socials=list(data.get("socials") or []),
            )
        else:
            name = cells[spec.name_col].strip()
            print(f"  [{scraped + 1}] {name} — {site}", flush=True)
            c = scrape_site(site, timeout=timeout, extra_pages=extra_pages)
            cache[cache_key] = {
                "phones": c.phones,
                "emails": c.emails,
                "socials": c.socials,
            }
            scraped += 1
            if sleep_s > 0:
                time.sleep(sleep_s)

        cells[spec.phone_col] = _join_cell(c.phones)
        cells[spec.email_col] = _join_cell(c.emails)
        cells[spec.social_col] = _join_cell(c.socials)
        spec.lines[row_idx] = "| " + " | ".join(_escape_cell(x) for x in cells) + " |"
        if c.phones or c.emails or c.socials:
            filled += 1

        if scraped > 0 and flush_every > 0 and scraped % flush_every == 0:
            _write_table(out_path, spec)
            save_cache(cache_path, cache)

    return scraped, filled


def main() -> int:
    parser = argparse.ArgumentParser(description="Телефоны, email и соцсети с сайтов из markdown-таблицы")
    parser.add_argument("--input", default="all/all_no_focus.md")
    parser.add_argument("--output", default="")
    parser.add_argument("--cache", default=str(CACHE_DEFAULT))
    parser.add_argument("--sleep", type=float, default=1.0, help="Пауза между сайтами (с)")
    parser.add_argument("--timeout", type=float, default=20.0, help="Таймаут HTTP (с)")
    parser.add_argument("--limit", type=int, default=0, help="Макс. число новых сайтов (0 = все)")
    parser.add_argument("--extra-pages", type=int, default=2, help="Страниц «контакты» на домен")
    parser.add_argument("--only-empty", action="store_true", help="Только строки с N/A во всех трёх колонках")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--flush-every", type=int, default=25)
    args = parser.parse_args()

    in_path = ROOT / args.input if not Path(args.input).is_absolute() else Path(args.input)
    out_path = Path(args.output) if args.output else in_path
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    spec = parse_table(in_path.read_text(encoding="utf-8"))
    if spec is None:
        print("Не найдена таблица с колонками «Название» и «Сайт».", file=sys.stderr)
        return 1

    cache_path = Path(args.cache)
    cache = {} if args.no_cache else load_cache(cache_path)

    scraped, filled = run(
        spec,
        cache=cache,
        cache_path=cache_path,
        out_path=out_path,
        sleep_s=args.sleep,
        limit=args.limit,
        timeout=args.timeout,
        extra_pages=args.extra_pages,
        only_empty=args.only_empty,
        flush_every=args.flush_every,
    )

    _write_table(out_path, spec)
    if not args.no_cache:
        save_cache(cache_path, cache)

    print(f"Готово: {out_path}")
    print(f"  обработано сайтов: {scraped}, строк с контактами: {filled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
