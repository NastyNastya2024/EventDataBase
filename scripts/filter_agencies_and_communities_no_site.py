#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

IN_PATH = ROOT / "all" / "all_agencies_and_communities.md"
OUT_PATH = ROOT / "all" / "all_agencies_and_communities_no_site.md"

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
    if not IN_PATH.exists():
        raise SystemExit(f"Missing: {IN_PATH}")

    text = IN_PATH.read_text(encoding="utf-8", errors="ignore")
    headers: list[str] | None = None
    rows: list[list[str]] = []
    for h, r in iter_md_tables(text):
        headers = h
        rows = r
        break
    if not headers:
        raise SystemExit(f"Could not parse table from {IN_PATH}")

    site_col = _find_col(headers, ("сайт", "site", "website", "url"))
    if site_col < 0:
        raise SystemExit(f"No site column in {IN_PATH}")

    missing = [r for r in rows if len(r) > site_col and r[site_col].strip() in {"N/A", "—", ""}]

    out: list[str] = []
    out.append("## Агентства + Комьюнити — без сайта (N/A)")
    out.append("")
    out.append(f"Источник: фильтр из `{IN_PATH.relative_to(ROOT)}`.")
    out.append("")
    out.append(f"Всего без сайта: **{len(missing)}**.")
    out.append("")
    out.append("| " + " | ".join(headers) + " |")
    out.append("|" + "|".join(["---:"] + ["---"] * (len(headers) - 1)) + "|")
    for i, r in enumerate(missing, start=1):
        # renumber in output
        rr = list(r)
        rr[0] = str(i)
        out.append("| " + " | ".join(rr) + " |")
    out.append("")

    OUT_PATH.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote: {OUT_PATH} (rows={len(missing)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

