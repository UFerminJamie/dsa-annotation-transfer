#!/usr/bin/env python3
"""Download selected HistomicsUI annotations from a DSA collection or folder."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

import requests


ANNOTATION_NAMES = (
    "non_globally_sclerotic_glomeruli_tuft",
    "tubules",
    "globally_sclerotic_glomeruli",
    "muscular_vessels",
    "non_globally_sclerotic_glomeruli",
    "peritubular_capillaries",
    "arteries/arterioles",
)
PAGE_SIZE = 500
TIMEOUT = (10, 120)
MAX_RETRIES = 5
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
LOG = logging.getLogger("download_dsa_annotations")


class DSAError(RuntimeError):
    """A user-facing DSA/API error."""


def parse_dsa_url(url: str) -> tuple[str, str | None, str | None]:
    """Return (server, collection_id, folder_id) for a DSA web URL."""
    try:
        parsed = urlsplit(url.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid DSA URL: {exc}") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Invalid DSA URL: expected an http(s) URL with a server host")
    fragment = unquote(parsed.fragment).strip("/")
    # DSA UI links place resource routes in the fragment; also accept API-like paths.
    route = fragment or parsed.path.strip("/")
    parts = [p for p in route.split("/") if p]
    collection_id = folder_id = None
    for index, part in enumerate(parts[:-1]):
        if part == "collection":
            collection_id = parts[index + 1]
        elif part == "folder":
            folder_id = parts[index + 1]
    if folder_id is None and collection_id is None:
        raise ValueError("Invalid DSA URL: include a collection/<id> or folder/<id> resource")
    if collection_id and not re.fullmatch(r"[A-Za-z0-9_-]+", collection_id):
        raise ValueError("Invalid DSA URL: malformed collection ID")
    if folder_id and not re.fullmatch(r"[A-Za-z0-9_-]+", folder_id):
        raise ValueError("Invalid DSA URL: malformed folder ID")
    server = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}/api/v1"
    return server, collection_id, folder_id


def sanitize_filename(value: str) -> str:
    """Replace path separators and unsafe filename characters with underscores."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip(" ._")
    return cleaned or "unnamed"


def annotation_name(annotation: dict[str, Any]) -> Any:
    nested = annotation.get("annotation")
    return nested.get("name") if isinstance(nested, dict) else annotation.get("name")


def normalized_annotation_name(annotation: dict[str, Any]) -> str | None:
    """Return the annotation name without surrounding whitespace for selection."""
    name = annotation_name(annotation)
    return name.strip() if isinstance(name, str) else None


class GirderClient:
    def __init__(self, api_url: str, api_key: str | None = None, session: Any = None):
        self.api_url = api_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        if api_key:
            try:
                result = self._request("POST", "/api_key/token", data={"key": api_key}, authenticate=False)
            except DSAError as exc:
                raise DSAError(f"DSA API key authentication failed: {exc}") from exc
            token = result.get("token") if isinstance(result, dict) else None
            if not token and isinstance(result, dict):
                auth_token = result.get("authToken")
                if isinstance(auth_token, dict):
                    token = auth_token.get("token")
            if not isinstance(token, str) or not token:
                raise DSAError("DSA API key authentication failed: server returned no token")
            self.session.headers["Girder-Token"] = token

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 data: dict | None = None, authenticate: bool = True) -> Any:
        del authenticate  # token is attached to the session after key exchange
        url = f"{self.api_url}{path}"
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.request(method, url, params=params, data=data, timeout=TIMEOUT)
            except requests.RequestException as exc:
                if attempt + 1 == MAX_RETRIES:
                    raise DSAError(f"Request failed for {path}: {exc.__class__.__name__}") from exc
                time.sleep(min(2 ** attempt, 16))
                continue
            if response.status_code in RETRYABLE_STATUS and attempt + 1 < MAX_RETRIES:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = min(float(retry_after), 30) if retry_after else min(2 ** attempt, 16)
                except ValueError:
                    delay = min(2 ** attempt, 16)
                time.sleep(delay)
                continue
            if response.status_code in (401, 403):
                raise DSAError("Authentication failed or the requested DSA resource is not accessible")
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise DSAError(f"DSA request failed for {path} (HTTP {response.status_code})") from exc
            try:
                return response.json()
            except ValueError as exc:
                raise DSAError(f"DSA returned invalid JSON for {path}") from exc
        raise DSAError(f"Request failed for {path} after retries")

    def paged(self, path: str, *, params: dict | None = None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        while True:
            query = dict(params or {})
            query.update(limit=PAGE_SIZE, offset=offset)
            page = self._request("GET", path, params=query)
            if isinstance(page, dict):
                # Some deployments wrap paged responses, while standard Girder returns a list.
                page = page.get("data", page.get("results", []))
            if not isinstance(page, list):
                raise DSAError(f"Unexpected paginated response from {path}")
            result.extend(page)
            if len(page) < PAGE_SIZE:
                return result
            offset += len(page)

    def items_in_folder_tree(self, collection_id: str | None, folder_id: str | None) -> list[dict]:
        folders: list[str] = []
        if folder_id:
            folders.append(folder_id)
        else:
            folders.extend(folder["_id"] for folder in self.paged(
                "/folder", params={"parentType": "collection", "parentId": collection_id})
                if folder.get("_id"))
        visited: set[str] = set()
        items: list[dict] = []
        while folders:
            current = folders.pop()
            if current in visited:
                continue
            visited.add(current)
            subfolders = self.paged(
                "/folder", params={"parentType": "folder", "parentId": current})
            folders.extend(folder["_id"] for folder in subfolders if folder.get("_id"))
            items.extend(self.paged("/item", params={"folderId": current}))
        return items

    def annotations_for_item(self, item_id: str) -> list[dict]:
        # /annotation supports limit/offset and returns summaries with annotation.name.
        return self.paged("/annotation", params={"itemId": item_id})

    def full_annotation(self, annotation_id: str) -> dict:
        document: dict[str, Any] | None = None
        all_elements: list[Any] = []
        offset = 0
        while True:
            page = self._request("GET", f"/annotation/{annotation_id}",
                                 params={"limit": PAGE_SIZE, "offset": offset})
            if not isinstance(page, dict) or not isinstance(page.get("annotation"), dict):
                raise DSAError(f"Unexpected annotation document for {annotation_id}")
            if document is None:
                document = page
            elements = page["annotation"].get("elements", [])
            if not isinstance(elements, list):
                raise DSAError(f"Invalid annotation elements for {annotation_id}")
            all_elements.extend(elements)
            if len(elements) < PAGE_SIZE:
                break
            offset += len(elements)
        assert document is not None
        document["annotation"]["elements"] = all_elements
        expected = document.get("_elementCount")
        if expected is not None:
            try:
                expected_count = int(expected)
            except (TypeError, ValueError):
                expected_count = len(all_elements)
            if expected_count != len(all_elements):
                raise DSAError(
                    f"Annotation {annotation_id} is incomplete: API reports {expected_count} elements, "
                    f"received {len(all_elements)}")
        return document


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    """Write JSON to a sibling temp file and atomically replace destination."""
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def plan_filenames(matches: list[tuple[dict, dict]]) -> list[tuple[dict, dict, str]]:
    """Assign unique filenames, adding both item and annotation IDs on collisions."""
    candidates: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for item, annotation in matches:
        stem = Path(str(item.get("name", "unnamed"))).stem
        name = sanitize_filename(str(annotation_name(annotation) or "unnamed"))
        candidates[f"{sanitize_filename(stem)}_{name}.json"].append((item, annotation))
    planned = []
    for filename, entries in candidates.items():
        if len(entries) == 1:
            item, annotation = entries[0]
            planned.append((item, annotation, filename))
            continue
        LOG.warning("Filename collision for %s (%d annotations); adding item and annotation IDs",
                    filename, len(entries))
        for item, annotation in entries:
            item_id = sanitize_filename(str(item.get("_id", "item")))
            annotation_id = sanitize_filename(str(annotation.get("_id", "annotation")))
            stem = Path(filename).stem
            planned.append((item, annotation, f"{stem}_{item_id}_{annotation_id}.json"))
    return planned


def ensure_output_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise OSError("path is not a directory")
        probe = tempfile.NamedTemporaryFile(prefix=".dsa_write_test_", dir=path, delete=True)
        probe.close()
    except OSError as exc:
        raise DSAError(f"Output directory is not writable: {path} ({exc})") from exc


def download(client: GirderClient, items: Iterable[dict], output: Path, overwrite: bool) -> dict[str, int]:
    stats = {"items": 0, "matches": 0, "downloaded": 0, "skipped": 0, "failed": 0}
    matches: list[tuple[dict, dict]] = []
    for item in items:
        stats["items"] += 1
        item_id = item.get("_id")
        item_name = str(item.get("name", item_id or "unknown item"))
        if not item_id:
            LOG.error("Skipping item without an ID: %s", item_name)
            stats["failed"] += 1
            continue
        try:
            annotations = client.annotations_for_item(item_id)
        except DSAError as exc:
            LOG.error("Could not list annotations for %s (%s): %s", item_name, item_id, exc)
            stats["failed"] += 1
            continue
        selected = [a for a in annotations if normalized_annotation_name(a) in ANNOTATION_NAMES]
        stats["matches"] += len(selected)
        present = {normalized_annotation_name(a) for a in selected}
        missing = [name for name in ANNOTATION_NAMES if name not in present]
        LOG.info("Item %s: %d matching annotation(s)", item_name, len(selected))
        if missing:
            LOG.info("Item %s missing annotation name(s): %s", item_name, ", ".join(missing))
        matches.extend((item, annotation) for annotation in selected)

    for item, summary, filename in plan_filenames(matches):
        target = output / filename
        if target.exists() and not overwrite:
            LOG.info("Skipping existing file: %s", target)
            stats["skipped"] += 1
            continue
        annotation_id = summary.get("_id")
        try:
            if not annotation_id:
                raise DSAError("annotation record has no ID")
            document = client.full_annotation(str(annotation_id))
            # Guard against a stale/mismatched list response without altering returned JSON.
            if annotation_name(document) != annotation_name(summary):
                raise DSAError(f"Annotation name changed while retrieving {annotation_id}")
            atomic_write_json(target, document)
            stats["downloaded"] += 1
            LOG.info("Downloaded %s", target.name)
        except (DSAError, OSError, TypeError, ValueError) as exc:
            LOG.error("Failed to download %s (%s): %s", annotation_name(summary), annotation_id, exc)
            stats["failed"] += 1
    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="DSA collection or folder URL")
    parser.add_argument("--output-directory", required=True, type=Path, help="Directory for annotation JSON files")
    parser.add_argument("--api-key", help="Girder API key (or set ATHENA_API_KEY)")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing output files")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    try:
        api_url, collection_id, folder_id = parse_dsa_url(args.url)
        ensure_output_directory(args.output_directory)
        client = GirderClient(api_url, args.api_key or os.environ.get("ATHENA_API_KEY"))
        items = client.items_in_folder_tree(collection_id, folder_id)
        LOG.info("Found %d WSI item(s) in requested resource", len(items))
        stats = download(client, items, args.output_directory, args.overwrite)
    except ValueError as exc:
        LOG.error("%s", exc)
        return 2
    except DSAError as exc:
        LOG.error("%s", exc)
        return 2
    except OSError as exc:
        LOG.error("Could not access output directory: %s", exc)
        return 2
    LOG.info("Summary: items inspected=%d, matching annotations found=%d, files downloaded=%d, "
             "existing files skipped=%d, failed downloads=%d", stats["items"], stats["matches"],
             stats["downloaded"], stats["skipped"], stats["failed"])
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
