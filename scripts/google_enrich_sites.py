#!/usr/bin/env python3
"""
Подставляет в markdown-таблицу сайт из первой ссылки Google-выдачи.

Примеры:
  # Организации №1–140 (только строки с N/A в колонке «Сайт»)
  export SERPER_API_KEY=ваш_ключ   # https://serper.dev — бесплатно ~2500 запросов
  python scripts/google_enrich_sites.py \\
    --input data/organizations/organizations_1_140_sites_phones.md \\
    --output data/organizations/organizations_1_140_sites_phones.md

  # all.md — добавить колонку «Сайт», локальные данные, затем Serper для N/A
  python scripts/google_enrich_sites.py --input all/all.md --output all/all.md --backend serper

  # Тест на 5 Serper-запросах
  python scripts/google_enrich_sites.py --input all/all.md --limit 5 --sleep 0.3

  # Без API (прямой scrape — часто блокируется с датацентров)
  python scripts/google_enrich_sites.py --backend scrape --limit 3
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

from google_search import build_query, google_first_url  # noqa: E402

CACHE_PATH_DEFAULT = ROOT / "scripts" / ".cache" / "google_sites_cache.json"

_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_EMPTY_SITE = frozenset({"", "—", "n/a", "N/A", "нет"})


@dataclass
class TableSpec:
    header_line_idx: int
    sep_line_idx: int
    name_col: int
    site_col: int
    lines: list[str]


def _split_cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def _find_col(headers: list[str], candidates: tuple[str, ...]) -> int:
    lowered = [h.casefold() for h in headers]
    for cand in candidates:
        c = cand.casefold()
        for i, h in enumerate(lowered):
            if c == h or c in h:
                return i
    return -1


def ensure_site_column(spec: TableSpec) -> None:
    """Добавляет колонку «Сайт» (после «Тип», иначе в конец) во все строки таблицы."""
    header_cells = _split_cells(spec.lines[spec.header_line_idx])
    site_col = _find_col(header_cells, ("сайт", "site", "website", "официальный сайт"))
    if site_col >= 0:
        spec.site_col = site_col
        return

    typ_col = _find_col(header_cells, ("тип", "type"))
    insert_at = typ_col + 1 if typ_col >= 0 else len(header_cells)
    header_cells.insert(insert_at, "Сайт")
    spec.lines[spec.header_line_idx] = "| " + " | ".join(header_cells) + " |"

    n = len(header_cells)
    sep_cells = ["---:"] + ["---"] * (n - 1)
    spec.lines[spec.sep_line_idx] = "| " + " | ".join(sep_cells) + " |"
    spec.site_col = insert_at

    for row_idx in range(spec.sep_line_idx + 1, len(spec.lines)):
        line = spec.lines[row_idx]
        if not _TABLE_ROW_RE.match(line):
            continue
        cells = _split_cells(line)
        if not cells or cells[0].startswith("---"):
            continue
        while len(cells) < insert_at:
            cells.append("")
        if len(cells) == insert_at:
            cells.append("N/A")
        elif len(cells) > insert_at and not cells[insert_at].strip():
            cells[insert_at] = "N/A"
        spec.lines[row_idx] = "| " + " | ".join(_escape_cell(c) for c in cells) + " |"


def parse_markdown_table(text: str) -> TableSpec | None:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not _TABLE_ROW_RE.match(line):
            continue
        cells = _split_cells(line)
        if not cells:
            continue
        name_col = _find_col(cells, ("организация", "название", "компания", "name", "бренд"))
        if name_col < 0:
            continue
        if i + 1 >= len(lines) or not re.match(r"^\|[\s:|-]+\|\s*$", lines[i + 1]):
            continue
        site_col = _find_col(cells, ("сайт", "site", "website", "официальный сайт"))
        spec = TableSpec(
            header_line_idx=i,
            sep_line_idx=i + 1,
            name_col=name_col,
            site_col=site_col,
            lines=lines,
        )
        if site_col < 0:
            ensure_site_column(spec)
        return spec
    return None


def fill_sites_from_local_index(
    spec: TableSpec,
    site_index: dict[str, str],
    contact_index: dict[str, str],
) -> int:
    from enrich_all_with_sites import _canon_name, _norm_name

    filled = 0
    for row_idx in range(spec.sep_line_idx + 1, len(spec.lines)):
        line = spec.lines[row_idx]
        if not _TABLE_ROW_RE.match(line):
            continue
        cells = _split_cells(line)
        if len(cells) <= max(spec.name_col, spec.site_col):
            continue
        if not _needs_fill(cells[spec.site_col].strip(), force=False):
            continue
        name = cells[spec.name_col].strip()
        if not name:
            continue
        key = _norm_name(name)
        canon = _canon_name(name)
        site = site_index.get(key, "") or site_index.get(f"__canon_site__:{canon}", "")
        if not site:
            site = contact_index.get(key, "") or contact_index.get(f"__canon_contact__:{canon}", "")
        from google_search import is_kontur_focus_url

        if site and not is_kontur_focus_url(site):
            cells[spec.site_col] = site
            spec.lines[row_idx] = "| " + " | ".join(_escape_cell(c) for c in cells) + " |"
            filled += 1
    return filled


def _escape_cell(s: str) -> str:
    return s.replace("|", "\\|")


def _needs_fill(site: str, *, force: bool) -> bool:
    if force:
        return True
    return site.strip() in _EMPTY_SITE


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


def _write_table(out_path: Path, spec: TableSpec) -> None:
    body = "\n".join(spec.lines)
    if body and not body.endswith("\n"):
        body += "\n"
    out_path.write_text(body, encoding="utf-8")


def enrich_table(
    spec: TableSpec,
    *,
    backend: str,
    query_suffix: str,
    sleep_s: float,
    limit: int,
    force: bool,
    only_na: bool,
    cache: dict[str, str],
    serper_api_key: str,
    google_api_key: str,
    google_cse_id: str,
    out_path: Path | None = None,
    cache_path: Path | None = None,
    flush_every: int = 25,
) -> tuple[int, int]:
    """Returns (queries_done, sites_filled)."""
    queries_done = 0
    sites_filled = 0
    data_start = spec.sep_line_idx + 1

    for row_idx in range(data_start, len(spec.lines)):
        line = spec.lines[row_idx]
        if not _TABLE_ROW_RE.match(line):
            continue
        cells = _split_cells(line)
        if len(cells) <= max(spec.name_col, spec.site_col):
            continue

        name = cells[spec.name_col].strip()
        if not name or name in {"№", "#"}:
            continue

        site = cells[spec.site_col].strip()
        if only_na and not _needs_fill(site, force=force):
            continue

        if limit > 0 and queries_done >= limit:
            break

        cache_key = name.casefold()
        if cache_key not in cache:
            q = build_query(name, query_suffix)
            try:
                found = google_first_url(
                    q,
                    backend=backend,
                    serper_api_key=serper_api_key,
                    google_api_key=google_api_key,
                    google_cse_id=google_cse_id,
                )
            except Exception as exc:
                print(f"  ! ошибка для «{name}»: {exc}", file=sys.stderr)
                queries_done += 1
                if sleep_s > 0:
                    time.sleep(sleep_s)
                continue
            cache[cache_key] = found
            queries_done += 1
            if sleep_s > 0:
                time.sleep(sleep_s)
            print(f"  [{queries_done}] {name} -> {found or 'N/A'}", flush=True)
            if (
                out_path
                and flush_every > 0
                and queries_done % flush_every == 0
            ):
                _write_table(out_path, spec)
                if cache_path:
                    save_cache(cache_path, cache)
        else:
            found = cache[cache_key]

        if found:
            cells[spec.site_col] = found
            spec.lines[row_idx] = "| " + " | ".join(_escape_cell(c) for c in cells) + " |"
            sites_filled += 1

    return queries_done, sites_filled


def main() -> int:
    parser = argparse.ArgumentParser(description="Первая ссылка из Google → колонка «Сайт» в markdown-таблице")
    parser.add_argument("--input", required=True, help="Входной .md с таблицей")
    parser.add_argument("--output", default="", help="Выходной .md (по умолчанию = --input)")
    parser.add_argument("--backend", default="auto", choices=("auto", "serper", "cse", "scrape"))
    parser.add_argument("--serper-api-key", default="", help="Или env SERPER_API_KEY")
    parser.add_argument("--google-api-key", default="", help="Или env GOOGLE_API_KEY (Custom Search)")
    parser.add_argument("--google-cse-id", default="", help="Или env GOOGLE_CSE_ID")
    parser.add_argument("--query-suffix", default="официальный сайт", help="Добавка к запросу")
    parser.add_argument("--sleep", type=float, default=1.0, help="Пауза между запросами (с)")
    parser.add_argument("--limit", type=int, default=0, help="Макс. число веб-запросов (0 = без лимита)")
    parser.add_argument("--force", action="store_true", help="Перезаписывать уже заполненные сайты")
    parser.add_argument("--cache", default=str(CACHE_PATH_DEFAULT), help="JSON-кэш name→url")
    parser.add_argument("--no-cache", action="store_true", help="Не читать/писать кэш")
    parser.add_argument("--dry-run", action="store_true", help="Только показать, что будет запрошено")
    parser.add_argument(
        "--local-first",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Сначала подставить сайты из data/** (по умолчанию включено)",
    )
    parser.add_argument(
        "--serper-only",
        action="store_true",
        help="Только Serper, без локального индекса",
    )
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.is_absolute():
        in_path = ROOT / in_path
    out_path = Path(args.output) if args.output else in_path
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    text = in_path.read_text(encoding="utf-8")
    spec = parse_markdown_table(text)
    if spec is None:
        print("Не найдена markdown-таблица с колонками «Название/Организация» и «Сайт».", file=sys.stderr)
        return 1

    cache_path = Path(args.cache)
    cache = {} if args.no_cache else load_cache(cache_path)

    if args.dry_run:
        n = 0
        for row_idx in range(spec.sep_line_idx + 1, len(spec.lines)):
            line = spec.lines[row_idx]
            if not _TABLE_ROW_RE.match(line):
                continue
            cells = _split_cells(line)
            if len(cells) <= max(spec.name_col, spec.site_col):
                continue
            name = cells[spec.name_col].strip()
            site = cells[spec.site_col].strip()
            if not name:
                continue
            if _needs_fill(site, force=args.force):
                print(build_query(name, args.query_suffix))
                n += 1
        print(f"Будет запрошено: {n} (лимит {args.limit or 'нет'})")
        return 0

    if args.local_first and not args.serper_only:
        from enrich_all_with_sites import build_link_index

        site_index, contact_index = build_link_index()
        local_filled = fill_sites_from_local_index(spec, site_index, contact_index)
        _write_table(out_path, spec)
        print(f"  локальный индекс: заполнено {local_filled} сайтов")

    api_key = args.serper_api_key or __import__("os").environ.get("SERPER_API_KEY", "")
    backend = args.backend
    if backend == "auto":
        backend = "serper" if api_key else "off"
    if backend == "serper" and not api_key:
        print("SERPER_API_KEY не задан — пропуск веб-поиска.", file=sys.stderr)
        return 0
    if backend == "off":
        print("Веб-поиск пропущен (нет SERPER_API_KEY, укажите --backend serper).")
        return 0

    queries, filled = enrich_table(
        spec,
        backend=backend,
        query_suffix=args.query_suffix,
        sleep_s=args.sleep,
        limit=args.limit,
        force=args.force,
        only_na=True,
        cache=cache,
        serper_api_key=api_key,
        google_api_key=args.google_api_key,
        google_cse_id=args.google_cse_id,
        out_path=out_path,
        cache_path=None if args.no_cache else cache_path,
        flush_every=25,
    )

    _write_table(out_path, spec)
    if not args.no_cache:
        save_cache(cache_path, cache)

    print(f"Готово: {out_path}")
    print(f"  запросов: {queries}, обновлено сайтов: {filled}, кэш: {cache_path}")
    if args.backend in ("auto", "scrape") and queries > 0 and filled == 0:
        print(
            "  подсказка: прямой scrape Google часто блокируется. "
            "Зарегистрируйте бесплатный ключ на https://serper.dev и: export SERPER_API_KEY=...",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
