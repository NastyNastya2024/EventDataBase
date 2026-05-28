#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGET = ROOT / "all" / "all_agencies_and_communities.md"

_MD_LINK_RE = re.compile(r"^\[([^\]]+)\]\(([^)]+)\)$")
_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")


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
    # domain without scheme
    if re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/.*)?", s) and not s.startswith(("http://", "https://")):
        s = "https://" + s
    if not s.startswith(("http://", "https://")):
        return ""
    return s


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


def _norm_name(name: str) -> str:
    # keep simple: casefold + collapse whitespace
    return " ".join((name or "").strip().split()).casefold()


def collect_sites_from_md(path: Path, out: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    for headers, rows in iter_md_tables(text):
        name_col = _find_col(headers, ("агентство", "компания", "организация", "название", "name", "community", "комьюнити"))
        site_col = _find_col(headers, ("сайт", "site", "website", "url"))
        if name_col < 0 or site_col < 0:
            continue
        for r in rows:
            if len(r) <= max(name_col, site_col):
                continue
            name = _clean_cell(r[name_col])
            site = _clean_url(r[site_col])
            if not name or not site:
                continue
            k = _norm_name(name)
            if k not in out:
                out[k] = site


def collect_sites_from_csv(path: Path, out: dict[str, str]) -> None:
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return
        headers_norm = [h.strip().casefold() for h in headers]
        # guess columns
        def find_csv_col(cands: tuple[str, ...]) -> int:
            for cand in cands:
                c = cand.casefold()
                for i, h in enumerate(headers_norm):
                    if c == h or c in h:
                        return i
            return -1

        name_col = find_csv_col(("агентство", "компания", "организация", "название", "name", "community", "комьюнити"))
        site_col = find_csv_col(("сайт", "site", "website", "url"))
        if name_col < 0 or site_col < 0:
            return
        for row in reader:
            if len(row) <= max(name_col, site_col):
                continue
            name = (row[name_col] or "").strip()
            site = _clean_url(row[site_col])
            if not name or not site:
                continue
            k = _norm_name(name)
            if k not in out:
                out[k] = site


@dataclass
class Item:
    kind: str
    name: str
    site: str = ""


def read_target_items(path: Path) -> list[Item]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    for headers, rows in iter_md_tables(text):
        kind_col = _find_col(headers, ("тип", "type"))
        name_col = _find_col(headers, ("название", "name"))
        site_col = _find_col(headers, ("сайт", "site", "website", "url"))
        if kind_col < 0 or name_col < 0:
            continue
        items: list[Item] = []
        for r in rows:
            if len(r) <= max(kind_col, name_col):
                continue
            kind = _clean_cell(r[kind_col]) if kind_col >= 0 else ""
            name = _clean_cell(r[name_col]) if name_col >= 0 else ""
            site = _clean_url(r[site_col]) if (site_col >= 0 and len(r) > site_col) else ""
            if name and kind:
                items.append(Item(kind=kind, name=name, site=site))
        if items:
            return items
    raise SystemExit(f"Could not parse items from {path}")


def write_target(path: Path, items: list[Item]) -> None:
    out: list[str] = []
    out.append("## Агентства + Комьюнити — единый список")
    out.append("")
    out.append("Источник: объединение `all/all_agencies.md` и `all/all_communities.md` + сайты из документов репозитория.")
    out.append("")
    out.append("| № | Тип | Название | Сайт |")
    out.append("|---:|---|---|---|")
    for i, it in enumerate(items, start=1):
        name = it.name.replace("|", "\\|")
        site = it.site or "N/A"
        out.append(f"| {i} | {it.kind} | {name} | {site} |")
    out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


def main() -> int:
    if not TARGET.exists():
        raise SystemExit(f"Missing: {TARGET}")

    items = read_target_items(TARGET)

    sites: dict[str, str] = {}

    # Prefer consolidated “all” tables first (often already curated)
    preferred_md = [
        ROOT / "all" / "all_with_sites.md",
        ROOT / "all" / "all_no_focus_has_site.md",
    ]
    for p in preferred_md:
        if p.exists():
            collect_sites_from_md(p, sites)

    # Then scan data/ and all/ for any tables with site columns
    for p in sorted((ROOT / "data").rglob("*.md")):
        collect_sites_from_md(p, sites)
    for p in sorted((ROOT / "data").rglob("*.csv")):
        collect_sites_from_csv(p, sites)
    for p in sorted((ROOT / "all").glob("*.md")):
        if p.resolve() == TARGET.resolve():
            continue
        collect_sites_from_md(p, sites)

    filled = 0
    for it in items:
        if it.site:
            continue
        k = _norm_name(it.name)
        site = sites.get(k, "")
        if site:
            it.site = site
            filled += 1

    write_target(TARGET, items)
    print(f"Updated: {TARGET} (filled={filled}, total={len(items)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

