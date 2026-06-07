#!/usr/bin/env python3
"""Импорт event-агентств из list-org (xlsx/csv) в final/final.md."""

from __future__ import annotations

import argparse
import csv
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "data" / "agencies" / "list_org_event_agencies.csv"
FINAL_PATH = ROOT / "final" / "final.md"

_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
ORG_TYPE = "ивент агентство"
_SOURCE_NOTE = "+ `data/agencies/list_org_event_agencies.csv` (list-org.com, коллеги)."
_FALLBACK_SITE = "коллеги"


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _escape_cell(s: str) -> str:
    return (s or "").replace("|", "\\|")


def _norm_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        if re.match(r"^www\.", u, re.I):
            u = "https://" + u
        elif "." in u and " " not in u:
            u = "https://" + u
    if u.endswith("/"):
        u = u[:-1]
    return u


def _resolve_site(site: str, list_org_url: str) -> str:
    site = _norm_url(site)
    if site:
        return site
    list_org_url = _norm_url(list_org_url)
    if list_org_url:
        return list_org_url
    return _FALLBACK_SITE


def _xlsx_cell_value(cell: ET.Element, shared: list[str]) -> str:
    t = cell.attrib.get("t")
    if t == "inlineStr":
        is_el = cell.find("m:is", _NS)
        if is_el is not None:
            return "".join((t_el.text or "") for t_el in is_el.findall(".//m:t", _NS))
        return ""
    v = cell.find("m:v", _NS)
    if v is None or v.text is None:
        return ""
    if t == "s":
        return shared[int(v.text)]
    return v.text


def read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(".//m:si", _NS):
                shared.append("".join((t.text or "") for t in si.findall(".//m:t", _NS)))

        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid_map = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
        sheet = wb.find(".//m:sheet", _NS)
        rid = sheet.attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]
        target = rid_map[rid]
        if not target.startswith("xl/"):
            target = "xl/" + target

        root = ET.fromstring(z.read(target))
        matrix: list[list[str]] = []
        for row in root.findall(".//m:row", _NS):
            cells: dict[str, str] = {}
            for c in row.findall("m:c", _NS):
                ref = c.attrib.get("r", "")
                col = "".join(ch for ch in ref if ch.isalpha())
                cells[col] = _xlsx_cell_value(c, shared)
            if not cells:
                continue
            max_col_idx = max(ord(k) - 65 for k in cells)
            matrix.append([cells.get(chr(65 + i), "") for i in range(max_col_idx + 1)])

    if not matrix:
        return []

    header = matrix[0]
    idx = {h: i for i, h in enumerate(header)}
    out: list[dict[str, str]] = []
    for row in matrix[1:]:
        def get(name: str) -> str:
            i = idx.get(name)
            if i is None or i >= len(row):
                return ""
            return (row[i] or "").strip()

        name = get("Наименование")
        if not name:
            continue
        out.append(
            {
                "name": name,
                "list_org_url": get("Ссылка на www.list-org.com"),
                "phone": get("Телефон (один из)"),
                "email": get("E-mail"),
                "site": get("Сайт"),
                "address": get("Юридический адрес"),
                "inn": get("ИНН"),
                "ogrn": get("ОГРН"),
            }
        )
    return out


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return [
            {
                "name": (r.get("name") or "").strip(),
                "list_org_url": (r.get("list_org_url") or "").strip(),
                "phone": (r.get("phone") or "").strip(),
                "email": (r.get("email") or "").strip(),
                "site": (r.get("site") or "").strip(),
                "address": (r.get("address") or "").strip(),
                "inn": (r.get("inn") or "").strip(),
                "ogrn": (r.get("ogrn") or "").strip(),
            }
            for r in csv.DictReader(f, delimiter=";")
            if (r.get("name") or "").strip()
        ]


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


def agency_rows(records: list[dict[str, str]]) -> list[tuple[str, str, str, str, str]]:
    out: list[tuple[str, str, str, str, str]] = []
    for r in records:
        name = r["name"]
        site = _resolve_site(r["site"], r["list_org_url"])
        phone = r["phone"]
        email = r["email"]
        address = r["address"]

        if phone:
            out.append((name, ORG_TYPE, site, "phone", phone))
        if email:
            out.append((name, ORG_TYPE, site, "email", email))
        if address and not phone and not email:
            out.append((name, ORG_TYPE, site, "address", address))
        if not phone and not email and not address:
            out.append((name, ORG_TYPE, site, "social", "list-org.com"))
    return out


def write_csv(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["name", "list_org_url", "phone", "email", "site", "address", "inn", "ogrn"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";", lineterminator="\n")
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k, "") for k in fields})


def _ensure_source_note(header_lines: list[str]) -> None:
    if len(header_lines) < 3 or not header_lines[2].startswith("Источник:"):
        return
    if _SOURCE_NOTE not in header_lines[2]:
        header_lines[2] = header_lines[2].rstrip(".") + " " + _SOURCE_NOTE


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=DEFAULT_CSV,
        help="CSV или XLSX с list-org",
    )
    ap.add_argument(
        "--export-csv",
        type=Path,
        default=DEFAULT_CSV,
        help="Куда сохранить CSV при импорте из XLSX",
    )
    args = ap.parse_args()

    if not args.source.exists():
        raise SystemExit(f"Source not found: {args.source}")

    if args.source.suffix.lower() == ".xlsx":
        records = read_xlsx_rows(args.source)
        write_csv(args.export_csv, records)
        print(f"exported csv: {args.export_csv} ({len(records)} rows)")
    else:
        records = read_csv_rows(args.source)

    header_lines, existing = read_final_rows(FINAL_PATH)
    seen = {tuple(r) for r in existing}
    new_rows = agency_rows(records)
    added = 0
    for row in new_rows:
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
    print(f"agency rows from source: {len(new_rows)}")
    print(f"added to final: {added}")
    print(f"total rows in final: {len(existing)}")
    print(f"wrote: {FINAL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
