#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    src = ROOT / "final" / "site"
    # GitHub Pages (branch main, folder /) — статика в корне репозитория
    dst = ROOT

    if not (src / "index.html").exists():
        raise SystemExit(f"Missing site sources: {src}")

    # copy static assets (html/css/js)
    for name in ("index.html", "styles.css", "app.js"):
        shutil.copyfile(src / name, dst / name)

    # prevent Jekyll processing
    (dst / ".nojekyll").write_text("", encoding="utf-8")

    # build JSON into project root (рядом с index.html)
    from build_contacts_site_json import main as build_json_main  # local import

    # emulate CLI args via direct call is awkward; call module as a script instead
    # (we keep it simple and just run it through python by importing argparse-less function)
    # So: re-run the generator in-process using its functions would require refactor.
    # We'll shell out is not allowed here; instead we generate by invoking build_json_main with sys.argv.
    import sys

    old_argv = sys.argv[:]
    try:
        sys.argv = [
            old_argv[0],
            "--input",
            str(ROOT / "final" / "final.md"),
            "--output",
            str(dst / "contacts.json"),
        ]
        build_json_main()
    finally:
        sys.argv = old_argv

    print(f"Wrote GitHub Pages site to: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

