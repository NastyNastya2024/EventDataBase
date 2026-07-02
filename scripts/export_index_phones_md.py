#!/usr/bin/env python3
"""Выгрузка телефонов со страницы «Все остальные» (index) из final/final.md."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from export_index_contacts_md import (
    ROOT,
    _csv_field,
    read_index_rows,
)

DEFAULT_IN = ROOT / "final" / "final.md"
DEFAULT_OUT = ROOT / "final" / "phones_export_50.md"
DEFAULT_LIMIT = 50


def _norm_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or not digits.startswith("7"):
        return ""
    return digits


# Москва и МО: 495, 499, 496, 498; мобильные 79XXXXXXXXX
_MOSCOW_LANDLINE_PREFIXES = ("7495", "7499", "7496", "7498")


def _is_moscow_phone(phone: str) -> bool:
    if len(phone) != 11 or not phone.startswith("7"):
        return False
    if phone[1] == "9":
        return True
    return phone.startswith(_MOSCOW_LANDLINE_PREFIXES)


def build_phone_lines(
    rows: list[tuple[str, str, str, str, str]],
    *,
    limit: int,
    moscow_only: bool = True,
) -> list[tuple[str, str]]:
    """(нормализованный телефон 7..., org) — уникальные телефоны в порядке final.md."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    for org, _typ, site, kind, value in rows:
        if kind != "phone" or not value:
            continue
        raw = value.strip()
        if "XX" in raw.upper():
            continue
        key = _norm_phone(raw)
        if not key:
            continue
        if moscow_only and not _is_moscow_phone(key):
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append((key, org))
        if len(out) >= limit:
            break

    return out


def write_csv(out_path: Path, export_rows: list[tuple[str, str]]) -> None:
    import csv

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=",", quoting=csv.QUOTE_MINIMAL)
        w.writerow(["Телефон", "Организация"])
        w.writerows(export_rows)


def _phone_cell(phone: str) -> int | str:
    s = (phone or "").strip()
    if s.isdigit():
        return int(s)
    return s


def write_xlsx(out_path: Path, export_rows: list[tuple[str, str]]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Телефоны"
    ws.append(["Телефон", "Организация"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for phone, org in export_rows:
        ws.append([_phone_cell(phone), org])
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 55
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


def write_md(
    out_path: Path,
    export_rows: list[tuple[str, str]],
    source: Path,
    *,
    limit: int,
    moscow_only: bool,
) -> None:
    if moscow_only:
        title = "## Телефоны — Москва (кроме ивент-агентств)"
        scope = (
            "Только московские телефоны (495/499/496/498 и мобильные 9xx), без агентств."
        )
    else:
        title = "## Телефоны (кроме ивент-агентств)"
        scope = "Только телефоны, без агентств. Уникальные номера в порядке final.md."
    lines = [
        title,
        "",
        f"Источник: `{source.relative_to(ROOT)}` — страница «Все остальные» сайта.",
        scope,
        "Формат номера: цифры, начинается с 7, без +, пробелов и дефисов.",
        "",
        f"Контактов: **{len(export_rows)}**.",
        "",
        "Телефон, Организация",
    ]
    for phone, org in export_rows:
        lines.append(f"{phone},{_csv_field(org)}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DEFAULT_IN))
    ap.add_argument("--output", default=str(DEFAULT_OUT))
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument(
        "--all-phones",
        action="store_true",
        help="все российские телефоны (7...), без фильтра по Москве",
    )
    ap.add_argument("--csv", default="", help="доп. путь к .csv (по умолчанию: рядом с --output)")
    ap.add_argument("--xlsx", default="", help="доп. путь к .xlsx (по умолчанию: рядом с --output)")
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.is_absolute():
        in_path = ROOT / in_path
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    rows = read_index_rows(in_path)
    moscow_only = not args.all_phones
    export_rows = build_phone_lines(rows, limit=args.limit, moscow_only=moscow_only)
    write_md(out_path, export_rows, in_path, limit=args.limit, moscow_only=moscow_only)

    csv_path = Path(args.csv) if args.csv else out_path.with_suffix(".csv")
    if not csv_path.is_absolute():
        csv_path = ROOT / csv_path
    write_csv(csv_path, export_rows)

    xlsx_path = Path(args.xlsx) if args.xlsx else out_path.with_suffix(".xlsx")
    if not xlsx_path.is_absolute():
        xlsx_path = ROOT / xlsx_path
    try:
        write_xlsx(xlsx_path, export_rows)
        print(f"Wrote {xlsx_path}")
    except ImportError:
        print(f"Skip xlsx (openpyxl not installed): {xlsx_path}", file=__import__("sys").stderr)

    print(f"Wrote {out_path} ({len(export_rows)} rows)")
    print(f"Wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
