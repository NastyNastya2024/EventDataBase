#!/usr/bin/env python3
"""
Выгрузка строк из `all/all_no_focus.md` по наличию email в `all/all_contacts.md`.

Режимы:
- without_email: сайты, где email НЕ найден
- with_email: сайты, где email найден
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_ALL_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")

@dataclass(frozen=True)
class AllRow:
    n: int
    name: str
    typ: str
    site: str


def _clean_site(s: str) -> str:
    s = (s or "").strip()
    if not s or s.upper() == "N/A":
        return ""
    return s.rstrip("/")


def read_all_rows(path: Path) -> list[AllRow]:
    rows: list[AllRow] = []
    in_table = False
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith("| № |") and "Название" in line and "Сайт" in line:
            in_table = True
            continue
        if not in_table:
            continue
        m = _ALL_ROW_RE.match(line)
        if not m:
            continue
        n = int(m.group(1))
        rows.append(AllRow(n=n, name=m.group(2).strip(), typ=m.group(3).strip(), site=_clean_site(m.group(4))))
    return rows


def sites_with_email(contacts_md: Path) -> set[str]:
    sites: set[str] = set()
    in_table = False
    for line in contacts_md.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith("| Организация |") and "Вид контакта" in line and "Сайт" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|") or line.lstrip().startswith("|---"):
            continue
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) < 5:
            continue
        site = _clean_site(parts[1])
        kind = parts[2].casefold()
        if site and kind == "email":
            sites.add(site)
    return sites


def write_out(rows: list[AllRow], out_path: Path, *, title: str, source_line: str) -> None:
    out: list[str] = []
    out.append(title)
    out.append("")
    out.append(source_line)
    out.append("")
    out.append(f"Всего: **{len(rows)}**.")
    out.append("")
    out.append("| № | Название | Тип | Сайт |")
    out.append("|---:|---|---|---|")
    for i, r in enumerate(rows, start=1):
        out.append(f"| {i} | {r.name.replace('|','\\\\|')} | {r.typ} | {r.site or 'N/A'} |")
    out.append("")
    out_path.write_text("\n".join(out), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", default="all/all_no_focus.md")
    ap.add_argument("--contacts", default="all/all_contacts.md")
    ap.add_argument("--mode", default="with_email", choices=("with_email", "without_email"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    all_path = ROOT / args.all if not Path(args.all).is_absolute() else Path(args.all)
    contacts_path = ROOT / args.contacts if not Path(args.contacts).is_absolute() else Path(args.contacts)
    default_out = "all/all_with_email.md" if args.mode == "with_email" else "all/all_no_email.md"
    out_arg = args.out or default_out
    out_path = ROOT / out_arg if not Path(out_arg).is_absolute() else Path(out_arg)

    all_rows = read_all_rows(all_path)
    email_sites = sites_with_email(contacts_path) if contacts_path.exists() else set()

    if args.mode == "with_email":
        selected = [r for r in all_rows if r.site and r.site in email_sites]
        write_out(
            selected,
            out_path,
            title="## ALL — строки с email",
            source_line="Источник: `all/all_no_focus.md` ∩ сайты, где в `all/all_contacts.md` найден email.",
        )
    else:
        selected = [r for r in all_rows if r.site and r.site not in email_sites]
        write_out(
            selected,
            out_path,
            title="## ALL — строки без email",
            source_line="Источник: `all/all_no_focus.md` минус сайты, где в `all/all_contacts.md` найден email.",
        )
    print(f"Wrote: {out_path} (rows={len(selected)}, email_sites={len(email_sites)}, mode={args.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

