"""Append-only accepted observation directories and a disposable raw-bundle cache."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request

from . import __version__
from .validation import (canonical, digest, file_hash, jsonl, loads, read_json, require,
                         safe_name, timestamp, unpack_bundle, validate_receipt, validate_snapshot)

CATALOG_FIELDS = ("role", "refid", "source_occurrence_id", "archive_ordinal", "archive_sha256",
                  "member_ordinal", "member_path", "member_sha256", "member_size_bytes",
                  "member_type", "parse_status", "selected")


def _regular(path: Path):
    require(path.is_file() and not path.is_symlink(), f"Missing or linked file: {path}")


def _directory(path: Path):
    # Reject linked ancestors as well as the final directory on both Windows/Unix.
    for part in (path, *path.parents):
        require(not part.is_symlink() and not getattr(part, "is_junction", lambda: False)(),
                f"Linked storage directory: {part}")
    path.mkdir(parents=True, exist_ok=True)


def load_receipt(source: str) -> dict:
    if source.startswith("https://"):
        require(source.startswith("https://github.com/") and source.endswith("/evidence.json"),
                "Expected a public GitHub release evidence.json URL")
        with urllib.request.urlopen(source, timeout=120) as stream:
            data = stream.read(1024 * 1024 + 1)
        require(len(data) <= 1024 * 1024, "Receipt is too large")
        receipt = validate_receipt(loads(data))
        require(source == receipt["receipt_url"], "Requested receipt URL differs from verified identity")
        return receipt
    require("://" not in source, "Only local files or public HTTPS GitHub receipts are supported")
    path = Path(source)
    _regular(path)
    return validate_receipt(read_json(path))


def _observation_path(repository: Path, identity: str) -> Path:
    require(digest(identity), "Expected a full observation ID")
    return repository / "observations" / identity


def read_observation(repository: Path, identity: str) -> tuple[dict, dict, list[dict]]:
    path = _observation_path(repository, identity)
    for part in (path, *path.parents):
        require(not part.is_symlink() and not getattr(part, "is_junction", lambda: False)(),
                f"Linked ledger directory: {part}")
    for name in ("receipt.json", "observation.json", "members.jsonl", "source-observations.json"):
        _regular(path / name)
    receipt = validate_receipt(read_json(path / "receipt.json"))
    require(receipt["observation_id"] == identity, "Ledger directory/receipt identity mismatch")
    summary = read_json(path / "observation.json")
    require(summary.get("contract") == "history-observation-v1" and summary.get("observation_id") == identity
            and summary.get("receipt_sha256") == file_hash(path / "receipt.json")
            and summary.get("catalog_sha256") == file_hash(path / "members.jsonl")
            and summary.get("source_observation_sha256") == file_hash(path / "source-observations.json"),
            "Stored observation payload changed")
    require(summary.get("canonical_status") == "not_verified"
            and summary.get("legal_valid_time") == {"status": "unresolved", "from": None, "until": None},
            "Unsupported derived state in observation ledger")
    rows = list(jsonl(path / "members.jsonl"))
    require(len(rows) == summary["member_count"], "Stored member catalog count changed")
    return receipt, summary, rows


def ensure_bundle(repository: Path, receipt: dict, local: Path | None = None) -> Path:
    cache = repository / ".cache" / "bundles"
    _directory(cache)
    target = cache / (receipt["bundle"]["sha256"] + ".tar.gz")
    expected_size, expected_hash = receipt["bundle"]["bytes"], receipt["bundle"]["sha256"]
    if target.exists():
        _regular(target)
        require(target.stat().st_size == expected_size and file_hash(target) == expected_hash,
                "Cached bundle is corrupt; remove this cache file and retry")
        if local is not None:
            _regular(local)
            require(local.stat().st_size == expected_size and file_hash(local) == expected_hash,
                    "Explicit local bundle differs from receipt")
        return target
    fd, name = tempfile.mkstemp(prefix="download-", suffix=".tmp", dir=cache)
    temporary = Path(name)
    try:
        checksum, size = hashlib.sha256(), 0
        with os.fdopen(fd, "wb") as output:
            if local is not None:
                _regular(local)
                incoming = local.open("rb")
            else:
                incoming = urllib.request.urlopen(receipt["bundle"]["url"], timeout=120)
            with incoming:
                while chunk := incoming.read(1024 * 1024):
                    size += len(chunk)
                    require(size <= expected_size, "Downloaded bundle exceeds declared size")
                    checksum.update(chunk); output.write(chunk)
        require((size, checksum.hexdigest()) == (expected_size, expected_hash), "Downloaded bundle size/digest mismatch")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def ingest(source: str, repository: Path, bundle: Path | None = None) -> dict:
    receipt = load_receipt(source)
    identity = receipt["observation_id"]
    destination = _observation_path(repository, identity)
    _directory(repository)
    _directory(repository / "observations")
    if destination.exists():
        previous, summary, _ = read_observation(repository, identity)
        require(canonical(previous) == canonical(receipt), "Same observation identity has changed payload")
        if bundle is not None:
            _regular(bundle)
            require(file_hash(bundle) == receipt["bundle"]["sha256"]
                    and bundle.stat().st_size == receipt["bundle"]["bytes"], "Explicit bundle differs on replay")
        return {"status": "already_present", **summary}
    if bundle is None and not source.startswith("https://"):
        sibling = Path(source).parent / "snapshot.tar.gz"
        if sibling.exists():
            bundle = sibling
    retained = ensure_bundle(repository, receipt, bundle)
    _directory(repository / ".cache")
    with tempfile.TemporaryDirectory(prefix="validate-", dir=repository / ".cache") as temp:
        stage = Path(temp)
        names = unpack_bundle(retained, stage, receipt)
        manifest, observation, members = validate_snapshot(stage, names)
        require(manifest["version"] == receipt["snapshot_version"], "Receipt/snapshot version mismatch")
        accepted = stage / "accepted"
        accepted.mkdir()
        (accepted / "receipt.json").write_bytes(canonical(receipt, newline=True))
        shutil.copyfile(stage / "source-observations.json", accepted / "source-observations.json")
        with (accepted / "members.jsonl").open("wb") as output:
            for member in members:
                output.write(canonical({field: member[field] for field in CATALOG_FIELDS}, newline=True))
        summary = {
            "contract": "history-observation-v1", "consumer_version": __version__,
            "observation_id": identity, "receipt_sha256": file_hash(accepted / "receipt.json"),
            "source_observation_sha256": manifest["artifact_hashes"]["source-observations.json"],
            "catalog_sha256": file_hash(accepted / "members.jsonl"),
            "knowledge_cutoff": observation["knowledge_cutoff"],
            "knowledge_cutoff_basis": "local_archive_observation", "historical_knowledge_time_status": "unknown",
            "canonical_status": "not_verified", "legal_valid_time": {"status": "unresolved", "from": None, "until": None},
            "member_count": len(members), "archive_count": len(observation["archives"]),
            "parsed_occurrence_counts": manifest["evidence"]["parsed_occurrence_counts"],
            "unresolved_member_count": manifest["evidence"]["unresolved_member_count"],
            "parsed_amendment_count": manifest["evidence"]["parsed_amendment_count"],
            "scope": [{"role": a["role"], "original_filename": a["original_filename"], "prefixes": a["prefixes"]}
                      for a in observation["archives"]],
            "data_attribution": receipt["data_attribution"],
            "durable_bundle_url": receipt["bundle"]["url"],
            "receipt_url": receipt["receipt_url"],
        }
        (accepted / "observation.json").write_bytes(canonical(summary, newline=True))
        # Atomic directory publication: a failed verification cannot alter prior observations.
        try:
            accepted.rename(destination)
        except OSError:
            if not destination.exists():
                raise
            existing, previous, _ = read_observation(repository, identity)
            require(canonical(existing) == canonical(receipt) and previous == summary, "Concurrent observation conflict")
            return {"status": "already_present", **summary}
    return {"status": "accepted", **summary}


def list_observations(repository: Path) -> list[dict]:
    directory = repository / "observations"
    if not directory.exists():
        return []
    results = []
    for path in directory.iterdir():
        require(path.is_dir() and not path.is_symlink() and digest(path.name), f"Unexpected observation ledger entry: {path.name}")
        _, summary, _ = read_observation(repository, path.name)
        results.append(summary)
    return sorted(results, key=lambda row: (row["knowledge_cutoff"] or "", row["observation_id"]))


def show_document(repository: Path, refid: str, role: str | None = None) -> dict:
    require(isinstance(refid, str) and "/" in refid, "Expected a document refid such as lov/1998-07-17-56")
    require(role is None or role in {"laws", "forskrifter", "amendment_acts"}, "Unknown source archive role")
    observations = []
    known_roles, previous_scope = set(), set()
    for summary in list_observations(repository):
        _, _, members = read_observation(repository, summary["observation_id"])
        found = [row for row in members if row["refid"] == refid and (role is None or row["role"] == role)]
        scope = {(s["role"], s["original_filename"], tuple(s["prefixes"])) for s in summary["scope"]
                 if role is None or s["role"] == role}
        if found:
            known_roles.update(row["role"] for row in found)
            previous_scope = {s for s in scope if s[0] in known_roles}
            observations.append({"observation_id": summary["observation_id"], "observed_at": summary["knowledge_cutoff"],
                                 "status": "present", "members": found})
        elif known_roles:
            comparable = previous_scope <= scope
            observations.append({"observation_id": summary["observation_id"], "observed_at": summary["knowledge_cutoff"],
                                 "status": "not_present_in_observation" if comparable else "scope_not_comparable",
                                 "scope_comparable": comparable,
                                 "members": []})
    return {"refid": refid, **({"source_role": role} if role is not None else {}), "canonical_status": "not_verified",
            "legal_valid_time": {"status": "unresolved", "from": None, "until": None},
            "observations": observations}


def raw_member(repository: Path, identity: str, refid: str, occurrence: str | None = None) -> bytes:
    receipt, _, catalog = read_observation(repository, identity)
    candidates = [row for row in catalog if row["refid"] == refid and row["member_type"] == "file"
                  and (occurrence is None or row["source_occurrence_id"] == occurrence)]
    require(len(candidates) == 1, "Document source is missing or ambiguous; use a source_occurrence_id from show")
    selected = candidates[0]
    bundle = ensure_bundle(repository, receipt)
    archive_name = safe_name(f'raw/{selected["archive_sha256"]}.tar.bz2')
    # No tar extraction: copy exactly one verified raw archive into a temporary file.
    with tempfile.TemporaryDirectory(prefix="raw-", dir=repository / ".cache") as temp:
        raw_path = Path(temp) / "source.tar.bz2"
        with tarfile.open(bundle, "r:gz") as outer:
            matches = [item for item in outer if item.name == archive_name]
            require(len(matches) == 1 and matches[0].isfile(), "Retained raw archive is missing/ambiguous")
            with outer.extractfile(matches[0]) as source, raw_path.open("wb") as output:
                shutil.copyfileobj(source, output)
        require(file_hash(raw_path) == selected["archive_sha256"], "Retained archive digest mismatch")
        with tarfile.open(raw_path, "r:bz2") as raw:
            for ordinal, member in enumerate(raw):
                if ordinal == selected["member_ordinal"]:
                    require(member.isfile() and member.name == selected["member_path"]
                            and member.size == selected["member_size_bytes"], "Retrieved source member identity mismatch")
                    with raw.extractfile(member) as stream:
                        content = stream.read()
                    require(hashlib.sha256(content).hexdigest() == selected["member_sha256"], "Retrieved XML digest mismatch")
                    return content
    raise ValueError("Retained source member ordinal missing")
