#!/usr/bin/env python3
"""Импорт ресторанов GreatList (Москва) в final/final.md."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "data" / "restaurants" / "greatlist_moscow_restaurants.csv"
FINAL_PATH = ROOT / "final" / "final.md"

_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")
_SOURCE_NOTE = "+ `data/restaurants/greatlist_moscow_restaurants.csv` (greatlist.ru)."

_CATEGORY_TYPE = {
    "Бары": "бар",
    "Городские кафе": "ресторан / бар",
    "Высокая кухня": "ресторан",
    "Рестораны": "ресторан",
}


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _escape_cell(s: str) -> str:
    return (s or "").replace("|", "\\|")


def _norm_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if u.endswith("/"):
        u = u[:-1]
    return u


def _clean_site(url: str) -> str:
    url = _norm_url(url)
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.query:
        return url
    qs = parse_qs(parsed.query, keep_blank_values=True)
    for key in list(qs.keys()):
        if key.startswith("utm_"):
            del qs[key]
    query = urlencode({k: v[0] for k, v in qs.items()}, doseq=False)
    return urlunparse(parsed._replace(query=query))


def _org_type(notes: str) -> str:
    for part in (notes or "").split(";"):
        part = part.strip()
        if part in _CATEGORY_TYPE:
            return _CATEGORY_TYPE[part]
    return "ресторан"


def read_final_rows(path: Path) -> tuple[list[str], list[tuple[str, str, str, str, str]]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    header_lines: list[str] = []
    rows: list[tuple[str, str, str, str, str]] = []

    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("| Организация |"):
            header_lines = lines[: i + 2]
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                if _SEP_RE.match(lines[i]):
                    i += 1
                    continue
                cells = _split_cells(lines[i])
                if len(cells) >= 5:
                    rows.append(tuple(cells[:5]))
                i += 1
            break
        i += 1

    if not header_lines:
        raise SystemExit(f"Table header not found in {path}")
    return header_lines, rows


def read_restaurant_rows(path: Path) -> list[tuple[str, str, str, str, str]]:
    out: list[tuple[str, str, str, str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            name = (r.get("name") or "").strip()
            if not name:
                continue
            site = _clean_site(r.get("website") or "") or _norm_url(
                r.get("greatlist_url") or ""
            )
            if not site:
                continue
            org_type = _org_type(r.get("notes") or "")
            phone = (r.get("phone") or "").strip()
            greatlist = _norm_url(r.get("greatlist_url") or "")
            if phone:
                out.append((name, org_type, site, "phone", phone))
            elif greatlist:
                out.append((name, org_type, site, "social", greatlist))
    return out


def _ensure_source_note(header_lines: list[str]) -> None:
    if len(header_lines) < 3 or not header_lines[2].startswith("Источник:"):
        return
    if _SOURCE_NOTE not in header_lines[2]:
        header_lines[2] = header_lines[2].rstrip(".") + " " + _SOURCE_NOTE


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", type=Path, default=DEFAULT_CSV)
    args = ap.parse_args()

    if not args.csv.exists():
        raise SystemExit(f"CSV not found: {args.csv}")

    header_lines, existing = read_final_rows(FINAL_PATH)
    seen = {tuple(r) for r in existing}
    restaurant_rows = read_restaurant_rows(args.csv)
    added = 0
    for row in restaurant_rows:
        if row not in seen:
            existing.append(row)
            seen.add(row)
            added += 1

    _ensure_source_note(header_lines)
    existing.sort(key=lambda r: r[0].casefold())

    out_lines = list(header_lines)
    for org, typ, site, kind, contact in existing:
        out_lines.append(
            "| "
            + " | ".join(_escape_cell(x) for x in (org, typ, site, kind, contact))
            + " |"
        )
    out_lines.append("")

    FINAL_PATH.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"restaurant rows from csv: {len(restaurant_rows)}")
    print(f"added to final: {added}")
    print(f"total rows in final: {len(existing)}")
    print(f"wrote: {FINAL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
