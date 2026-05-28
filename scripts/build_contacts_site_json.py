#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import argparse
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]

IN_PATH_DEFAULT = ROOT / "final" / "final.md"
OUT_PATH_DEFAULT = ROOT / "final" / "site" / "contacts.json"

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


def _social_platform(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").casefold()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return "other"
    if host.endswith(("t.me", "telegram.me", "telegram.org")):
        return "telegram"
    if host.endswith(("vk.com", "vk.ru")):
        return "vk"
    if host.endswith("instagram.com"):
        return "instagram"
    if host.endswith(("facebook.com", "fb.com")):
        return "facebook"
    if host.endswith(("youtube.com", "youtu.be")):
        return "youtube"
    if host.endswith(("wa.me", "api.whatsapp.com", "whatsapp.com")):
        return "whatsapp"
    if host.endswith(("ok.ru", "odnoklassniki.ru")):
        return "ok"
    if host.endswith("tiktok.com"):
        return "tiktok"
    if host.endswith("dzen.ru"):
        return "dzen"
    if host.endswith("zen.yandex.ru"):
        return "dzen"
    if host.endswith("rutube.ru"):
        return "rutube"
    if host.endswith("linkedin.com"):
        return "linkedin"
    if host.endswith(("x.com", "twitter.com")):
        return "x"
    return "other"

def main() -> int:
    ap = argparse.ArgumentParser(description="Build contacts.json for static site")
    ap.add_argument("--input", default=str(IN_PATH_DEFAULT))
    ap.add_argument("--output", default=str(OUT_PATH_DEFAULT))
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.is_absolute():
        in_path = ROOT / in_path
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    if not in_path.exists():
        raise SystemExit(f"Missing: {in_path}")

    lines = in_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    headers, start = find_table(lines)

    org_i = col(headers, "Организация")
    typ_i = col(headers, "Тип")
    site_i = col(headers, "Сайт")
    kind_i = col(headers, "Вид контакта")
    val_i = col(headers, "Контакт")
    items: list[dict] = []
    for ln in lines[start:]:
        if not ln.startswith("|"):
            break
        if ln.lstrip().startswith("|---"):
            continue
        cells = _split_cells(ln)
        if len(cells) <= max(org_i, typ_i, site_i, kind_i, val_i):
            continue
        items.append(
            {
                "org": cells[org_i],
                "orgType": cells[typ_i],
                "site": cells[site_i],
                "kind": cells[kind_i],  # phone|email|social
                "value": cells[val_i],
                "socialPlatform": _social_platform(cells[val_i]) if cells[kind_i] == "social" else "",
            }
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote: {out_path} (rows={len(items)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

