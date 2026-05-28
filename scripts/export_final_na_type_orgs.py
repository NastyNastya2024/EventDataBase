#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _find_col(headers: list[str], candidates: tuple[str, ...]) -> int:
    lowered = [h.casefold().strip() for h in headers]
    for cand in candidates:
        c = cand.casefold()
        for i, h in enumerate(lowered):
            if c == h:
                return i
    for cand in candidates:
        c = cand.casefold()
        for i, h in enumerate(lowered):
            if c in h:
                return i
    return -1


def export_orgs_with_na_type(input_md: Path) -> list[str]:
    lines = input_md.read_text(encoding="utf-8", errors="ignore").splitlines()

    header_idx = -1
    headers: list[str] | None = None
    for i, ln in enumerate(lines):
        if not ln.startswith("|"):
            continue
        maybe_headers = _split_cells(ln)
        if i + 1 < len(lines) and _SEP_RE.match(lines[i + 1]):
            header_idx = i
            headers = maybe_headers
            break

    if header_idx < 0 or not headers:
        raise SystemExit(f"Table not found in: {input_md}")

    org_col = _find_col(headers, ("организация", "название", "компания", "name"))
    type_col = _find_col(headers, ("тип", "тип организации", "type"))
    if min(org_col, type_col) < 0:
        raise SystemExit("Could not find required columns (org/type) in header")

    seen: set[str] = set()
    out: list[str] = []

    j = header_idx + 2
    while j < len(lines) and lines[j].startswith("|"):
        row = _split_cells(lines[j])
        if len(row) > max(org_col, type_col):
            org = row[org_col].strip()
            typ = row[type_col].strip()
            if org and typ == "N/A":
                key = " ".join(org.split()).casefold()
                if key not in seen:
                    seen.add(key)
                    out.append(org)
        j += 1

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Export unique org names with type=N/A from final markdown table.")
    ap.add_argument("--input", default=str(Path("final") / "final.md"))
    ap.add_argument("--output", default=str(Path("final") / "final_orgs_type_na.txt"))
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    orgs = export_orgs_with_na_type(in_path)
    out_path.write_text("\n".join(orgs) + ("\n" if orgs else ""), encoding="utf-8")
    print(f"Wrote: {out_path} (orgs={len(orgs)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

