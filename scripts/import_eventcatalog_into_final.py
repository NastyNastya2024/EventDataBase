#!/usr/bin/env python3
"""Импорт event-агентств EventCatalog в final/final.md."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "data" / "agencies" / "eventcatalog_event_agencies.csv"
FINAL_PATH = ROOT / "final" / "final.md"

_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")
ORG_TYPE = "ивент агентство"
_SOURCE_NOTE = "+ `data/agencies/eventcatalog_event_agencies.csv` (eventcatalog.ru)."


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _escape_cell(s: str) -> str:
    return (s or "").replace("|", "\\|")


def _norm_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if u.endswith("/"):
        u = u[:-1]
    return u


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


def read_agency_rows(path: Path) -> list[tuple[str, str, str, str, str]]:
    out: list[tuple[str, str, str, str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            name = (r.get("agency_name") or "").strip()
            if not name:
                continue
            site = _norm_url(r.get("website") or "") or _norm_url(
                r.get("agency_url") or ""
            )
            if not site:
                continue

            phone = (r.get("phone") or "").strip()
            email = (r.get("email") or "").strip()
            instagram = _norm_url(r.get("instagram") or "")
            telegram = _norm_url(r.get("telegram") or "")
            whatsapp = _norm_url(r.get("whatsapp") or "")
            vk = _norm_url(r.get("vk") or "")

            if phone:
                out.append((name, ORG_TYPE, site, "phone", phone))
            if email:
                out.append((name, ORG_TYPE, site, "email", email))
            for kind, val in (
                ("social", instagram),
                ("social", telegram),
                ("social", whatsapp),
                ("social", vk),
            ):
                if val:
                    out.append((name, ORG_TYPE, site, kind, val))

            if not phone and not email and not any(
                (instagram, telegram, whatsapp, vk)
            ):
                catalog = _norm_url(r.get("agency_url") or "")
                if catalog:
                    out.append((name, ORG_TYPE, site, "social", catalog))
    return out


def _ensure_source_note(header_lines: list[str]) -> None:
    if len(header_lines) < 3 or not header_lines[2].startswith("Источник:"):
        return
    if _SOURCE_NOTE not in header_lines[2]:
        header_lines[2] = header_lines[2].rstrip(".") + " " + _SOURCE_NOTE


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", type=Path, default=DEFAULT_CSV)
    args = ap.parse_args()

    if not args.csv.exists():
        raise SystemExit(f"CSV not found: {args.csv}")

    header_lines, existing = read_final_rows(FINAL_PATH)
    seen = {tuple(r) for r in existing}
    agency_rows = read_agency_rows(args.csv)
    added = 0
    for row in agency_rows:
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
    print(f"agency rows from csv: {len(agency_rows)}")
    print(f"added to final: {added}")
    print(f"total rows in final: {len(existing)}")
    print(f"wrote: {FINAL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
