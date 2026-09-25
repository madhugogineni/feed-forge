"""Build and validate the small-file editorial view of Topic Radar output."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


EDITORIAL_INPUT_SCHEMA = "feed-forge/editorial-input/v1"
DEFAULT_SHARD_SIZE = 20
_TRACKING_QUERY_NAMES = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
}
_OCCURRENCE_ID = re.compile(r"occ_\d{6}")


class EditorialSnapshotError(ValueError):
    """Raised when an editorial snapshot is incomplete or inconsistent."""


def canonicalize_url(value: str) -> str:
    """Apply conservative, deterministic URL normalization.

    Host and scheme case, default ports, fragments, and common tracking
    parameters are safe to normalize without guessing at publisher URL rules.
    Remaining query parameter order is retained because it can be meaningful.
    """

    if not isinstance(value, str) or not value.strip():
        raise EditorialSnapshotError("URL must be a non-empty string")
    original = value.strip()
    try:
        parsed = urlsplit(original)
        port = parsed.port
    except ValueError as error:
        raise EditorialSnapshotError(f"Invalid URL {original!r}: {error}") from error
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise EditorialSnapshotError(f"URL must use HTTP(S) and include a host: {original!r}")

    hostname = parsed.hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    userinfo = ""
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    include_port = port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    )
    netloc = f"{userinfo}{hostname}{f':{port}' if include_port else ''}"
    query_pairs = [
        (name, item)
        for name, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_parameter(name)
    ]
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, urlencode(query_pairs, doseq=True), ""))


def build_editorial_snapshot(
    report: dict[str, Any],
    target_directory: Path,
    *,
    workflow_run_id: int,
    commit_sha: str,
    generated_at: str | None = None,
    shard_size: int = DEFAULT_SHARD_SIZE,
) -> dict[str, Any]:
    """Build, validate, and atomically replace an editorial snapshot directory."""

    if not isinstance(report, dict):
        raise EditorialSnapshotError("Topic Radar report must be an object")
    if workflow_run_id <= 0:
        raise EditorialSnapshotError("workflow_run_id must be a positive integer")
    if not isinstance(commit_sha, str) or not commit_sha.strip():
        raise EditorialSnapshotError("commit_sha must not be empty")
    if not isinstance(shard_size, int) or isinstance(shard_size, bool) or shard_size <= 0:
        raise EditorialSnapshotError("shard_size must be a positive integer")

    timestamp = generated_at or report.get("generated_at")
    if not isinstance(timestamp, str) or not timestamp.strip():
        timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    topics, source_health = _read_report_sections(report)
    occurrences, topic_records = _build_occurrences(topics, source_health)
    url_records = _build_url_records(occurrences)

    target_directory = Path(target_directory)
    target_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{target_directory.name}-",
            dir=target_directory.parent,
        )
    )
    try:
        (temporary / "occurrences").mkdir()
        (temporary / "urls").mkdir()
        topics_payload = {
            "schema_version": EDITORIAL_INPUT_SCHEMA,
            "generated_at": timestamp,
            "topics": topic_records,
        }
        health_payload = {
            "schema_version": EDITORIAL_INPUT_SCHEMA,
            "generated_at": timestamp,
            "sources": source_health,
        }
        topics_path = temporary / "topics.json"
        health_path = temporary / "source-health.json"
        _write_json(topics_path, topics_payload)
        _write_json(health_path, health_payload)

        occurrence_shards = _write_shards(
            temporary,
            "occurrences",
            occurrences,
            shard_size,
        )
        url_shards = _write_shards(
            temporary,
            "urls",
            url_records,
            shard_size,
        )
        manifest = {
            "schema_version": EDITORIAL_INPUT_SCHEMA,
            "workflow_run_id": workflow_run_id,
            "commit_sha": commit_sha.strip(),
            "generated_at": timestamp,
            "topic_count": len(topic_records),
            "url_occurrence_count": len(occurrences),
            "unique_url_count": len(url_records),
            "topics_file": "topics.json",
            "topics_sha256": _sha256(topics_path),
            "source_health_file": "source-health.json",
            "source_health_sha256": _sha256(health_path),
            "shard_size": shard_size,
            "occurrence_shards": occurrence_shards,
            "url_shards": url_shards,
        }
        _write_json(temporary / "manifest.json", manifest)
        validate_editorial_snapshot(temporary)

        if target_directory.exists():
            if not target_directory.is_dir():
                raise EditorialSnapshotError(
                    f"Snapshot target is not a directory: {target_directory}"
                )
            shutil.rmtree(target_directory)
        temporary.replace(target_directory)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise

    validate_editorial_snapshot(target_directory)
    return manifest


def validate_editorial_snapshot(snapshot_directory: Path) -> dict[str, Any]:
    """Validate every file, checksum, count, and occurrence-to-URL mapping."""

    root = Path(snapshot_directory)
    manifest = _read_json_object(root / "manifest.json", "manifest")
    if manifest.get("schema_version") != EDITORIAL_INPUT_SCHEMA:
        raise EditorialSnapshotError("Manifest has an unsupported schema_version")
    _require_positive_integer(manifest, "workflow_run_id")
    _require_non_empty_string(manifest, "commit_sha", "manifest")
    _require_non_empty_string(manifest, "generated_at", "manifest")
    for field in ("topic_count", "url_occurrence_count", "unique_url_count"):
        _require_non_negative_integer(manifest, field)
    _require_positive_integer(manifest, "shard_size")

    topics_path = _resolve_relative_file(root, manifest, "topics_file")
    health_path = _resolve_relative_file(root, manifest, "source_health_file")
    _validate_checksum(topics_path, manifest.get("topics_sha256"))
    _validate_checksum(health_path, manifest.get("source_health_sha256"))
    topics_payload = _read_json_object(topics_path, "topics file")
    health_payload = _read_json_object(health_path, "source-health file")
    _validate_payload_schema(topics_payload, "topics file")
    _validate_payload_schema(health_payload, "source-health file")
    topics = topics_payload.get("topics")
    sources = health_payload.get("sources")
    if not isinstance(topics, list):
        raise EditorialSnapshotError("topics file must contain a topics array")
    if not isinstance(sources, list):
        raise EditorialSnapshotError("source-health file must contain a sources array")
    if len(topics) != manifest["topic_count"]:
        raise EditorialSnapshotError("Manifest topic_count does not match topics.json")

    occurrence_records = _read_shards(root, manifest, "occurrence_shards", "occurrences")
    url_records = _read_shards(root, manifest, "url_shards", "urls")
    if len(occurrence_records) != manifest["url_occurrence_count"]:
        raise EditorialSnapshotError(
            "Occurrence shard totals do not match manifest.url_occurrence_count"
        )
    if len(url_records) != manifest["unique_url_count"]:
        raise EditorialSnapshotError(
            "URL shard totals do not match manifest.unique_url_count"
        )

    occurrences_by_id: dict[str, dict[str, Any]] = {}
    canonical_occurrences: defaultdict[str, set[str]] = defaultdict(set)
    topic_occurrences: defaultdict[str, set[str]] = defaultdict(set)
    for record in occurrence_records:
        _validate_occurrence(record)
        occurrence_id = record["occurrence_id"]
        if occurrence_id in occurrences_by_id:
            raise EditorialSnapshotError(f"Duplicate occurrence_id: {occurrence_id}")
        occurrences_by_id[occurrence_id] = record
        canonical_occurrences[record["canonical_url"]].add(occurrence_id)
        topic_occurrences[record["topic_id"]].add(occurrence_id)

    if len(canonical_occurrences) != manifest["unique_url_count"]:
        raise EditorialSnapshotError(
            "Unique canonical URLs in occurrences do not match manifest.unique_url_count"
        )

    mapped_occurrences: dict[str, str] = {}
    canonical_urls: set[str] = set()
    url_ids: set[str] = set()
    for record in url_records:
        _validate_url_record(record)
        url_id = record["url_id"]
        canonical_url = record["canonical_url"]
        if url_id in url_ids:
            raise EditorialSnapshotError(f"Duplicate url_id: {url_id}")
        if canonical_url in canonical_urls:
            raise EditorialSnapshotError(f"Duplicate canonical URL record: {canonical_url}")
        url_ids.add(url_id)
        canonical_urls.add(canonical_url)
        occurrence_ids = record["occurrence_ids"]
        if record["occurrence_count"] != len(occurrence_ids):
            raise EditorialSnapshotError(
                f"URL record {url_id} occurrence_count does not match occurrence_ids"
            )
        if len(set(occurrence_ids)) != len(occurrence_ids):
            raise EditorialSnapshotError(f"URL record {url_id} repeats an occurrence_id")
        for occurrence_id in occurrence_ids:
            if occurrence_id not in occurrences_by_id:
                raise EditorialSnapshotError(
                    f"URL record {url_id} references unknown occurrence {occurrence_id}"
                )
            if occurrence_id in mapped_occurrences:
                raise EditorialSnapshotError(
                    f"Occurrence {occurrence_id} maps to more than one URL record"
                )
            if occurrences_by_id[occurrence_id]["canonical_url"] != canonical_url:
                raise EditorialSnapshotError(
                    f"Occurrence {occurrence_id} canonical URL does not match {url_id}"
                )
            mapped_occurrences[occurrence_id] = url_id
        if set(occurrence_ids) != canonical_occurrences.get(canonical_url, set()):
            raise EditorialSnapshotError(
                f"URL record {url_id} does not list every matching occurrence"
            )

    if set(mapped_occurrences) != set(occurrences_by_id):
        raise EditorialSnapshotError("Every occurrence must map to exactly one URL record")
    _validate_topic_mappings(topics, topic_occurrences, set(occurrences_by_id))
    return manifest


def _is_tracking_parameter(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith("utm_") or lowered in _TRACKING_QUERY_NAMES


def _read_report_sections(report: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    topics = report.get("topics")
    source_health = report.get("source_health")
    if not isinstance(topics, list) or not all(isinstance(item, dict) for item in topics):
        raise EditorialSnapshotError("Topic Radar report must contain a topics array")
    if not isinstance(source_health, list) or not all(
        isinstance(item, dict) for item in source_health
    ):
        raise EditorialSnapshotError("Topic Radar report must contain a source_health array")
    return topics, source_health


def _build_occurrences(
    topics: list[dict[str, Any]], source_health: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_names: dict[str, str] = {}
    for source in source_health:
        source_id = _required_string(source, "id", "source-health record")
        source_names[source_id] = _required_string(source, "name", "source-health record")

    pending: list[dict[str, Any]] = []
    topic_metadata: dict[str, dict[str, Any]] = {}
    for topic in topics:
        topic_id = _required_string(topic, "id", "topic")
        if topic_id in topic_metadata:
            raise EditorialSnapshotError(f"Duplicate topic id: {topic_id}")
        label = _required_string(topic, "label", f"topic {topic_id}")
        lane = _required_string(topic, "lane", f"topic {topic_id}")
        items = topic.get("items")
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise EditorialSnapshotError(f"Topic {topic_id} must contain an items array")
        topic_metadata[topic_id] = {
            "id": topic_id,
            "label": label,
            "lane": lane,
            "total_recent": topic.get("total_recent"),
            "term_counts": topic.get("term_counts"),
            "selection": topic.get("selection"),
        }
        for item in items:
            pipeline_item_id = _required_string(item, "id", f"topic {topic_id} item")
            original_url = _required_string(
                item, "url", f"topic {topic_id} item {pipeline_item_id}"
            )
            source_ids = item.get("source_ids")
            if not isinstance(source_ids, list) or not source_ids or not all(
                isinstance(source_id, str) and source_id.strip() for source_id in source_ids
            ):
                raise EditorialSnapshotError(
                    f"Topic item {pipeline_item_id} must contain non-empty source_ids"
                )
            feed_ids = sorted(set(source_ids))
            feed_names = [source_names.get(source_id, source_id) for source_id in feed_ids]
            topic_matches = item.get("topic_matches", {})
            matched_terms = (
                topic_matches.get(topic_id, []) if isinstance(topic_matches, dict) else []
            )
            if not isinstance(matched_terms, list):
                matched_terms = []
            pending.append(
                {
                    "pipeline_item_id": pipeline_item_id,
                    "topic_id": topic_id,
                    "topic": label,
                    "topic_lane": lane,
                    "feed_id": feed_ids[0],
                    "feed_name": feed_names[0],
                    "feed_ids": feed_ids,
                    "feed_names": feed_names,
                    "title": _required_string(
                        item, "title", f"topic item {pipeline_item_id}"
                    ),
                    "published_at": _required_string(
                        item, "published_at", f"topic item {pipeline_item_id}"
                    ),
                    "original_url": original_url,
                    "canonical_url": canonicalize_url(original_url),
                    "matched_terms": sorted(
                        {term for term in matched_terms if isinstance(term, str)}
                    ),
                }
            )

    pending.sort(
        key=lambda item: (
            item["topic_id"],
            item["pipeline_item_id"],
            item["original_url"],
            item["feed_ids"],
        )
    )
    topic_occurrence_ids: defaultdict[str, list[str]] = defaultdict(list)
    occurrences: list[dict[str, Any]] = []
    for index, item in enumerate(pending, start=1):
        record = {"occurrence_id": f"occ_{index:06d}", **item}
        occurrences.append(record)
        topic_occurrence_ids[item["topic_id"]].append(record["occurrence_id"])

    topic_records = []
    for topic_id in sorted(topic_metadata):
        metadata = topic_metadata[topic_id]
        topic_records.append(
            {
                **metadata,
                "selected_item_count": len(topic_occurrence_ids[topic_id]),
                "occurrence_ids": topic_occurrence_ids[topic_id],
            }
        )
    return occurrences, topic_records


def _build_url_records(occurrences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for occurrence in occurrences:
        grouped[occurrence["canonical_url"]].append(occurrence)
    records = []
    for index, canonical_url in enumerate(sorted(grouped), start=1):
        matches = grouped[canonical_url]
        records.append(
            {
                "url_id": f"url_{index:06d}",
                "canonical_url": canonical_url,
                "domain": urlsplit(canonical_url).hostname,
                "occurrence_count": len(matches),
                "occurrence_ids": sorted(item["occurrence_id"] for item in matches),
                "topic_ids": sorted({item["topic_id"] for item in matches}),
                "topics": sorted({item["topic"] for item in matches}),
                "feed_ids": sorted(
                    {feed_id for item in matches for feed_id in item["feed_ids"]}
                ),
                "feed_names": sorted(
                    {feed_name for item in matches for feed_name in item["feed_names"]}
                ),
            }
        )
    return records


def _write_shards(
    root: Path,
    kind: str,
    records: list[dict[str, Any]],
    shard_size: int,
) -> list[dict[str, Any]]:
    entries = []
    for index, start in enumerate(range(0, len(records), shard_size), start=1):
        chunk = records[start : start + shard_size]
        relative_path = f"{kind}/{index:03d}.json"
        path = root / relative_path
        _write_json(
            path,
            {
                "schema_version": EDITORIAL_INPUT_SCHEMA,
                "shard_type": kind,
                "shard_index": index,
                "record_count": len(chunk),
                "records": chunk,
            },
        )
        entries.append(
            {
                "path": relative_path,
                "record_count": len(chunk),
                "sha256": _sha256(path),
            }
        )
    return entries


def _read_shards(
    root: Path,
    manifest: dict[str, Any],
    manifest_field: str,
    kind: str,
) -> list[dict[str, Any]]:
    entries = manifest.get(manifest_field)
    if not isinstance(entries, list):
        raise EditorialSnapshotError(f"Manifest {manifest_field} must be an array")
    listed_paths: set[str] = set()
    records: list[dict[str, Any]] = []
    for expected_index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise EditorialSnapshotError(f"Manifest {manifest_field} entries must be objects")
        path_value = _required_string(entry, "path", f"manifest {manifest_field} entry")
        expected_path = f"{kind}/{expected_index:03d}.json"
        if path_value != expected_path:
            raise EditorialSnapshotError(
                f"Shard ordering/path mismatch: expected {expected_path}, got {path_value}"
            )
        if path_value in listed_paths:
            raise EditorialSnapshotError(f"Duplicate shard path: {path_value}")
        listed_paths.add(path_value)
        path = _safe_relative_path(root, path_value)
        _validate_checksum(path, entry.get("sha256"))
        payload = _read_json_object(path, f"shard {path_value}")
        _validate_payload_schema(payload, f"shard {path_value}")
        if payload.get("shard_type") != kind or payload.get("shard_index") != expected_index:
            raise EditorialSnapshotError(f"Shard metadata mismatch: {path_value}")
        shard_records = payload.get("records")
        if not isinstance(shard_records, list) or not all(
            isinstance(record, dict) for record in shard_records
        ):
            raise EditorialSnapshotError(f"Shard {path_value} must contain a records array")
        record_count = entry.get("record_count")
        if (
            not isinstance(record_count, int)
            or isinstance(record_count, bool)
            or record_count != len(shard_records)
            or payload.get("record_count") != len(shard_records)
        ):
            raise EditorialSnapshotError(f"Shard record count mismatch: {path_value}")
        if len(shard_records) > manifest["shard_size"]:
            raise EditorialSnapshotError(f"Shard exceeds configured size: {path_value}")
        records.extend(shard_records)

    shard_directory = root / kind
    if not shard_directory.is_dir():
        raise EditorialSnapshotError(f"Missing shard directory: {kind}")
    actual_paths = {
        path.relative_to(root).as_posix() for path in shard_directory.glob("*.json")
    }
    if actual_paths != listed_paths:
        raise EditorialSnapshotError(
            f"Shard files on disk do not exactly match manifest {manifest_field}"
        )
    return records


def _validate_occurrence(record: dict[str, Any]) -> None:
    for field in (
        "occurrence_id",
        "pipeline_item_id",
        "topic_id",
        "topic",
        "topic_lane",
        "feed_id",
        "feed_name",
        "title",
        "published_at",
        "original_url",
        "canonical_url",
    ):
        _required_string(record, field, "occurrence record")
    if not _OCCURRENCE_ID.fullmatch(record["occurrence_id"]):
        raise EditorialSnapshotError(
            f"Invalid occurrence_id: {record['occurrence_id']}"
        )
    for field in ("feed_ids", "feed_names", "matched_terms"):
        value = record.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise EditorialSnapshotError(f"Occurrence {field} must be a string array")
    if not record["feed_ids"] or not record["feed_names"]:
        raise EditorialSnapshotError("Occurrence feed provenance must not be empty")
    if canonicalize_url(record["original_url"]) != record["canonical_url"]:
        raise EditorialSnapshotError(
            f"Occurrence {record['occurrence_id']} has an invalid canonical_url"
        )


def _validate_url_record(record: dict[str, Any]) -> None:
    _required_string(record, "url_id", "URL record")
    canonical = _required_string(record, "canonical_url", "URL record")
    if canonicalize_url(canonical) != canonical:
        raise EditorialSnapshotError(f"URL record is not canonical: {canonical}")
    count = record.get("occurrence_count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise EditorialSnapshotError("URL record occurrence_count must be positive")
    occurrence_ids = record.get("occurrence_ids")
    if not isinstance(occurrence_ids, list) or not all(
        isinstance(item, str) for item in occurrence_ids
    ):
        raise EditorialSnapshotError("URL record occurrence_ids must be a string array")


def _validate_topic_mappings(
    topics: list[Any],
    expected: dict[str, set[str]],
    all_occurrence_ids: set[str],
) -> None:
    seen_topic_ids: set[str] = set()
    mapped: set[str] = set()
    for topic in topics:
        if not isinstance(topic, dict):
            raise EditorialSnapshotError("Every topic record must be an object")
        topic_id = _required_string(topic, "id", "topic record")
        if topic_id in seen_topic_ids:
            raise EditorialSnapshotError(f"Duplicate topic id in topics.json: {topic_id}")
        seen_topic_ids.add(topic_id)
        occurrence_ids = topic.get("occurrence_ids")
        if not isinstance(occurrence_ids, list) or not all(
            isinstance(item, str) for item in occurrence_ids
        ):
            raise EditorialSnapshotError(f"Topic {topic_id} occurrence_ids must be an array")
        if len(occurrence_ids) != topic.get("selected_item_count"):
            raise EditorialSnapshotError(f"Topic {topic_id} selected_item_count is invalid")
        if set(occurrence_ids) != expected.get(topic_id, set()):
            raise EditorialSnapshotError(f"Topic {topic_id} occurrence mapping is incomplete")
        mapped.update(occurrence_ids)
    if mapped != all_occurrence_ids:
        raise EditorialSnapshotError("topics.json does not map every occurrence")


def _resolve_relative_file(root: Path, manifest: dict[str, Any], field: str) -> Path:
    value = _required_string(manifest, field, "manifest")
    return _safe_relative_path(root, value)


def _safe_relative_path(root: Path, value: str) -> Path:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise EditorialSnapshotError(f"Snapshot path must be relative and contained: {value}")
    path = root.joinpath(*relative.parts)
    if not path.is_file():
        raise EditorialSnapshotError(f"Snapshot file is missing: {value}")
    return path


def _validate_payload_schema(payload: dict[str, Any], label: str) -> None:
    if payload.get("schema_version") != EDITORIAL_INPUT_SCHEMA:
        raise EditorialSnapshotError(f"{label} has an unsupported schema_version")


def _validate_checksum(path: Path, expected: Any) -> None:
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise EditorialSnapshotError(f"Invalid SHA-256 value for {path.name}")
    actual = _sha256(path)
    if actual != expected:
        raise EditorialSnapshotError(f"SHA-256 mismatch for {path.as_posix()}")


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise EditorialSnapshotError(f"Could not read {label}: {error}") from error
    except json.JSONDecodeError as error:
        raise EditorialSnapshotError(f"Malformed JSON in {label}: {error}") from error
    if not isinstance(value, dict):
        raise EditorialSnapshotError(f"{label} must contain a JSON object")
    return value


def _required_string(record: dict[str, Any], field: str, label: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EditorialSnapshotError(f"{label} is missing required field {field}")
    return value


def _require_non_empty_string(record: dict[str, Any], field: str, label: str) -> None:
    _required_string(record, field, label)


def _require_positive_integer(record: dict[str, Any], field: str) -> None:
    value = record.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise EditorialSnapshotError(f"Manifest {field} must be a positive integer")


def _require_non_negative_integer(record: dict[str, Any], field: str) -> None:
    value = record.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise EditorialSnapshotError(f"Manifest {field} must be a non-negative integer")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
