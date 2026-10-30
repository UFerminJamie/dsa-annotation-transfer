#!/usr/bin/env python3
"""Preview or remove transfer-tool annotations for source files matching a destination."""

import argparse
import os
from pathlib import Path
import sys

from src.hpg_athena_transfer.api import APIError, AthenaClient
from src.hpg_athena_transfer.matching import build_index, discover, match_source
from src.hpg_athena_transfer.transfer import PROVENANCE_KEY


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path,
                        help="Source annotation directory used for the transfer")
    parser.add_argument("--destination", required=True,
                        help="Athena collection or folder URL/ID used for the transfer")
    parser.add_argument("--api-url", default="https://athena.rc.ufl.edu/api/v1")
    parser.add_argument("--recursive", action="store_true",
                        help="Include source subdirectories")
    parser.add_argument("--apply", action="store_true",
                        help="Delete the listed annotations; default is preview only")
    args = parser.parse_args()
    if not args.source.is_dir():
        parser.error("--source must be a readable directory")
    key = api_key()
    if not key:
        print("ATHENA_API_KEY is missing from the environment or ignored .env file", file=sys.stderr)
        return 2

    try:
        client = AthenaClient(args.api_url, key)
        user = client.check_connection()
        sources = discover(args.source, args.recursive)
        slide_index = build_index(client.slides(args.destination))
        matched_paths = {}
        for source in sources:
            sample, candidates = match_source(source.stem, slide_index)
            if sample is not None and len(candidates) == 1:
                matched_paths.setdefault(candidates[0].id, set()).add(
                    source.path.relative_to(args.source).as_posix())

        targets = []
        for item_id, paths in matched_paths.items():
            for record in client.annotations(item_id):
                annotation = record.get("annotation", {})
                attributes = annotation.get("attributes", {}) if isinstance(annotation, dict) else {}
                provenance = attributes.get(PROVENANCE_KEY, {}) if isinstance(attributes, dict) else {}
                if (record.get("_active") is not False and isinstance(provenance, dict)
                        and provenance.get("tool") == PROVENANCE_KEY
                        and provenance.get("source_relative_path") in paths
                        and isinstance(record.get("_id"), str)):
                    targets.append((item_id, record["_id"], annotation.get("name", "(unnamed)")))

        mode = "Deleting" if args.apply else "Preview only; no annotations deleted"
        print("Athena user: %s; matched WSI items: %d; transfer annotations found: %d" %
              (user.get("login") or user["id"], len(matched_paths), len(targets)))
        for item_id, annotation_id, name in targets:
            print("%s | %s | %s" % (item_id, annotation_id, name))
        if not args.apply:
            print(mode + ". Add --apply to delete these annotations.")
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
