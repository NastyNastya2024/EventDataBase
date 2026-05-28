#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _find_col(headers: list[str], candidates: tuple[str, ...]) -> int:
    lowered = [h.casefold().strip() for h in headers]
    for cand in candidates:
        c = cand.casefold()
        # exact match first
        for i, h in enumerate(lowered):
            if c == h:
                return i
        for i, h in enumerate(lowered):
            if c in h:
                return i
    return -1


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split()).casefold()


def _norm_url(u: str) -> str:
    u = (u or "").strip()
    if u.endswith("/"):
        u = u[:-1]
    return u


def read_table(path: Path) -> tuple[list[str], list[list[str]]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if not ln.startswith("|"):
            continue
        headers = _split_cells(ln)
        if i + 1 < len(lines) and _SEP_RE.match(lines[i + 1]):
            rows: list[list[str]] = []
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                if lines[j].lstrip().startswith("|---"):
                    j += 1
                    continue
                rows.append(_split_cells(lines[j]))
                j += 1
            return headers, rows
    raise SystemExit(f"Table not found: {path}")


def read_type_overrides(path: Path) -> dict[str, str]:
    """
    Reads a 2-column markdown table `Название | Тип организации`.
    Returns mapping: norm(name) -> type.
    """
    if not path.exists():
        return {}

    h, rows = read_table(path)
    name_col = _find_col(h, ("название", "организация", "компания", "name"))
    type_col = _find_col(h, ("тип организации", "тип", "type"))
    if min(name_col, type_col) < 0:
        raise SystemExit(f"Missing columns in overrides file: {path}")

    out: dict[str, str] = {}
    for r in rows:
        if len(r) <= max(name_col, type_col):
            continue
        name = r[name_col].strip()
        typ = r[type_col].strip()
        if not name or not typ:
            continue
        out[_norm(name)] = typ
    return out


def main() -> int:
    all_contacts = ROOT / "all" / "all_contacts.md"
    has_site = ROOT / "all" / "all_no_focus_has_site.md"
    out_path = ROOT / "final" / "final.md"
    overrides_path = ROOT / "final" / "org_type_overrides.md"

    # build (org, site) -> type mapping
    h, rows = read_table(has_site)
    name_col = _find_col(h, ("название", "организация", "компания", "name"))
    type_col = _find_col(h, ("тип", "type"))
    site_col = _find_col(h, ("сайт", "site", "website", "url"))
    if min(name_col, type_col, site_col) < 0:
        raise SystemExit("Missing columns in all_no_focus_has_site.md")

    typemap: dict[tuple[str, str], str] = {}
    for r in rows:
        if len(r) <= max(name_col, type_col, site_col):
            continue
        name = r[name_col].strip()
        typ = r[type_col].strip()
        site = r[site_col].strip()
        if not name or not typ or not site or site == "N/A":
            continue
        typemap[(_norm(name), _norm_url(site))] = typ

    overrides = read_type_overrides(overrides_path)

    # read contacts and write enriched output
    ch, crows = read_table(all_contacts)
    # Use strict header names to avoid matching "контакт" in "вид контакта"
    org_col = _find_col(ch, ("организация",))
    csite_col = _find_col(ch, ("сайт",))
    kind_col = _find_col(ch, ("вид контакта",))
    value_col = _find_col(ch, ("контакт",))
    desc_col = _find_col(ch, ("описание",))
    if min(org_col, csite_col, kind_col, value_col) < 0:
        raise SystemExit("Missing columns in all_contacts.md")

    out: list[str] = []
    out.append("## FINAL — контакты + тип организации")
    out.append("")
    out.append(
        "Источник: `all/all_contacts.md` + `all/all_no_focus_has_site.md` (тип по совпадению организации+сайта) "
        "+ `final/org_type_overrides.md` (ручные оверрайды по названию)."
    )
    out.append("")
    out.append("| Организация | Тип | Сайт | Вид контакта | Контакт |")
    out.append("|---|---|---|---|---|")

    written = 0
    for r in crows:
        if len(r) <= max(org_col, csite_col, kind_col, value_col, desc_col):
            continue
        org = r[org_col].strip()
        # drop Saint Petersburg entries from final dataset
        org_cf = org.casefold()
        if "санкт-петербург" in org_cf or "санкт петербург" in org_cf or "spb" in org_cf:
            continue
        site = _norm_url(r[csite_col].strip())
        kind = r[kind_col].strip()
        value = r[value_col].strip()
        if not (org and site and kind and value):
            continue
        norm_org = _norm(org)
        typ = overrides.get(norm_org) or typemap.get((norm_org, site), "N/A")
        out.append(
            "| "
            + " | ".join(
                s.replace("|", "\\|")
                for s in (
                    org,
                    typ,
                    site,
                    kind,
                    value,
                )
            )
            + " |"
        )
        written += 1

    out.append("")
    out_path.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote: {out_path} (rows={written}, typemap={len(typemap)}, overrides={len(overrides)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

