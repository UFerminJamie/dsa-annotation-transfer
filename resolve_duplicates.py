#!/usr/bin/env python3
"""Collapse annotation JSON files whose names end in two 24-character IDs."""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path


# Run: python3 resolve_duplicates.py /blue/pinaki.sarder/j.fermin/HPG-ATHENA-Transfer/kpmp_b1_LB --apply
FILENAME_PATTERN = re.compile(r"^(?P<base>.+)_[0-9a-fA-F]{24}_[0-9a-fA-F]{24}\.json$")


def resolve_directory(directory: Path, apply: bool = False) -> None:
    if not directory.is_dir():
        raise ValueError(f"Not a directory: {directory}")

    groups: dict[Path, list[Path]] = defaultdict(list)
    for source in sorted(directory.glob("*.json")):
        match = FILENAME_PATTERN.match(source.name)
        if match:
            groups[source.with_name(f"{match.group('base')}.json")].append(source)

    if not groups:
        print(f"No matching JSON files found in {directory}")
        return

    duplicate_file_count = 0
    duplicate_group_count = 0
    for target, sources in sorted(groups.items()):
        # If the clean name already exists, keep it and remove the suffixed copies.
        candidates = sorted(sources)
        if target.exists():
            keep = target
            duplicates = candidates
        else:
            keep = candidates[0]
            duplicates = candidates[1:]

        duplicate_file_count += len(duplicates)
        if duplicates:
            duplicate_group_count += 1

        action = "Applying" if apply else "Preview"
        print(f"{action}: keep {keep.name}; rename to {target.name}")
        for duplicate in duplicates:
            print(f"  delete {duplicate.name}")

        if apply:
            if keep != target:
                keep.rename(target)
            for duplicate in duplicates:
                duplicate.unlink()

    print(
        f"Duplicate files found: {duplicate_file_count} "
        f"across {duplicate_group_count} duplicate group(s)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Keep one JSON per annotation filename, removing the two trailing "
            "24-character IDs. Runs as a preview unless --apply is supplied."
        )
    )
    parser.add_argument("directory", type=Path, help="Directory containing the JSON files")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rename the retained file and delete duplicate copies",
    )
    args = parser.parse_args()

    try:
        resolve_directory(args.directory, apply=args.apply)
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
