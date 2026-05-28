#!/usr/bin/env python3
"""
Собирает единый список агентств из `data/agencies/*.md`.

Выход: `all/all_agencies.md`
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")
_MD_LINK_RE = re.compile(r"^\[([^\]]+)\]\(([^)]+)\)$")


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


def _clean_cell(s: str) -> str:
    s = (s or "").strip()
    m = _MD_LINK_RE.match(s)
    if m:
        return m.group(1).strip()
    return s


def _clean_url(s: str) -> str:
    s = (s or "").strip()
    if not s or s in {"—", "N/A"}:
        return ""
    m = _MD_LINK_RE.match(s)
    if m:
        s = m.group(2).strip()
    if re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/.*)?", s) and not s.startswith(("http://", "https://")):
        s = "https://" + s
    return s


def iter_tables(md_text: str):
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("|"):
            i += 1
            continue
        headers = _split_cells(line)
        if i + 1 >= len(lines) or not _SEP_RE.match(lines[i + 1]):
            i += 1
            continue
        j = i + 2
        rows = []
        while j < len(lines) and lines[j].startswith("|"):
            if lines[j].lstrip().startswith("|---"):
                j += 1
                continue
            rows.append(_split_cells(lines[j]))
            j += 1
        yield headers, rows
        i = j


def collect_agencies() -> dict[str, str]:
    agencies: dict[str, str] = {}
    for p in (ROOT / "data" / "agencies").glob("*.md"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        for headers, rows in iter_tables(text):
            name_col = _find_col(headers, ("агентство", "agency", "компания", "название", "организация"))
            if name_col < 0:
                continue

            for r in rows:
                if len(r) <= name_col:
                    continue
                name = _clean_cell(r[name_col])
                if not name or name in {"(АВТОРЫ)"}:
                    continue
                key = name.casefold()
                if key not in agencies:
                    agencies[key] = name
    return agencies


def main() -> int:
    agencies = collect_agencies()
    rows = sorted(agencies.values(), key=lambda s: s.casefold())

    out = []
    out.append("## Агентства — единый список")
    out.append("")
    out.append("Источник: агрегировано из документов в `data/agencies/` (все `.md`).")
    out.append("")
    out.append(f"Всего: **{len(rows)}**.")
    out.append("")
    out.append("| № | Агентство |")
    out.append("|---:|---|")
    for i, name in enumerate(rows, start=1):
        out.append(f"| {i} | {name.replace('|','\\\\|')} |")
    out.append("")

    (ROOT / "all" / "all_agencies.md").write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote: {ROOT / 'all' / 'all_agencies.md'} (rows={len(rows)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

