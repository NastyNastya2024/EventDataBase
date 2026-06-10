#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_FILES = (
    "index.html",
    "agencies.html",
    "wedwed.html",
    "telegram.html",
    "styles.css",
    "telegram.css",
    "app.js",
    "app-agencies.js",
    "app-wedwed.js",
    "telegram.js",
    "shared.js",
    "contacts.json",
    "wedwed.json",
    ".nojekyll",
)

SITE_DATA_FILES = ("data/event_telegram_channels.json",)


def main() -> int:
    src = ROOT / "final" / "site"
    if not (src / "index.html").exists():
        raise SystemExit(f"Missing site sources: {src}")

    for name in (
        "index.html",
        "agencies.html",
        "wedwed.html",
        "telegram.html",
        "styles.css",
        "telegram.css",
        "app.js",
        "app-agencies.js",
        "app-wedwed.js",
        "telegram.js",
        "shared.js",
    ):
        shutil.copyfile(src / name, ROOT / name)

    for rel in SITE_DATA_FILES:
        dst = ROOT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / rel, dst)

    (ROOT / ".nojekyll").write_text("", encoding="utf-8")

    site_json = src / "contacts.json"
    wedwed_json = src / "wedwed.json"

    from build_contacts_site_json import main as build_json_main

    old_argv = sys.argv[:]
    try:
        sys.argv = [
            old_argv[0],
            "--input",
            str(ROOT / "final" / "final.md"),
            "--output",
            str(site_json),
        ]
        build_json_main()
        sys.argv = [
            old_argv[0],
            "--input",
            str(ROOT / "final" / "wedwed.md"),
            "--output",
            str(wedwed_json),
        ]
        build_json_main()
    finally:
        sys.argv = old_argv

    shutil.copyfile(site_json, ROOT / "contacts.json")
    shutil.copyfile(wedwed_json, ROOT / "wedwed.json")
    row_count = len(json.loads(site_json.read_text(encoding="utf-8")))
    wedwed_count = len(json.loads(wedwed_json.read_text(encoding="utf-8")))

    # Корень репо (legacy branch deploy) + docs/ (fallback) + _site/ (GitHub Actions)
    for target in (ROOT / "docs", ROOT / "_site"):
        target.mkdir(parents=True, exist_ok=True)
        for name in SITE_FILES:
            shutil.copyfile(ROOT / name, target / name)
        for rel in SITE_DATA_FILES:
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, dst)

    print(f"Wrote contacts.json rows={row_count}, wedwed.json rows={wedwed_count}")
    print(f"Site files: {src}, {ROOT}, {ROOT / 'docs'}, {ROOT / '_site'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
