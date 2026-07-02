#!/usr/bin/env python3
"""База по корпорациям из final/final.md: одна строка = одна организация."""

from __future__ import annotations

import argparse
import csv
import re
from collections import OrderedDict
from pathlib import Path

from export_index_contacts_md import ROOT, _csv_field, org_key, read_index_rows
from org_type_groups import classify

DEFAULT_IN = ROOT / "final" / "final.md"
DEFAULT_OUT = ROOT / "final" / "corporations_db.md"
CORP_GROUP = "Корпорации и финансы"


def _norm_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    return digits


def _phone_cell(phone: str) -> int | str:
    s = (phone or "").strip()
    return int(s) if s.isdigit() else s


def build_corporations(
    rows: list[tuple[str, str, str, str, str]],
    *,
    limit: int | None,
) -> list[dict[str, str]]:
    orgs: OrderedDict[tuple[str, str], dict[str, str | list[str]]] = OrderedDict()

    for org, typ, site, kind, value in rows:
        if classify(typ) != CORP_GROUP:
            continue
        key = org_key(org, site)
        if key not in orgs:
            orgs[key] = {
                "name": org,
                "type": typ,
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
        elif kind == "email" and "@" in val:
            if val not in rec["emails"]:
                rec["emails"].append(val)

    out: list[dict[str, str]] = []
    for rec in orgs.values():
        phones: list[str] = rec["phones"]  # type: ignore[assignment]
        if not phones:
            continue
        emails: list[str] = rec["emails"]  # type: ignore[assignment]
        out.append(
            {
                "phone": phones[0],
                "org": str(rec["name"]),
                "type": str(rec["type"]),
                "site": str(rec["site"]),
                "email": sorted(emails, key=str.casefold)[0] if emails else "",
            }
        )
        if limit is not None and len(out) >= limit:
            break

    return out


def write_csv(out_path: Path, rows: list[dict[str, str]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["Телефон", "Организация", "Тип", "Сайт", "Email"]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=fields,
            delimiter=",",
            quoting=csv.QUOTE_MINIMAL,
        )
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "Телефон": r["phone"],
                    "Организация": r["org"],
                    "Тип": r["type"],
                    "Сайт": r["site"],
                    "Email": r["email"],
                }
            )


def write_xlsx(out_path: Path, rows: list[dict[str, str]]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Корпорации"
    headers = ["Телефон", "Организация", "Тип", "Сайт", "Email"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for r in rows:
        ws.append(
            [
                _phone_cell(r["phone"]),
                r["org"],
                r["type"],
                r["site"],
                r["email"],
            ]
        )
    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 48
    ws.column_dimensions["C"].width = 28
    ws.column_dimensions["D"].width = 36
    ws.column_dimensions["E"].width = 32
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


def write_md(out_path: Path, rows: list[dict[str, str]], source: Path, limit: int | None) -> None:
    limit_note = f", не более **{limit}**" if limit else ""
    lines = [
        "## База по корпорациям",
        "",
        f"Источник: `{source.relative_to(ROOT)}` — категория «{CORP_GROUP}».",
        "Одна строка = одна организация (не ивент-агентство). Телефон — первый из final.md.",
        "Формат номера: цифры, начинается с 7, без +, пробелов и дефисов.",
        "",
        f"Организаций: **{len(rows)}**{limit_note}.",
        "",
        "Телефон, Организация, Тип, Сайт, Email",
    ]
    for r in rows:
        lines.append(
            ",".join(
                [
                    r["phone"],
                    _csv_field(r["org"]),
                    _csv_field(r["type"]),
                    _csv_field(r["site"]),
                    _csv_field(r["email"]),
                ]
            )
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DEFAULT_IN))
    ap.add_argument("--output", default=str(DEFAULT_OUT))
    ap.add_argument(
        "--limit",
        type=int,
        default=100,
        help="макс. организаций (0 = без лимита)",
    )
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.is_absolute():
        in_path = ROOT / in_path
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    limit = None if args.limit <= 0 else args.limit
    rows = build_corporations(read_index_rows(in_path), limit=limit)
    write_md(out_path, rows, in_path, limit)
    write_csv(out_path.with_suffix(".csv"), rows)
    try:
        write_xlsx(out_path.with_suffix(".xlsx"), rows)
        print(f"Wrote {out_path.with_suffix('.xlsx')}")
    except ImportError:
        print(f"Skip xlsx (openpyxl not installed): {out_path.with_suffix('.xlsx')}")

    print(f"Wrote {out_path} ({len(rows)} rows)")
    print(f"Wrote {out_path.with_suffix('.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
