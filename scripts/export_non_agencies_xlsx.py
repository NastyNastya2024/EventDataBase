#!/usr/bin/env python3
"""Excel: все организации из final.md (кроме ивент-агентств), одна строка = одна организация."""

from __future__ import annotations

import argparse
import csv
import re
from collections import OrderedDict
from pathlib import Path

from export_index_contacts_md import ROOT, read_index_rows, org_key

DEFAULT_IN = ROOT / "final" / "final.md"
DEFAULT_OUT = ROOT / "final" / "non_agencies_export.xlsx"


def _norm_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    return digits


def _norm_email(raw: str) -> str:
    e = (raw or "").strip()
    if e.startswith("%20"):
        e = e[3:]
    return e


def _phone_cell(phone: str) -> int | None:
    s = (phone or "").strip()
    if s.isdigit():
        return int(s)
    return None


def build_orgs(rows: list[tuple[str, str, str, str, str]]) -> list[dict[str, str]]:
    orgs: OrderedDict[tuple[str, str], dict[str, str | list[str]]] = OrderedDict()

    for org, typ, site, kind, value in rows:
        key = org_key(org, site)
        if key not in orgs:
            orgs[key] = {
                "name": org,
                "site": site,
                "phones": [],
                "emails": [],
            }
        rec = orgs[key]
        val = (value or "").strip()
        if not val or "XX" in val.upper():
            continue
        if kind == "phone":
            norm = _norm_phone(val)
            if norm and norm not in rec["phones"]:
                rec["phones"].append(norm)
        elif kind == "email":
            norm = _norm_email(val)
            if norm and "@" in norm and norm not in rec["emails"]:
                rec["emails"].append(norm)

    out: list[dict[str, str]] = []
    for rec in orgs.values():
        phones: list[str] = rec["phones"]  # type: ignore[assignment]
        emails: list[str] = rec["emails"]  # type: ignore[assignment]
        out.append(
            {
                "org": str(rec["name"]),
                "phone": phones[0] if phones else "",
                "email": sorted(emails, key=str.casefold)[0] if emails else "",
                "site": str(rec["site"]),
            }
        )
    return out


FIELDS = ["Название компании", "Название сделки", "Телефон", "Email", "Сайт"]


def write_csv(out_path: Path, rows: list[dict[str, str]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter=",", quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "Название компании": r["org"],
                    "Название сделки": r["org"],
                    "Телефон": r["phone"],
                    "Email": r["email"],
                    "Сайт": r["site"],
                }
            )


def write_xlsx(out_path: Path, rows: list[dict[str, str]]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Организации"
    ws.append(FIELDS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for r in rows:
        phone = _phone_cell(r["phone"])
        ws.append(
            [
                r["org"],
                r["org"],
                phone if phone is not None else "",
                r["email"],
                r["site"],
            ]
        )
    ws.column_dimensions["A"].width = 52
    ws.column_dimensions["B"].width = 52
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 36
    ws.column_dimensions["E"].width = 40
    ws.auto_filter.ref = f"A1:E{len(rows) + 1}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DEFAULT_IN))
    ap.add_argument("--output", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.is_absolute():
        in_path = ROOT / in_path
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    rows = build_orgs(read_index_rows(in_path))
    write_csv(out_path.with_suffix(".csv"), rows)
    write_xlsx(out_path, rows)

    mid = len(rows) // 2
    for i, part in enumerate([rows[:mid], rows[mid:]], 1):
        part_path = out_path.with_name(f"{out_path.stem}_{i}{out_path.suffix}")
        write_csv(part_path.with_suffix(".csv"), part)
        write_xlsx(part_path, part)
        print(f"Wrote {part_path} ({len(part)} rows)")
        print(f"Wrote {part_path.with_suffix('.csv')}")

    print(f"Wrote {out_path} ({len(rows)} rows)")
    print(f"Wrote {out_path.with_suffix('.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
