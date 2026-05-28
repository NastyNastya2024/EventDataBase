#!/usr/bin/env python3
"""
Заполняет колонку «Сайт» в markdown-таблице через DuckDuckGo (первая ссылка из выдачи).

Ориентировано на файлы вида `all/all_no_focus_na.md`, где в колонке «Сайт» стоит N/A.

Примеры:
  # тест на 20 запросов
  python scripts/ddg_enrich_sites.py --input all/all_no_focus_na.md --output all/all_no_focus_na.md --limit 20 --sleep 1.2

  # полный прогон (осторожно: долго)
  python scripts/ddg_enrich_sites.py --input all/all_no_focus_na.md --sleep 1.2
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from enrich_all_with_sites import ddg_first_result_url  # noqa: E402

CACHE_DEFAULT = ROOT / "scripts" / ".cache" / "ddg_sites_cache.json"

_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_EMPTY = frozenset({"", "—", "n/a", "N/A", "нет"})


@dataclass
class TableSpec:
    header_line_idx: int
    sep_line_idx: int
    name_col: int
    site_col: int
    lines: list[str]


def _split_cells(line: str) -> list[str]:
    inner = line.strip().strip("|")
    return [c.strip() for c in inner.split("|")]


def _find_col(headers: list[str], candidates: tuple[str, ...]) -> int:
    lowered = [h.casefold() for h in headers]
    for cand in candidates:
        c = cand.casefold()
        for i, h in enumerate(lowered):
            if c == h or c in h:
                return i
    return -1


def _escape_cell(s: str) -> str:
    return s.replace("|", "\\|")


def _needs_fill(site: str) -> bool:
    return site.strip() in _EMPTY


def parse_table(text: str) -> TableSpec | None:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not _TABLE_ROW_RE.match(line):
            continue
        headers = _split_cells(line)
        name_col = _find_col(headers, ("название", "организация", "компания", "name"))
        site_col = _find_col(headers, ("сайт", "site", "website"))
        if name_col < 0 or site_col < 0:
            continue
        if i + 1 >= len(lines) or not re.match(r"^\|[\s:|-]+\|\s*$", lines[i + 1]):
            continue
        return TableSpec(i, i + 1, name_col, site_col, lines)
    return None


def load_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_cache(path: Path, cache: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_table(path: Path, spec: TableSpec) -> None:
    body = "\n".join(spec.lines)
    if body and not body.endswith("\n"):
        body += "\n"
    path.write_text(body, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="DDG: заполнение сайтов для строк N/A")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default="")
    ap.add_argument("--cache", default=str(CACHE_DEFAULT))
    ap.add_argument("--sleep", type=float, default=1.2)
    ap.add_argument("--limit", type=int, default=0, help="Макс. число НОВЫХ запросов (0 = все)")
    ap.add_argument("--flush-every", type=int, default=25)
    ap.add_argument("--query-suffix", default="официальный сайт")
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.is_absolute():
        in_path = ROOT / in_path
    out_path = Path(args.output) if args.output else in_path
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    spec = parse_table(in_path.read_text(encoding="utf-8", errors="ignore"))
    if spec is None:
        print("Не найдена таблица с колонками «Название» и «Сайт».", file=sys.stderr)
        return 1

    cache_path = Path(args.cache)
    cache = load_cache(cache_path)

    queries = 0
    filled = 0

    for row_idx in range(spec.sep_line_idx + 1, len(spec.lines)):
        line = spec.lines[row_idx]
        if not _TABLE_ROW_RE.match(line) or line.lstrip().startswith("|---"):
            continue
        cells = _split_cells(line)
        if len(cells) <= max(spec.name_col, spec.site_col):
            continue
        name = cells[spec.name_col].strip()
        site = cells[spec.site_col].strip()
        if not name or not _needs_fill(site):
            continue

        if args.limit > 0 and queries >= args.limit:
            break

        key = name.casefold()
        if key in cache:
            found = cache[key]
        else:
            q = f"{name} {args.query_suffix}".strip()
            found = ddg_first_result_url(q) or ""
            cache[key] = found
            queries += 1
            print(f"  [{queries}] {name} -> {found or 'N/A'}", flush=True)
            if args.sleep > 0:
                time.sleep(args.sleep)

        if found:
            cells[spec.site_col] = found
            spec.lines[row_idx] = "| " + " | ".join(_escape_cell(c) for c in cells) + " |"
            filled += 1

        if args.flush_every > 0 and queries > 0 and queries % args.flush_every == 0:
            write_table(out_path, spec)
            save_cache(cache_path, cache)

    write_table(out_path, spec)
    save_cache(cache_path, cache)
    print(f"Готово: {out_path}")
    print(f"  запросов: {queries}, заполнено сайтов: {filled}, кэш: {cache_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

