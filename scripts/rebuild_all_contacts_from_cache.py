#!/usr/bin/env python3
"""
Пересобирает `all/all_contacts.md` из:
- списка организаций/сайтов (например `all/all_no_focus.md`)
- кэша `scripts/.cache/site_contacts_rows_cache.json`

Полезно, если `all/all_contacts.md` был случайно перезаписан коротким прогоном.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")


@dataclass(frozen=True)
class ContactRow:
    kind: str
    value: str
    desc: str


def _escape_cell(s: str) -> str:
    return (s or "").replace("|", "\\|")


def _clean_site(s: str) -> str:
    s = (s or "").strip()
    if not s or s.upper() == "N/A":
        return ""
    return s.rstrip("/")


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


def read_all_pairs(all_md: Path) -> list[tuple[str, str]]:
    """Return [(name, site)] in file order, regardless of extra columns."""
    text = all_md.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not _TABLE_ROW_RE.match(line):
            continue
        headers = _split_cells(line)
        if not headers:
            continue
        name_col = _find_col(headers, ("название", "организация", "компания", "name"))
        site_col = _find_col(headers, ("сайт", "site", "website"))
        if name_col < 0 or site_col < 0:
            continue
        if i + 1 >= len(lines) or not re.match(r"^\|[\s:|-]+\|\s*$", lines[i + 1]):
            continue
        pairs: list[tuple[str, str]] = []
        for row in lines[i + 2 :]:
            if not row.startswith("|") or row.lstrip().startswith("|---"):
                continue
            cells = _split_cells(row)
            if len(cells) <= max(name_col, site_col):
                continue
            # first col is number; skip if not a data row
            if not cells[0].strip().isdigit():
                continue
            name = cells[name_col].strip()
            site = _clean_site(cells[site_col])
            if name and site:
                pairs.append((name, site))
        return pairs
    return []


def load_cache(cache_path: Path) -> dict[str, list[dict]]:
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_contacts_md(rows: list[tuple[str, str, ContactRow]], out_path: Path) -> None:
    out: list[str] = []
    out.append("## Контакты — телефоны / email / соцсети")
    out.append("")
    out.append("Источник: кэш `scripts/.cache/site_contacts_rows_cache.json` + сайты из `all/all_no_focus.md`.")
    out.append("")
    out.append(f"Всего строк: **{len(rows)}**.")
    out.append("")
    out.append("| Организация | Сайт | Вид контакта | Контакт | Описание |")
    out.append("|---|---|---|---|---|")
    for org, site, c in rows:
        out.append(
            f"| {_escape_cell(org)} | {_escape_cell(site)} | {c.kind} | {_escape_cell(c.value)} | {_escape_cell(c.desc or 'N/A')} |"
        )
    out.append("")
    out_path.write_text("\n".join(out), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Rebuild all_contacts.md from cache")
    ap.add_argument("--all", default="all/all_no_focus.md")
    ap.add_argument("--cache", default="scripts/.cache/site_contacts_rows_cache.json")
    ap.add_argument("--out", default="all/all_contacts.md")
    args = ap.parse_args()

    all_path = ROOT / args.all if not Path(args.all).is_absolute() else Path(args.all)
    cache_path = ROOT / args.cache if not Path(args.cache).is_absolute() else Path(args.cache)
    out_path = ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)

    pairs = read_all_pairs(all_path)
    cache = load_cache(cache_path)

    rows: list[tuple[str, str, ContactRow]] = []
    for org, site in pairs:
        items = cache.get(site) or cache.get(site.rstrip("/")) or []
        parsed: list[ContactRow] = []
        for it in items:
            kind = str(it.get("kind") or "").strip()
            val = str(it.get("value") or "").strip()
            desc = str(it.get("desc") or "N/A").strip()
            if kind and val:
                parsed.append(ContactRow(kind=kind, value=val, desc=desc))

        # order: phones -> emails -> socials -> others
        kind_order = {"phone": 0, "email": 1, "social": 2}
        parsed.sort(key=lambda r: kind_order.get(r.kind, 9))
        for c in parsed:
            rows.append((org, site, c))

    write_contacts_md(rows, out_path)
    print(f"Wrote: {out_path} (rows={len(rows)}, sites_in_all={len(pairs)}, sites_in_cache={len(cache)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

