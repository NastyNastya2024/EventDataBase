#!/usr/bin/env python3
"""Импорт лофтов loft2rent.ru в final/final.md (тип: лофт)."""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOFT_CSV = ROOT / "data" / "лофтв" / "loft2rent_moscow.csv"
FINAL_PATH = ROOT / "final" / "final.md"

_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")
ORG_TYPE = "лофт"


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _escape_cell(s: str) -> str:
    return (s or "").replace("|", "\\|")


def _norm_url(u: str) -> str:
    u = (u or "").strip()
    if not u or u.upper() == "N/A":
        return ""
    if u.endswith("/"):
        u = u[:-1]
    return u


def _resolve_site(site: str, link: str) -> str:
    site = (site or "").strip()
    link = (link or "").strip()
    if site and site.upper() != "N/A":
        return _norm_url(site) or site
    return _norm_url(link) or link


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


def read_loft_rows(path: Path) -> list[tuple[str, str, str, str, str]]:
    out: list[tuple[str, str, str, str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            name = (r.get("название") or "").strip()
            phone = (r.get("телефон") or "").strip()
            site = _resolve_site(r.get("сайт") or "", r.get("ссылка") or "")
            if not name or not site or not phone:
                continue
            out.append((name, ORG_TYPE, site, "phone", phone))
    return out


def main() -> int:
    if not LOFT_CSV.exists():
        raise SystemExit(f"Missing: {LOFT_CSV}")

    header_lines, existing = read_final_rows(FINAL_PATH)
    loft_rows = read_loft_rows(LOFT_CSV)

    seen = {tuple(r) for r in existing}
    added = 0
    for row in loft_rows:
        if row not in seen:
            existing.append(row)
            seen.add(row)
            added += 1

    existing.sort(key=lambda r: r[0].casefold())

    out_lines = list(header_lines)
    # обновить строку источника
    if len(out_lines) >= 3 and out_lines[2].startswith("Источник:"):
        src = out_lines[2]
        if "loft2rent" not in src:
            out_lines[2] = (
                src.rstrip(".")
                + " + `data/лофтв/loft2rent_moscow.csv` (лофты loft2rent.ru, тип «лофт»)."
            )

    for org, typ, site, kind, contact in existing:
        out_lines.append(
            "| "
            + " | ".join(_escape_cell(x) for x in (org, typ, site, kind, contact))
            + " |"
        )
    out_lines.append("")

    FINAL_PATH.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"loft rows from csv: {len(loft_rows)}")
    print(f"added to final: {added}")
    print(f"total rows in final: {len(existing)}")
    print(f"wrote: {FINAL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
