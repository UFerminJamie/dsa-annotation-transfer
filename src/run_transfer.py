#!/usr/bin/env python3
"""Report duplicate WSIs and transfer annotations within one Athena folder."""

import argparse
import csv
from datetime import datetime
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

from hpg_athena_transfer.api import APIError, AthenaClient
from hpg_athena_transfer.cli import _api_key
from hpg_athena_transfer.matching import build_index
from hpg_athena_transfer.transfer import transfer


FOLDER_ID = re.compile(r"(?:^|/)folder/([0-9a-fA-F]{24})(?:/|$)")
BARE_ID = re.compile(r"^[0-9a-fA-F]{24}$")


def folder_destination(value):
    """Return a canonical folder URL, selecting folder from nested Athena URLs."""
    if BARE_ID.fullmatch(value):
        return "https://athena.rc.ufl.edu/#folder/" + value.lower(), value.lower()
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Destination must be an Athena folder URL or 24-character folder ID")
    route = unquote(parsed.fragment.split("?", 1)[0] or parsed.path)
    matches = list(FOLDER_ID.finditer(route))
    if not matches:
        raise ValueError("Destination URL must include a folder/<24-character-ID> route")
    folder_id = matches[-1].group(1).lower()
    return "%s://%s/#folder/%s" % (parsed.scheme, parsed.netloc, folder_id), folder_id


def parser():
    command = argparse.ArgumentParser(
        description=("List duplicate WSI basenames inside one Athena folder, then transfer "
                     "only source files that match exactly one WSI in that folder."))
    command.add_argument("--source", type=Path, required=True,
                         help="Directory containing JSON annotation files")
    command.add_argument("--destination", required=True,
                         help="Athena folder URL (including nested URLs) or folder ID")
    command.add_argument("--api-url", default="https://athena.rc.ufl.edu/api/v1",
                         help="Girder API base URL")
    command.add_argument("--recursive", action="store_true",
                         help="Include JSON files in source subdirectories")
    command.add_argument("--manifest", type=Path,
                         help="Transfer manifest path (defaults to a timestamped file)")
    command.add_argument("--duplicate-report", type=Path,
                         help="CSV path for duplicate WSI basenames and slide IDs")
    mode = command.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    mode.add_argument("--apply", action="store_true", help="Upload uniquely matched annotations")
    return command


def write_duplicate_report(path, slide_index):
    path.parent.mkdir(parents=True, exist_ok=True)
    duplicate_groups = [(name, candidates) for name, candidates in slide_index.items()
                        if len(candidates) > 1]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("basename", "slide_id", "slide_name"))
        writer.writeheader()
        for basename, candidates in sorted(duplicate_groups):
            for slide in sorted(candidates, key=lambda item: (item.name, item.id)):
                writer.writerow({"basename": basename, "slide_id": slide.id,
                                 "slide_name": slide.name})
    return len(duplicate_groups), sum(len(candidates) for _, candidates in duplicate_groups)


def main(argv=None):
    args = parser().parse_args(argv)
    if not os.environ.get("ATHENA_API_KEY") and not (Path.cwd() / ".env").is_file():
        print("ATHENA_API_KEY is missing from the environment or ignored .env file", file=sys.stderr)
        return 2

    try:
        destination, folder_id = folder_destination(args.destination)
    except ValueError as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 2

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    manifest = args.manifest or Path("transfer-manifest") / ("folder-unique-transfer-%s.json" % stamp)
    report = args.duplicate_report or manifest.with_name(manifest.stem + "-duplicate-wsis.csv")

    try:
        client = AthenaClient(args.api_url, _api_key())
        user = client.check_connection()
        slide_index = build_index(client.slides(destination))
        duplicate_groups, duplicate_items = write_duplicate_report(report, slide_index)
        print("Athena user: %s" % (user.get("login") or user["id"]))
        print("Destination folder: %s" % folder_id)
        print("Duplicate WSI basename groups in folder: %d; WSI items in those groups: %d" %
              (duplicate_groups, duplicate_items))
        print("Duplicate WSI report: %s" % report)

        result = transfer(client, args.source, destination, manifest,
                          recursive=args.recursive, apply=args.apply)
        mode = "apply" if args.apply else "dry-run"
        print("Mode: %s; source files: %d; annotation records: %d" %
              (mode, result["files"], result["records"]))
        for status in ("uploaded", "skipped-identical", "skipped-duplicate", "planned",
                       "unmatched", "ambiguous", "invalid", "failed"):
            print("%s: %d files; %d annotation records" %
                  (status, result["file_summary"].get(status, 0),
                   result["summary"].get(status, 0)))
        print("Manifest: %s" % result["manifest"])
        return 1 if result["summary"].get("failed") or result["summary"].get("invalid") else 0
    except (APIError, ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, (APIError, ValueError)) else type(exc).__name__
        print("Error: " + message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
