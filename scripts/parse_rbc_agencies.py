#!/usr/bin/env python3
"""Parse RBC Companies category listing (markdown dump) into agencies CSV/MD."""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    Path.home()
    / ".cursor/projects/Users-a1-Documents-GitHub-EventDataBase/uploads"
    / "751-razvlekatelnaya_deyatelnost-0.md"
)
OUT_DIR = ROOT / "data" / "agencies"
SOURCE_URL = "https://companies.rbc.ru/category/751-razvlekatelnaya_deyatelnost/"
CATEGORY = "Развлекательная деятельность"
CATEGORY_SLUG = "751-razvlekatelnaya_deyatelnost"

STATUS_RE = re.compile(
    r"^(Действует|Ликвидирована?|Есть решение ФНС о ликвидации)\s+(.+)$"
)
FIELD_RES = {
    "director": re.compile(
        r"^(Генеральный Директор|Исполнительный Директор|Директор|"
        r"Руководитель|Управляющий|Президент):(.+)$"
    ),
    "legal_address": re.compile(r"^Юридический адрес:(.+)$"),
    "registration_date": re.compile(r"^Дата регистрации:(.+)$"),
    "charter_capital": re.compile(r"^Уставной капитал:\s*(.+)$"),
    "inn": re.compile(r"^ИНН:(\d+)$"),
    "ogrn": re.compile(r"^ОГРН:(\d+)$"),
    "revenue": re.compile(r"^Выручка:(.+)$"),
    "revenue_growth": re.compile(r"^Темп прироста:(.+)$"),
}
CATEGORY_LINE = "Спорт, отдых и развлечения Развлекательная деятельность"

COLUMNS = [
    "id",
    "status",
    "display_name",
    "legal_name",
    "description",
    "director_title",
    "director_name",
    "legal_address",
    "registration_date",
    "charter_capital",
    "inn",
    "ogrn",
    "revenue",
    "revenue_growth",
    "category",
    "category_parent",
    "rbc_profile_url",
    "source_url",
    "source_page",
]


def parse_listing(text: str) -> list[dict]:
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.strip() == "# Компании в категории Развлекательная деятельность":
            start = i + 1
            break

    companies: list[dict] = []
    i = start
    # skip intro paragraph
    while i < len(lines) and not STATUS_RE.match(lines[i].strip()):
        i += 1

    while i < len(lines):
        line = lines[i].strip()
        m = STATUS_RE.match(line)
        if not m:
            if line.startswith("1 2 3") or line == "Вперед":
                break
            i += 1
            continue

        status, display_name = m.group(1), m.group(2).strip()
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        legal_name = lines[i].strip() if i < len(lines) else ""
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1

        description = ""
        if i < len(lines) and lines[i].strip() == CATEGORY_LINE.strip():
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if not nxt:
                    i += 1
                    continue
                if STATUS_RE.match(nxt) or nxt == CATEGORY_LINE.strip():
                    break
                if any(
                    nxt.startswith(prefix)
                    for prefix in (
                        "Генеральный Директор:",
                        "Исполнительный Директор:",
                        "Директор:",
                        "Руководитель:",
                        "Управляющий:",
                        "Президент:",
                        "Юридический адрес:",
                    )
                ):
                    break
                description = (description + " " + nxt).strip() if description else nxt
                i += 1

        row = {
            "status": status,
            "display_name": display_name,
            "legal_name": legal_name,
            "description": description,
            "director_title": "",
            "director_name": "",
            "legal_address": "",
            "registration_date": "",
            "charter_capital": "",
            "inn": "",
            "ogrn": "",
            "revenue": "",
            "revenue_growth": "",
            "category": CATEGORY,
            "category_parent": "Спорт, отдых и развлечения",
            "rbc_profile_url": "",
            "source_url": SOURCE_URL,
            "source_page": "1",
        }

        while i < len(lines):
            raw = lines[i]
            nxt = raw.strip()
            if not nxt:
                i += 1
                continue
            if STATUS_RE.match(nxt):
                break
            if nxt.startswith("1 2 3") or nxt == "Вперед":
                i = len(lines)
                break

            dm = FIELD_RES["director"].match(nxt)
            if dm:
                row["director_title"] = dm.group(1)
                row["director_name"] = dm.group(2).strip()
                i += 1
                continue

            for key in (
                "legal_address",
                "registration_date",
                "charter_capital",
                "inn",
                "ogrn",
                "revenue",
                "revenue_growth",
            ):
                fm = FIELD_RES[key].match(nxt)
                if fm:
                    row[key] = fm.group(1).strip().replace("\\", "")
                    break
            i += 1

        if row["inn"]:
            row["rbc_profile_url"] = (
                f"https://companies.rbc.ru/search/?query={row['inn']}"
            )
        companies.append(row)

    for n, row in enumerate(companies, start=1):
        row["id"] = str(n)

    return companies


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
        w.writeheader()
        w.writerows(rows)


def write_md(path: Path, rows: list[dict], total_in_category: str) -> None:
    lines = [
        f"## РБК Компании — {CATEGORY}",
        f"Источник: `{SOURCE_URL}`",
        "",
        f"На странице каталога: **{len(rows)}** компаний (страница 1). "
        f"Всего в категории: {total_in_category}.",
        "",
        "| № | Статус | Название | ИНН | ОГРН | Выручка | Прирост | Директор | Адрес |",
        "|---:|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        name = r["display_name"] or r["legal_name"]
        if r["rbc_profile_url"]:
            name_cell = f"[{name}]({r['rbc_profile_url']})"
        else:
            name_cell = name
        director = (
            f"{r['director_title']}: {r['director_name']}"
            if r["director_name"]
            else ""
        )
        addr = (r["legal_address"][:60] + "…") if len(r["legal_address"]) > 60 else r["legal_address"]
        lines.append(
            f"| {r['id']} | {r['status']} | {name_cell} | {r['inn']} | {r['ogrn']} | "
            f"{r['revenue']} | {r['revenue_growth']} | {director} | {addr} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = p.parse_args()

    text = args.input.read_text(encoding="utf-8")
    if text.startswith("Source URL:"):
        text = "\n".join(text.splitlines()[1:])

    total_match = re.search(
        r"содержится\s+([\d\s]+)\s+компаний", text.replace("\\", "")
    )
    total_in_category = total_match.group(1).replace(" ", " ") if total_match else "—"

    rows = parse_listing(text)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    base = f"rbc_{CATEGORY_SLUG}"
    csv_path = args.out_dir / f"{base}.csv"
    md_path = args.out_dir / f"{base}.md"

    write_csv(csv_path, rows)
    write_md(md_path, rows, total_in_category)

    print(f"Parsed {len(rows)} companies -> {csv_path}")


if __name__ == "__main__":
    main()
