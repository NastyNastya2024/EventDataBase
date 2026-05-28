#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

IN_PATH = ROOT / "all" / "all_agencies_and_communities.md"
OUT_PATH = ROOT / "all" / "all_agencies_has_site.md"

_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def iter_md_tables(md_text: str):
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].startswith("|"):
            i += 1
            continue
        headers = _split_cells(lines[i])
        if i + 1 >= len(lines) or not _SEP_RE.match(lines[i + 1]):
            i += 1
            continue
        j = i + 2
        rows: list[list[str]] = []
        while j < len(lines) and lines[j].startswith("|"):
            if lines[j].lstrip().startswith("|---"):
                j += 1
                continue
            rows.append(_split_cells(lines[j]))
            j += 1
        yield headers, rows
        i = j


def _find_col(headers: list[str], candidates: tuple[str, ...]) -> int:
    lowered = [h.casefold() for h in headers]
    for cand in candidates:
        c = cand.casefold()
        for i, h in enumerate(lowered):
            if c == h or c in h:
                return i
    return -1


def main() -> int:
    text = IN_PATH.read_text(encoding="utf-8", errors="ignore")
    headers: list[str] | None = None
    rows: list[list[str]] = []
    for h, r in iter_md_tables(text):
        headers, rows = h, r
        break
    if not headers:
        raise SystemExit(f"Could not parse table from {IN_PATH}")

    kind_col = _find_col(headers, ("тип", "type", "kind"))
    name_col = _find_col(headers, ("название", "name"))
    site_col = _find_col(headers, ("сайт", "site", "website", "url"))
    if kind_col < 0 or name_col < 0 or site_col < 0:
        raise SystemExit("Missing required columns: Тип/Название/Сайт")

    out_rows: list[tuple[str, str]] = []
    for r in rows:
        if len(r) <= max(kind_col, name_col, site_col):
            continue
        if r[kind_col].strip().casefold() != "agency":
            continue
        name = r[name_col].strip()
        site = r[site_col].strip()
        if not name or not site or site == "N/A":
            continue
        out_rows.append((name, site))

    out: list[str] = []
    out.append("## Агентства — только строки с сайтом")
    out.append("")
    out.append(f"Источник: `{IN_PATH.relative_to(ROOT)}`.")
    out.append("")
    out.append(f"Всего: **{len(out_rows)}**.")
    out.append("")
    out.append("| № | Название | Сайт |")
    out.append("|---:|---|---|")
    for i, (name, site) in enumerate(out_rows, start=1):
        out.append(f"| {i} | {name.replace('|','\\\\|')} | {site} |")
    out.append("")

    OUT_PATH.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote: {OUT_PATH} (rows={len(out_rows)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

