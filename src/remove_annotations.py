#!/usr/bin/env python3
"""Preview or remove every annotation attached to WSIs in an Athena destination."""

import argparse
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple

from hpg_athena_transfer.api import APIError, AthenaClient


DEFAULT_DESTINATION = (
    ""
)


def api_key() -> str:
    if os.environ.get("ATHENA_API_KEY"):
        return os.environ["ATHENA_API_KEY"]
    env_file = Path.cwd() / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "ATHENA_API_KEY":
                return value.strip().strip('"\'')
    return ""


def collect_targets(client: AthenaClient, destination: str) -> Tuple[List[Any], List[Tuple[str, str, str]]]:
    """Return WSI slides and their annotation IDs, de-duplicated by annotation ID."""
    slides = client.slides(destination)
    targets = []
    seen_ids = set()
    for slide in slides:
        for record in client.annotations(slide.id):
            if record.get("_active") is False:
                continue
            annotation_id = record.get("_id")
            if not isinstance(annotation_id, str) or annotation_id in seen_ids:
                continue
            seen_ids.add(annotation_id)
            annotation = record.get("annotation")
            name = annotation.get("name", "(unnamed)") if isinstance(annotation, dict) else "(unnamed)"
            targets.append((slide.id, annotation_id, str(name)))
    return slides, targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "destination", nargs="?", default=DEFAULT_DESTINATION,
        help="Athena collection/folder URL or ID (default: the configured destination)",
    )
    parser.add_argument("--api-url", default="https://athena.rc.ufl.edu/api/v1")
    parser.add_argument("--apply", action="store_true",
                        help="Delete the listed annotations; default is preview only")
    args = parser.parse_args()
    key = api_key()
    if not key:
        print("ATHENA_API_KEY is missing from the environment or ignored .env file", file=sys.stderr)
        return 2

    try:
        client = AthenaClient(args.api_url, key)
        user = client.check_connection()
        slides, targets = collect_targets(client, args.destination)
        print("Athena user: %s; destination: %s; WSI items: %d; annotations found: %d" % (
            user.get("login") or user["id"], args.destination, len(slides), len(targets)))
        for item_id, annotation_id, name in targets:
            print("%s | %s | %s" % (item_id, annotation_id, name))
        if not args.apply:
            print("Preview only; no annotations deleted. Add --apply to delete these annotations.")
            return 0

        deleted = 0
        failures = 0
        for _, annotation_id, _ in targets:
            try:
                client.delete_annotation(annotation_id)
                deleted += 1
            except APIError as exc:
                failures += 1
                print("Delete failed for %s: %s" % (annotation_id, exc), file=sys.stderr)
        print("Deleted: %d; failed: %d" % (deleted, failures))
        return 1 if failures else 0
    except (APIError, ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, (APIError, ValueError)) else type(exc).__name__
        print("Error: " + message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
