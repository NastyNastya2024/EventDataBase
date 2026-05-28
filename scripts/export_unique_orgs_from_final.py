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


def export_unique_orgs(input_md: Path) -> list[str]:
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
    if org_col < 0:
        raise SystemExit("Could not find organization column in header")

    seen: set[str] = set()
    out: list[str] = []

    j = header_idx + 2
    while j < len(lines) and lines[j].startswith("|"):
        row = _split_cells(lines[j])
        if org_col < len(row):
            org = row[org_col].strip()
            if org:
                key = " ".join(org.split()).casefold()
                if key not in seen:
                    seen.add(key)
                    out.append(org)
        j += 1

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Export unique org names from final contacts table.")
    ap.add_argument(
        "--input",
        default=str(Path("final") / "final_contacts_with_type.md"),
        help="Path to final markdown file",
    )
    ap.add_argument(
        "--output",
        default=str(Path("final") / "final_orgs_unique.txt"),
        help="Output path (one org per line)",
    )
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    orgs = export_unique_orgs(in_path)
    out_path.write_text("\n".join(orgs) + ("\n" if orgs else ""), encoding="utf-8")
    print(f"Wrote: {out_path} (orgs={len(orgs)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

