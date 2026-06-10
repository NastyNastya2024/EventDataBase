#!/usr/bin/env python3
"""Парсинг подрядчиков и площадок с https://wedwed.ru/"""

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
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "wedwed"
FINAL_PATH = ROOT / "final" / "wedwed.md"
CACHE_PATH = ROOT / "scripts" / ".cache" / "wedwed_profiles.json"
SOURCE_URL = "https://wedwed.ru/"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

SITEMAPS = (
    "https://wedwed.ru/sitemap_msc.xml",
    "https://wedwed.ru/sitemap_spb.xml",
)

# slug категорий и SEO-фильтров (не карточки подрядчиков)
_SKIP_SLUGS = frozenset(
    {
        "ploschadki",
        "vedushchie",
        "veduschie",
        "fotografy",
        "videografy",
        "kaver-gruppy-i-muzykanty",
        "shou-programma",
        "oformlenie-i-dekor",
        "horeografy",
        "konditery",
        "stilisty",
        "reelsmakers",
        "dj-i-oborudovanie",
        "transport",
        "feyerverk",
        "organizator",
        "didjay",
        "artist",
        "fokusnik",
        "illusionist",
        "photograph",
        "obraz",
        "obraz-nevesty",
        "obraz-gostey-na-svadbu",
        "obraz-zhenikha",
        "obraz_visajhist",
        "den-rozhdeniya",
        "novogodnyy-korporativ",
        "dlya-korporativa",
        "dlya-fursheta",
        "dlya-svadby-v-podmoskovye",
        "korporativ-10-chelovek",
        "korporativ-20-chelovek",
        "korporativ-30-chelovek",
        "korporativ-40-chelovek",
        "korporativ-100-chelovek",
        "korporativ-nedorogo",
        "korporativ-na-prirode",
        "korporativ-u-vody",
        "korporativ-v-yaht-klube",
        "korporativ-za-gorodom",
        "nedorogo",
        "nedorogie-vedushie",
        "nedorogie-restorany-dlya-svadbi",
        "desheviy",
        "na_1_chas",
        "na_15_chelovek",
        "na_godovchinu",
        "na_semeynuyu_svadby",
        "na_svadby",
        "svadebnoy_ceremonii",
        "svadebny-makiyazh",
        "svadebnye-pricheski",
        "ukladka-volos-na-svadbu",
        "parikmaher_na_dom",
        "parikmaher_visajhist_na_dom",
        "visajhist_nedorogo",
        "tamada_na_chas",
        "voditel",
        "prokat_microavtobusa",
        "arenda_limuzina_po_chasam",
        "arenda_mashin_s_voditelem",
        "2_cheloveka",
        "fire_show",
        "laser_show",
    }
)

CATEGORY_TYPES = {
    "ploschadki": "площадка",
    "vedushchie": "ведущий",
    "veduschie": "ведущий",
    "fotografy": "фотограф",
    "videografy": "видеограф",
    "kaver-gruppy-i-muzykanty": "кавер-группа",
    "shou-programma": "шоу-программа",
    "oformlenie-i-dekor": "декоратор",
    "horeografy": "хореограф",
    "konditery": "кондитер",
    "stilisty": "стилист",
    "reelsmakers": "рилсмейкер",
    "dj-i-oborudovanie": "DJ",
    "transport": "транспорт",
    "feyerverk": "фейерверк",
    "organizator": "организатор",
    "didjay": "DJ",
    "artist": "артист",
    "fokusnik": "фокусник",
    "illusionist": "иллюзионист",
    "photograph": "фотограф",
}

_WEDWED_PHONES = frozenset(
    {
        "74951487258",
        "79675192653",
        "74951487258",
    }
)


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return norm_space(s.replace("&nbsp;", " "))


_PROFILE_URL_RE = re.compile(
    r'<link itemprop="url" href="(https://wedwed\.ru(?:/spb)?/catalog/[^"]+)"'
)
_NAME_RE = re.compile(r'<meta itemprop="name" content="([^"]+)"')
_USER_ID_RE = re.compile(r'sbshowCont[^>]*data-id="(\d+)"')
_STREET_RE = re.compile(r'<meta itemprop="streetAddress" content="([^"]+)"')
_PHONE_META_RE = re.compile(r'<meta itemprop="telephone" content="([^"]+)"')


@dataclass
class ProfileRow:
    name: str = ""
    org_type: str = ""
    site: str = ""
    profile_url: str = ""
    city: str = ""
    category: str = ""
    user_id: str = ""
    phone: str = ""
    email: str = ""
    instagram: str = ""
    telegram: str = ""
    vk: str = ""
    address: str = ""
    contacts: list[tuple[str, str]] = field(default_factory=list)


def fetch(url: str, timeout: float = 45) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_json(url: str, timeout: float = 30) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def norm_url(u: str) -> str:
    u = norm_space(u)
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if not re.match(r"^https?://", u, re.I):
        return "https://" + u.lstrip("/")
    return u.rstrip("/")


def parse_catalog_path(url: str) -> tuple[str, str, str]:
    """city_prefix, category, slug"""
    path = urllib.parse.urlparse(url).path.strip("/")
    parts = path.split("/")
    if parts[:1] == ["spb"]:
        city = "spb"
        parts = parts[1:]
    else:
        city = "msc"
    if len(parts) >= 3 and parts[0] == "catalog":
        return city, parts[1], parts[2]
    return city, "", ""


def is_candidate_url(url: str) -> bool:
    _city, category, slug = parse_catalog_path(url)
    if not category or not slug:
        return False
    if slug == category or slug in _SKIP_SLUGS:
        return False
    return True


def load_sitemap_urls() -> list[str]:
    urls: set[str] = set()
    for sm in SITEMAPS:
        xml = fetch(sm, timeout=60)
        for loc in re.findall(r"<loc>([^<]+)</loc>", xml):
            loc = loc.rstrip("/") + "/"
            if "/catalog/" not in loc:
                continue
            if is_candidate_url(loc):
                urls.add(loc)
    return sorted(urls)


def is_profile_page(html: str, url: str) -> bool:
    canonical = url.rstrip("/") + "/"
    for m in _PROFILE_URL_RE.finditer(html):
        if m.group(1).rstrip("/") + "/" == canonical:
            return True
    return False


def phone_key(p: str) -> str:
    digits = re.sub(r"\D", "", strip_html(p) or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def is_platform_phone(p: str) -> bool:
    key = phone_key(p)
    return bool(key) and key in _WEDWED_PHONES


def is_valid_phone(p: str) -> bool:
    p = strip_html(p)
    if not p or "XX" in p.upper():
        return False
    return not is_platform_phone(p)


def dedupe_contacts(contacts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    seen_phones: set[str] = set()
    for kind, val in contacts:
        val = norm_space(val)
        if not val:
            continue
        if kind == "phone":
            key = phone_key(val)
            if not key or key in seen_phones or not is_valid_phone(val):
                continue
            seen_phones.add(key)
        pair = (kind, val)
        if pair in seen:
            continue
        seen.add(pair)
        out.append(pair)
    return out


def org_type_for(category: str, api_spec: str = "", place: bool = False) -> str:
    if place:
        return CATEGORY_TYPES.get(category, "площадка")
    if api_spec:
        spec = api_spec.lower()
        if "ведущ" in spec:
            return "ведущий"
        if "фотограф" in spec:
            return "фотограф"
        if "видеограф" in spec:
            return "видеограф"
        if "стилист" in spec or "визаж" in spec:
            return "стилист"
        if "декор" in spec or "флорист" in spec:
            return "декоратор"
        if "dj" in spec or "дидж" in spec:
            return "DJ"
        if "кондит" in spec:
            return "кондитер"
        if "музык" in spec or "кавер" in spec:
            return "кавер-группа"
        if "банкет" in spec:
            return "площадка"
    return CATEGORY_TYPES.get(category, category.replace("-", " "))


def load_item_contacts(user_id: str) -> dict:
    if not user_id or user_id == "0":
        return {}
    try:
        data = fetch_json(f"{SOURCE_URL}api/loadItem/?id={user_id}")
    except (urllib.error.URLError, json.JSONDecodeError):
        return {}
    if not data.get("status"):
        return {}
    return data.get("data", {}).get("user", {}) or {}


def parse_profile(url: str) -> ProfileRow | None:
    html = fetch(url)
    if not is_profile_page(html, url):
        return None

    city, category, slug = parse_catalog_path(url)
    profile_url = url.rstrip("/") + "/"

    name = ""
    for m in _NAME_RE.finditer(html):
        candidate = norm_space(m.group(1))
        if candidate and candidate.lower() not in ("wedwed", "главная"):
            name = candidate
            break
    if not name:
        return None

    user_id = ""
    for m in _USER_ID_RE.finditer(html):
        uid = m.group(1)
        if uid != "0":
            user_id = uid
            break

    phones: list[str] = []
    api = load_item_contacts(user_id)
    api_phone = strip_html(api.get("phone") or api.get("sphone") or "")
    if api_phone and is_valid_phone(api_phone):
        phones.append(api_phone)
    elif not api_phone:
        for m in _PHONE_META_RE.finditer(html):
            p = strip_html(m.group(1))
            if not is_valid_phone(p):
                continue
            if phone_key(p) not in {phone_key(x) for x in phones}:
                phones.append(p)
                break

    address = ""
    am = _STREET_RE.search(html)
    if am:
        address = norm_space(am.group(1))

    place = bool(api.get("place"))
    org_type = org_type_for(category, api.get("spec", ""), place)

    if api.get("nameOf"):
        name = norm_space(api.get("nameOf")) or name
    elif api.get("name"):
        name = norm_space(api.get("name")) or name

    sites: list[str] = []
    raw_sites = api.get("sites") or []
    if isinstance(raw_sites, str):
        raw_sites = [raw_sites] if raw_sites else []
    for s in raw_sites:
        s = norm_space(str(s))
        if s:
            sites.append(norm_url(s))

    site = sites[0] if sites else profile_url

    instagram = ""
    insta = norm_space(api.get("insta") or "")
    if insta:
        insta = insta.replace("instagram.com/", "").strip("@/ ")
        instagram = f"https://instagram.com/{insta}/"

    telegram = ""
    tg = norm_space(api.get("telegram") or "")
    if tg:
        tg = tg.strip("@/ ")
        telegram = f"https://t.me/{tg}/"

    vk = ""
    vk_id = norm_space(api.get("vk") or "")
    if vk_id:
        if vk_id.startswith("http"):
            vk = vk_id
        elif vk_id.isdigit():
            vk = f"https://vk.com/id{vk_id}"
        else:
            vk = f"https://vk.com/{vk_id}"

    contacts: list[tuple[str, str]] = []
    for p in phones:
        contacts.append(("phone", p))
    for s in sites[1:]:
        contacts.append(("social", norm_url(s)))
    if instagram:
        contacts.append(("social", instagram))
    if telegram:
        contacts.append(("social", telegram))
    if vk:
        contacts.append(("social", vk))
    if address:
        contacts.append(("address", address))

    contacts = dedupe_contacts(contacts)

    return ProfileRow(
        name=name,
        org_type=org_type,
        site=site,
        profile_url=profile_url,
        city=city,
        category=category,
        user_id=user_id,
        phone=phones[0] if phones else "",
        instagram=instagram,
        telegram=telegram,
        vk=vk,
        address=address,
        contacts=contacts,
    )


def write_final_md(rows: list[ProfileRow], path: Path) -> None:
    table_rows: list[tuple[str, str, str, str, str]] = []
    for row in rows:
        if not row.contacts and row.site:
            table_rows.append((row.name, row.org_type, row.site, "social", row.profile_url))
            continue
        for kind, val in row.contacts:
            if val:
                table_rows.append((row.name, row.org_type, row.site, kind, val))

    table_rows.sort(key=lambda r: (r[0].casefold(), r[3], r[4]))

    lines = [
        "## WedWed — контакты + тип организации",
        "",
        f"Источник: [{SOURCE_URL}]({SOURCE_URL}) (каталог подрядчиков и площадок, Москва + СПб).",
        "",
        f"Организаций: **{len(rows)}**, строк контактов: **{len(table_rows)}**.",
        "",
        "| Организация | Тип | Сайт | Вид контакта | Контакт |",
        "|---|---|---|---|---|",
    ]
    for org, typ, site, kind, contact in table_rows:
        org_e = org.replace("|", "\\|")
        contact_e = contact.replace("|", "\\|")
        lines.append(f"| {org_e} | {typ} | {site} | {kind} | {contact_e} |")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(rows: list[ProfileRow], path: Path) -> None:
    cols = [
        "name",
        "org_type",
        "site",
        "profile_url",
        "city",
        "category",
        "user_id",
        "phone",
        "instagram",
        "telegram",
        "vk",
        "address",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
        w.writeheader()
        for row in rows:
            w.writerow({c: getattr(row, c, "") for c in cols})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--delay", type=float, default=0.12)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="для отладки")
    args = ap.parse_args()

    urls = load_sitemap_urls()
    if args.limit:
        urls = urls[: args.limit]
    print(f"Candidates from sitemap: {len(urls)}", file=sys.stderr)

    cache: dict[str, dict] = {}
    if not args.no_cache and CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    if args.no_cache:
        cache = {}

    todo = [u for u in urls if u not in cache]
    if todo:
        print(f"Fetching {len(todo)} pages...", file=sys.stderr)

        def work(url: str) -> tuple[str, dict | None]:
            try:
                row = parse_profile(url)
                return url, None if row is None else {
                    "name": row.name,
                    "org_type": row.org_type,
                    "site": row.site,
                    "profile_url": row.profile_url,
                    "city": row.city,
                    "category": row.category,
                    "user_id": row.user_id,
                    "phone": row.phone,
                    "instagram": row.instagram,
                    "telegram": row.telegram,
                    "vk": row.vk,
                    "address": row.address,
                    "contacts": row.contacts,
                }
            except Exception as exc:
                print(f"error {url}: {exc}", file=sys.stderr)
                return url, {"_error": str(exc)}

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(work, url): url for url in todo}
            done = 0
            for fut in as_completed(futs):
                url, data = fut.result()
                cache[url] = data
                done += 1
                if done % 25 == 0:
                    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                    CACHE_PATH.write_text(
                        json.dumps(cache, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    profiles = sum(1 for v in cache.values() if v)
                    print(f"  {done}/{len(todo)}, profiles={profiles}", file=sys.stderr)
                time.sleep(args.delay / max(args.workers, 1))

        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    rows: list[ProfileRow] = []
    for url in urls:
        data = cache.get(url)
        if not data or data.get("_error"):
            continue
        contacts = dedupe_contacts([tuple(c) for c in data.get("contacts", [])])
        rows.append(
            ProfileRow(
                name=data.get("name", ""),
                org_type=data.get("org_type", ""),
                site=data.get("site", ""),
                profile_url=data.get("profile_url", url),
                city=data.get("city", ""),
                category=data.get("category", ""),
                user_id=data.get("user_id", ""),
                phone=next((v for k, v in contacts if k == "phone"), data.get("phone", "")),
                instagram=data.get("instagram", ""),
                telegram=data.get("telegram", ""),
                vk=data.get("vk", ""),
                address=data.get("address", ""),
                contacts=contacts,
            )
        )

    rows.sort(key=lambda r: r.name.casefold())
    write_csv(rows, OUT_DIR / "wedwed_contacts.csv")
    write_final_md(rows, FINAL_PATH)

    with_phone = sum(1 for r in rows if r.phone)
    with_site = sum(1 for r in rows if r.site and "wedwed.ru/catalog" not in r.site)
    print(
        f"Profiles: {len(rows)}, with phone: {with_phone}, with external site: {with_site}"
    )
    print(f"Wrote {FINAL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
