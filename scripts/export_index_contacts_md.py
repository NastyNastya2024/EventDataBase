#!/usr/bin/env python3
"""Выгрузка контактов со страницы «Все остальные» (index) в MD: email | организация - контакт."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "final" / "final.md"
DEFAULT_OUT = ROOT / "final" / "all_contacts_export.md"

_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def find_table(lines: list[str]) -> tuple[list[str], int]:
    for i, ln in enumerate(lines):
        if not ln.startswith("|"):
            continue
        headers = _split_cells(ln)
        if "Организация" in headers and "Вид контакта" in headers and "Контакт" in headers:
            if i + 1 < len(lines) and _SEP_RE.match(lines[i + 1]):
                return headers, i + 2
    raise SystemExit("Contacts table not found")


def col(headers: list[str], name: str) -> int:
    name_cf = name.casefold()
    for i, h in enumerate(headers):
        if h.casefold() == name_cf:
            return i
    raise SystemExit(f"Missing column: {name}")


def org_key(org: str, site: str) -> tuple[str, str]:
    site = (site or "").strip().rstrip("/")
    return org.strip(), site


def read_index_rows(path: Path) -> list[tuple[str, str, str, str, str]]:
    from org_type_groups import is_event_agency

    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    headers, start = find_table(lines)
    org_i = col(headers, "Организация")
    typ_i = col(headers, "Тип")
    site_i = col(headers, "Сайт")
    kind_i = col(headers, "Вид контакта")
    val_i = col(headers, "Контакт")

    rows: list[tuple[str, str, str, str, str]] = []
    for ln in lines[start:]:
        if not ln.startswith("|"):
            break
        if _SEP_RE.match(ln):
            continue
        cells = _split_cells(ln)
        if len(cells) <= max(org_i, typ_i, site_i, kind_i, val_i):
            continue
        org_type = cells[typ_i]
        if is_event_agency(org_type):
            continue
        rows.append(
            (
                cells[org_i],
                org_type,
                cells[site_i],
                cells[kind_i],
                cells[val_i],
            )
        )
    return rows


def _norm_email(raw: str) -> str:
    e = (raw or "").strip()
    if e.startswith("%20"):
        e = e[3:]
    return e


def _email_key(raw: str) -> str:
    return _norm_email(raw).casefold()


def build_export_lines(rows: list[tuple[str, str, str, str, str]]) -> list[tuple[str, str]]:
    """(email, org) — одна строка на уникальный email."""
    emails_by_org: dict[tuple[str, str], list[str]] = {}
    org_names: dict[tuple[str, str], str] = {}

    for org, _typ, site, kind, value in rows:
        key = org_key(org, site)
        org_names.setdefault(key, org)
        if kind != "email" or not value:
            continue
        norm = _norm_email(value)
        if not norm or "@" not in norm:
            continue
        bucket = emails_by_org.setdefault(key, [])
        if norm not in bucket:
            bucket.append(norm)

    by_email: dict[str, tuple[str, str]] = {}
    for key, emails in emails_by_org.items():
        if not emails:
            continue
        primary_email = sorted(emails, key=str.casefold)[0]
        org = org_names[key]
        ek = _email_key(primary_email)
        prev = by_email.get(ek)
        if prev is None or org.casefold() < prev[1].casefold():
            by_email[ek] = (primary_email, org)

    out = list(by_email.values())
    out.sort(key=lambda r: (_email_key(r[0]), r[1].casefold()))
    return out


def _csv_field(s: str) -> str:
    s = (s or "").replace("\n", " ").strip()
    if "," in s or '"' in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def write_md(out_path: Path, export_rows: list[tuple[str, str]], source: Path) -> None:
    lines = [
        "## Организации с email (кроме ивент-агентств)",
        "",
        f"Источник: `{source.relative_to(ROOT)}` — страница «Все остальные» сайта.",
        "Только организации, у которых есть email. Одна строка = один уникальный email.",
        "",
        f"Организаций: **{len(export_rows)}**.",
        "",
        "Email, Организация",
    ]
    for email, org in export_rows:
        lines.append(f"{_csv_field(email)},{_csv_field(org)}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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

    rows = read_index_rows(in_path)
    export_rows = build_export_lines(rows)
    write_md(out_path, export_rows, in_path)
    print(f"Wrote {out_path} ({len(export_rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
