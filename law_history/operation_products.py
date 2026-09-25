"""Append-only, source-bound amendment evidence; no legal dates are inferred."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import gzip
import hashlib
import os
from pathlib import Path, PurePosixPath
import platform
import re
import tarfile
import tempfile
import zlib

from .ledger import CATALOG_FIELDS, _directory, _regular, ensure_bundle, list_observations, read_observation
from .operations import VERSION, CLAIM_VERSION, _identity, extract_act
from .validation import canonical, digest, file_hash, jsonl, loads, read_json, require, safe_name, unpack_bundle, validate_snapshot, value_hash

CONTRACT = "history-operation-product-v1"
SHARD_ACTS = 1000
INPUT_PROOFS = {"input-manifest.json", "source-members.jsonl.gz"}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _loaded_generator_identity():
    package = Path(__file__).parent
    return {"contract": CONTRACT, "extractor": VERSION,
            "sources": {name: _sha((package / name).read_bytes().replace(b"\r\n", b"\n"))
                        for name in ("operation_products.py", "operations.py", "validation.py")},
            "python": platform.python_version(), "zlib": zlib.ZLIB_RUNTIME_VERSION}


# Keep the startup source identity with the loaded implementation. Reading source
# files anew on every replay can label old running code with a later disk edit.
_GENERATOR_IDENTITY = _loaded_generator_identity()


def generator_identity():
    return deepcopy(_GENERATOR_IDENTITY)


def read_operation_receipt(repository: Path, identity: str) -> dict:
    """Check the immutable Git receipt without fetching release artifacts.

    This verifies identity, schema and declared inventories, not source evidence
    or public release availability. Use ``read_operation_product`` for those.
    """
    require(digest(identity), "Expected an operation product digest")
    root = repository / "operation-products" / identity
    for path in (root, *root.parents):
        require(not path.is_symlink() and not getattr(path, "is_junction", lambda: False)(), "Linked operation product")
    _regular(root / "receipt.json")
    receipt = read_json(root / "receipt.json")
    require((root / "receipt.json").read_bytes() == canonical(receipt, newline=True), "Noncanonical operation receipt")
    core = {k: v for k, v in receipt.items() if k not in {"operation_product_id", "release_tag"}}
    core["bundle"] = {k: v for k, v in receipt.get("bundle", {}).items() if k != "url"}
    require(receipt.get("contract") == CONTRACT and receipt.get("operation_product_id") == identity
            and _sha(canonical(core, newline=True)) == identity, "Operation product identity changed")
    require(digest(receipt.get("observation_id")) and (receipt.get("parent_operation_product_id") is None
            or digest(receipt.get("parent_operation_product_id"))), "Invalid operation product lineage")
    require(receipt.get("legal_valid_time_status") == "unresolved"
            and receipt.get("coverage") == "all_producer_parsed_act_occurrences_not_source_operation_completeness",
            "Unsupported operation product claim")
    project = receipt.get("repository")
    require(isinstance(project, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", project)
            and receipt.get("release_tag") == "operations-" + identity
            and receipt["bundle"].get("name") == "operations.tar.gz"
            and digest(receipt["bundle"].get("sha256"))
            and type(receipt["bundle"].get("bytes")) is int and receipt["bundle"]["bytes"] > 0
            and receipt["bundle"].get("url") == f"https://github.com/{project}/releases/download/operations-{identity}/operations.tar.gz",
            "Invalid operation release transport identity")
    require({p.name for p in root.iterdir()} == {"receipt.json"}, "Only the operation receipt belongs in Git")
    hashes = receipt.get("artifact_hashes")
    require(isinstance(hashes, dict) and hashes and "index.jsonl.gz" in hashes, "Missing operation artifacts")
    for name, checksum in hashes.items():
        require(safe_name(name) == name and digest(checksum), "Invalid operation artifact identity")
    require(all(digest(receipt.get(name)) for name in (
        "snapshot_manifest_sha256", "source_observation_sha256", "parsed_acts_sha256")),
        "Invalid operation input identity")
    counts = receipt.get("counts", {})
    require(all(isinstance(counts.get(k), int) and not isinstance(counts[k], bool) and counts[k] >= 0
                for k in ("acts", "operations", "claims"))
            and counts["claims"] == counts["acts"] + counts["operations"], "Invalid operation inventory counts")
    shards = receipt.get("shards")
    require(isinstance(shards, list) and all(isinstance(s, str) for s in shards)
            and len(shards) == len(set(shards)) and set(hashes) == set(shards) | {"index.jsonl.gz"} | INPUT_PROOFS,
            "Invalid operation shard inventory")
    require(shards == [f"acts/{n:05d}.jsonl.gz" for n in range((counts["acts"] + SHARD_ACTS - 1) // SHARD_ACTS)],
            "Operation shard inventory differs from act count")
    return receipt


def read_operation_product(repository: Path, identity: str, *, ledger_repository: Path | None = None,
                           artifacts: Path | None = None) -> dict:
    receipt = read_operation_receipt(repository, identity)
    root = artifacts if artifacts is not None else artifact_tree(ledger_repository or repository, receipt)
    hashes, counts, shards = receipt["artifact_hashes"], receipt["counts"], receipt["shards"]
    actual = set()
    for path in root.rglob("*"):
        require(not path.is_symlink() and not getattr(path, "is_junction", lambda: False)(), "Linked operation artifact")
        if path.is_file(): actual.add(path.relative_to(root).as_posix())
    require(actual == set(hashes), "Operation artifact membership changed")
    for name, checksum in hashes.items():
        _regular(root / name)
        require(file_hash(root / name) == checksum, "Operation artifact bytes changed")
    rows = list(_gzip_rows(root / "index.jsonl.gz"))
    require(len(rows) == counts["acts"] and len({r["source_occurrence_id"] for r in rows}) == len(rows)
            and sum(r["operations"] for r in rows) == counts["operations"], "Operation index counts changed")
    for ordinal, row in enumerate(rows):
        require(row["ordinal"] == ordinal and row["shard"] == f"acts/{ordinal // SHARD_ACTS:05d}.jsonl.gz"
                and row["shard"] in shards and digest(row["source_occurrence_id"])
                and digest(row["parsed_revision_id"]) and digest(row["record_sha256"]), "Invalid operation index row")
    source_acts, source_observation = _bound_catalog(ledger_repository or repository, root, receipt)
    require(len(rows) == len(source_acts) and all(
        row["source_occurrence_id"] == member["source_occurrence_id"]
        and row["parsed_revision_id"] == _identity("history-parsed-act-revision-v1",
            [member["source_occurrence_id"], member["parsed_model_sha256"]])
        for row, member in zip(rows, source_acts)), "Operation index differs from accepted source inventory")
    _verify_records(root, receipt, rows, source_acts, source_observation)
    return receipt


def artifact_tree(repository, receipt):
    """Rehydrate immutable release artifacts into a disposable, verified cache."""
    root = repository / ".cache" / "operation-artifacts" / receipt["operation_product_id"]
    if root.exists():
        require(root.is_dir() and not root.is_symlink() and not getattr(root, "is_junction", lambda: False)(),
                "Linked operation artifact cache")
        return root
    from .operation_transport import ensure_bundle as ensure_operation_bundle
    bundle = ensure_operation_bundle(repository, receipt)
    _directory(root.parent)
    with tempfile.TemporaryDirectory(prefix="unpack-", dir=root.parent) as temporary:
        stage = Path(temporary) / "artifacts"; stage.mkdir()
        seen = set()
        with tarfile.open(bundle, "r|gz") as stream:
            for member in stream:
                name = safe_name(member.name)
                require(member.isfile() and name in receipt["artifact_hashes"] and name not in seen,
                        "Unexpected or linked operation bundle member")
                seen.add(name)
                target = stage / name; target.parent.mkdir(parents=True, exist_ok=True)
                checksum = hashlib.sha256()
                with stream.extractfile(member) as incoming, target.open("xb") as output:
                    while chunk := incoming.read(1024 * 1024): checksum.update(chunk); output.write(chunk)
                require(checksum.hexdigest() == receipt["artifact_hashes"][name], "Operation bundle member changed")
        require(seen == set(receipt["artifact_hashes"]), "Operation bundle omitted artifacts")
        try:
            stage.rename(root)
        except FileExistsError:
            require(root.is_dir(), "Operation cache installation conflict")
    return root


def _bundle_artifacts(output, path, hashes):
    with path.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0, compresslevel=1) as zipped:
        with tarfile.open(fileobj=zipped, mode="w|") as bundle:
            for name in sorted(hashes):
                source = output / name
                require(file_hash(source) == hashes[name], "Operation artifact changed before bundling")
                info = tarfile.TarInfo(name); info.size = source.stat().st_size
                info.mode = 0o644; info.mtime = 0
                with source.open("rb") as incoming: bundle.addfile(info, incoming)
    return {"name": "operations.tar.gz", "sha256": file_hash(path), "bytes": path.stat().st_size}


def _bound_catalog(repository, root, receipt):
    release, summary, accepted = read_observation(repository, receipt["observation_id"])
    manifest_path = root / "input-manifest.json"
    require(file_hash(manifest_path) == release["snapshot_manifest_sha256"] == receipt["snapshot_manifest_sha256"]
            and receipt["source_receipt_url"] == release["receipt_url"], "Operation product input receipt binding changed")
    manifest = read_json(manifest_path)
    hashes = manifest["artifact_hashes"]
    source_path = repository / "observations" / receipt["observation_id"] / "source-observations.json"
    source = read_json(source_path)
    require(hashes["source-observations.json"] == file_hash(source_path) == receipt["source_observation_sha256"]
            and hashes["parsed-amendment-acts.v1.jsonl"] == receipt["parsed_acts_sha256"]
            and source["knowledge_cutoff"] == summary["knowledge_cutoff"] == receipt["knowledge_cutoff"],
            "Operation product source clock or artifact binding changed")
    checksum, members = hashlib.sha256(), []
    with gzip.open(root / "source-members.jsonl.gz", "rb") as stream:
        for line in stream:
            checksum.update(line); members.append(loads(line))
    require(checksum.hexdigest() == hashes["source-members.jsonl"], "Operation source catalog differs from accepted manifest")
    require([{field: row[field] for field in CATALOG_FIELDS} for row in members] == accepted,
            "Operation source catalog differs from accepted ledger")
    acts = sorted((m for m in members if m["role"] == "amendment_acts" and m["parse_status"] == "parsed"),
                  key=lambda m: m["parsed_occurrence_ordinal"])
    require([m["parsed_occurrence_ordinal"] for m in acts] == list(range(len(acts)))
            and len(acts) == summary["parsed_occurrence_counts"]["amendment_acts"]
            == manifest["evidence"]["parsed_occurrence_counts"]["amendment_acts"] == receipt["counts"]["acts"]
            and summary["parsed_amendment_count"] == manifest["evidence"]["parsed_amendment_count"]
            == receipt["counts"]["operations"], "Operation counts differ from accepted source inventory")
    return acts, source


def _verify_records(root, receipt, index, source_acts, source_observation):
    cursor = iter(index)
    counts = {"acts": 0, "operations": 0, "claims": 0}
    for name in receipt["shards"]:
        for row in _gzip_rows(root / name):
            entry = next(cursor, None)
            require(entry is not None and entry["shard"] == name
                    and entry["record_sha256"] == _sha(canonical(row, newline=True)), "Operation shard/index mismatch")
            act, operations, claims = row["act"], row["operations"], row["claims"]
            source_member = source_acts[counts["acts"]]
            occurrence, model_sha = act["source_occurrence_id"], act["parsed_model_sha256"]
            require(row["contract"] == VERSION and act["contract"] == VERSION
                    and act["refid"] == entry["refid"] == source_member["refid"]
                    and occurrence == entry["source_occurrence_id"]
                    and act["parsed_revision_id"] == entry["parsed_revision_id"]
                    and act["act_id"] == _identity("history-act-occurrence-v1", occurrence)
                    and act["parsed_revision_id"] == _identity("history-parsed-act-revision-v1", [occurrence, model_sha])
                    and value_hash(act["producer_envelope"]["record"]) == model_sha
                    and act["source_member"]["parsed_model_sha256"] == model_sha
                    and act["source_member"] == source_member
                    and act["producer_envelope"]["source_occurrence_id"] == occurrence
                    and act["producer_envelope"]["parsed_occurrence_ordinal"] == source_member["parsed_occurrence_ordinal"]
                    and act["parsed_evidence"]["parsed_occurrence_ordinal"] == source_member["parsed_occurrence_ordinal"],
                    "Operation act/revision binding changed")
            require(act["context"]["observation_id"] == receipt["observation_id"]
                    and act["context"]["snapshot_manifest_sha256"] == receipt["snapshot_manifest_sha256"]
                    and act["context"]["source_observation_sha256"] == receipt["source_observation_sha256"]
                    and act["parsed_evidence"]["artifact_sha256"] == receipt["parsed_acts_sha256"]
                    and act["clocks"]["knowledge_cutoff"] == receipt["knowledge_cutoff"],
                    "Operation observation binding changed")
            archive = source_observation["archives"][source_member["archive_ordinal"]]
            original = act["producer_envelope"]["record"]
            expected_clocks = {
                "knowledge_cutoff": source_observation["knowledge_cutoff"],
                "knowledge_cutoff_basis": source_observation["knowledge_cutoff_basis"],
                "observed_at": archive["observed_at"], "retrieved_at": archive["retrieved_at"],
                "retrieval_time_status": archive["retrieval_time_status"],
                "historical_knowledge_time": {"status": "unknown", "at": None},
                "source_last_modified": archive["source_last_modified"],
                "source_date_published": original["date_published"],
                "source_date_in_force": original["date_in_force"],
                "release_publication": {"status": "unknown", "assertion": None},
            }
            require(act["clocks"] == expected_clocks, "Operation source clocks changed or historical dates were inferred")
            require(act["expression_coverage"]["status"] == "candidates_only_not_complete"
                    and act["expression_coverage"]["scope_assignment"] == "not_performed"
                    and act["operation_coverage"] == "all_operations_in_producer_model_not_source_completeness"
                    and all(e["legal_scope_status"] == "unresolved" for e in act["commencement_expressions"]),
                    "Operation candidate scope became an unsupported interpretation")
            require(isinstance(operations, list) and len(operations) == entry["operations"]
                    and [op["producer_record"] for op in operations] == act["producer_envelope"]["record"]["amendments"],
                    "Operation inventory differs from preserved original act")
            subjects = [{"kind": "act", "id": act["act_id"], "parsed_revision_id": act["parsed_revision_id"]}]
            for ordinal, op in enumerate(operations):
                identity = _identity("history-operation-revision-v1", [occurrence, model_sha, ordinal])
                require(op["operation_id"] == identity and op["operation_ordinal"] == ordinal
                        and op["act_id"] == act["act_id"]
                        and op["source_occurrence_id"] == occurrence and op["parsed_model_sha256"] == model_sha
                        and op["parsed_revision_id"] == act["parsed_revision_id"]
                        and op["observation_id"] == receipt["observation_id"]
                        and op["parsed_evidence"]["parsed_occurrence_ordinal"] == source_member["parsed_occurrence_ordinal"]
                        and op["target_resolution"]["status"] == "unresolved", "Operation identity/status changed")
                subjects.append({"kind": "operation", "id": identity})
            require(isinstance(claims, list) and [c["subject"] for c in claims] == subjects, "Initial claim subjects changed")
            for claim in claims:
                require(claim["contract"] == CLAIM_VERSION and claim["source_occurrence_id"] == occurrence
                        and claim["observation_id"] == receipt["observation_id"] and claim["clocks"] == act["clocks"]
                        and claim["claim_id"] == _identity(CLAIM_VERSION, {k: v for k, v in claim.items() if k != "claim_id"})
                        and claim["supersedes"] == [] and claim["legal_valid_time"]["status"] == "unresolved"
                        and claim["legal_valid_time"]["from"] is None and claim["legal_valid_time"]["until"] is None
                        and claim["method"] == "retain_unresolved_no_legal_interpretation-v1"
                        and claim["expression_scope_assignment"] == "unresolved"
                        and claim["target_resolution_status"] == (
                            "unresolved" if claim["subject"]["kind"] == "operation" else "not_applicable"),
                        "Initial legal claim changed or became an unsupported interpretation")
            counts["acts"] += 1; counts["operations"] += len(operations); counts["claims"] += len(claims)
    require(next(cursor, None) is None and counts == receipt["counts"], "Operation shard counts differ from receipt/index")


def operation_products(repository: Path, *, verify: bool = True) -> list[dict]:
    """Read the chain; explicit audits verify every product by default.

    Orchestration may check only Git receipts, then fully verify new or selected
    products without downloading all prior immutable releases again.
    """
    directory = repository / "operation-products"
    if not directory.exists(): return []
    require(directory.is_dir() and not directory.is_symlink()
            and not getattr(directory, "is_junction", lambda: False)(), "Linked operation product directory")
    entries = {}
    for path in directory.iterdir():
        require(path.is_dir() and digest(path.name), "Unexpected operation product entry")
        reader = read_operation_product if verify else read_operation_receipt
        entries[path.name] = reader(repository, path.name)
    ordered, parent = [], None
    while len(ordered) < len(entries):
        children = [r for r in entries.values() if r["parent_operation_product_id"] == parent]
        require(len(children) == 1, "Operation product chain is disconnected or forked")
        item = children[0]
        require(item not in ordered, "Cyclic operation product chain")
        ordered.append(item); parent = item["operation_product_id"]
    return ordered


def _gzip_rows(path):
    with gzip.open(path, "rb") as stream:
        for line in stream:
            row = loads(line)
            require(line == canonical(row, newline=True), "Noncanonical operation row")
            yield row


@contextmanager
def _gzip_writer(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0, compresslevel=9) as output:
            yield output


def _ordered_sources(snapshot, selected, source_bytes):
    """Follow producer archive/prefix order without buffering the XML corpus."""
    observation = loads(source_bytes)
    for archive in observation["archives"]:
        if archive["role"] != "amendment_acts": continue
        path = snapshot / archive["raw_path"]
        require(file_hash(path) == archive["archive_sha256"], "Operation archive changed")
        for prefix in archive["prefixes"]:
            wanted = {m["member_ordinal"]: m for m in selected
                      if m["archive_ordinal"] == archive["archive_ordinal"]
                      and PurePosixPath(m["member_path"]).name.startswith(prefix)}
            with tarfile.open(path, "r|bz2") as stream:
                for ordinal, member in enumerate(stream):
                    if ordinal not in wanted: continue
                    catalog = wanted.pop(ordinal)
                    require(member.isfile() and member.name == catalog["member_path"]
                            and member.size == catalog["member_size_bytes"], "Operation member changed")
                    with stream.extractfile(member) as incoming: raw = incoming.read()
                    yield catalog, raw
            require(not wanted, "Operation archive omitted declared members")


def _generate(snapshot, output, release, manifest, members):
    manifest_bytes = (snapshot / "manifest.json").read_bytes()
    source_bytes = (snapshot / "source-observations.json").read_bytes()
    counts = {"acts": 0, "operations": 0, "claims": 0}
    diagnostics = {"zero_operation_acts": 0, "empty_replacement_operations": 0,
                   "producer_unknown_operations": 0, "unresolved_candidate_targets": 0,
                   "uniquely_aligned_instructions": 0, "commencement_candidates": 0}
    parsed = iter(jsonl(snapshot / "parsed-amendment-acts.v1.jsonl"))
    selected = [m for m in members if m["role"] == "amendment_acts" and m["parse_status"] == "parsed"]
    shards = []
    shard_context = shard = None
    try:
        with _gzip_writer(output / "index.jsonl.gz") as index:
            for catalog, raw in _ordered_sources(snapshot, selected, source_bytes):
                envelope = next(parsed, None)
                require(envelope is not None and envelope["source_occurrence_id"] == catalog["source_occurrence_id"],
                        "Parsed act order differs from source catalog")
                evidence = extract_act(envelope, raw, member=catalog, receipt=release,
                                       manifest_bytes=manifest_bytes, source_observation_bytes=source_bytes)
                ordinal = counts["acts"]
                if ordinal % SHARD_ACTS == 0:
                    if shard_context is not None: shard_context.__exit__(None, None, None)
                    name = f"acts/{ordinal // SHARD_ACTS:05d}.jsonl.gz"
                    shards.append(name); shard_context = _gzip_writer(output / name)
                    shard = shard_context.__enter__()
                content = canonical(evidence, newline=True)
                shard.write(content)
                index.write(canonical({"ordinal": ordinal, "refid": catalog["refid"],
                    "source_occurrence_id": catalog["source_occurrence_id"],
                    "parsed_revision_id": evidence["act"]["parsed_revision_id"],
                    "operations": len(evidence["operations"]), "shard": name,
                    "record_sha256": _sha(content)}, newline=True))
                counts["acts"] += 1; counts["operations"] += len(evidence["operations"])
                counts["claims"] += len(evidence["claims"])
                diagnostics["zero_operation_acts"] += not evidence["operations"]
                diagnostics["commencement_candidates"] += len(evidence["act"]["commencement_expressions"])
                for op in evidence["operations"]:
                    original = op["producer_record"]
                    diagnostics["empty_replacement_operations"] += not original["new_text"]
                    diagnostics["producer_unknown_operations"] += original["change_type"] == "unknown"
                    diagnostics["unresolved_candidate_targets"] += not original["target_law"]
                    diagnostics["uniquely_aligned_instructions"] += op["source_alignment"]["status"] == "unique_text_match"
        require(next(parsed, None) is None and counts["acts"] == len(selected)
                and counts["operations"] == manifest["evidence"]["parsed_amendment_count"],
                "Operation product does not cover the full producer inventory")
    finally:
        if shard_context is not None: shard_context.__exit__(None, None, None)
        close = getattr(parsed, "close", None)
        if close: close()
    require(all((output / name).stat().st_size < 50 * 1024 * 1024 for name in shards), "Operation shard exceeds bounded artifact size")
    return counts, diagnostics, shards


def extract_operations(repository: Path, observation_id: str, expected_parent="auto", snapshot: Path | None = None,
                       github_repository="sondreskarsten/norwegian-laws-history", *, verify_replay: bool = True) -> dict:
    """Validate the complete accepted input, then atomically append a full product.

    ``snapshot`` can reuse an already unpacked local bundle. Every declared file,
    raw member and model is still checked against the accepted release identity.
    Routine catch-up can skip artifact revalidation for an identical accepted
    receipt; explicit extraction revalidates that matching product by default.
    """
    repository = Path(repository).absolute()
    require(isinstance(github_repository, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", github_repository),
            "Expected a public GitHub operation-product destination")
    _directory(repository / ".cache")
    lock = repository / ".cache" / "operation-writer.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError("An operation writer lock exists; inspect the prior writer before retrying") from exc
    try:
        os.close(fd)
        chain = operation_products(repository, verify=False)
        parent = chain[-1]["operation_product_id"] if chain else None
        require(expected_parent == "auto" or expected_parent == parent
                or expected_parent == "none" and parent is None, "Operation product parent changed")
        generator = generator_identity()
        for prior in chain:
            if (prior["observation_id"] == observation_id and prior["generator"] == generator
                    and prior["repository"] == github_repository):
                if verify_replay:
                    read_operation_product(repository, prior["operation_product_id"])
                return {"status": "already_present", **prior}
        release, summary, accepted_members = read_observation(repository, observation_id)
        _directory(repository / "operation-products")
        with tempfile.TemporaryDirectory(prefix="operations-", dir=repository / ".cache") as temporary:
            work = Path(temporary)
            if snapshot is None:
                source = work / "snapshot"; source.mkdir()
                names = unpack_bundle(ensure_bundle(repository, release), source, release)
            else:
                source = Path(snapshot)
                _regular(source / "manifest.json")
                manifest = read_json(source / "manifest.json")
                names = set(manifest["artifact_hashes"]) | {"manifest.json"}
            require(file_hash(source / "manifest.json") == release["snapshot_manifest_sha256"], "Operation snapshot identity mismatch")
            manifest, observation, members = validate_snapshot(source, names)
            require(manifest["artifact_hashes"]["source-observations.json"] == summary["source_observation_sha256"]
                    and [m["source_occurrence_id"] for m in members] == [m["source_occurrence_id"] for m in accepted_members],
                    "Operation input differs from accepted observation")
            output = work / "product"; output.mkdir()
            counts, diagnostics, shards = _generate(source, output, release, manifest, members)
            (output / "input-manifest.json").write_bytes((source / "manifest.json").read_bytes())
            with (source / "source-members.jsonl").open("rb") as incoming:
                with _gzip_writer(output / "source-members.jsonl.gz") as compressed:
                    while chunk := incoming.read(1024 * 1024): compressed.write(chunk)
            core = {"contract": CONTRACT, "repository": github_repository, "observation_id": observation_id,
                    "parent_operation_product_id": parent, "generator": generator,
                    "source_receipt_url": release["receipt_url"], "snapshot_manifest_sha256": release["snapshot_manifest_sha256"],
                    "source_observation_sha256": summary["source_observation_sha256"],
                    "parsed_acts_sha256": manifest["artifact_hashes"]["parsed-amendment-acts.v1.jsonl"],
                    "knowledge_cutoff": observation["knowledge_cutoff"],
                    "legal_valid_time_status": "unresolved",
                    "coverage": "all_producer_parsed_act_occurrences_not_source_operation_completeness",
                    "counts": counts, "diagnostics": diagnostics, "shards": shards,
                    "artifact_hashes": {name: file_hash(output / name) for name in ["index.jsonl.gz", *shards, *sorted(INPUT_PROOFS)]}}
            bundle = work / "operations.tar.gz"
            core["bundle"] = _bundle_artifacts(output, bundle, core["artifact_hashes"])
            identity = _sha(canonical(core, newline=True))
            tag = "operations-" + identity
            receipt = {**core, "operation_product_id": identity, "release_tag": tag,
                       "bundle": {**core["bundle"], "url": f"https://github.com/{github_repository}/releases/download/{tag}/operations.tar.gz"}}
            # Validate the complete staged shard content before accepting a directory.
            staging = work / "operation-products" / identity
            staging.mkdir(parents=True)
            (staging / "receipt.json").write_bytes(canonical(receipt, newline=True))
            verified = read_operation_product(work, identity, ledger_repository=repository, artifacts=output)
            cache = repository / ".cache" / "operation-bundles"
            _directory(cache)
            cached_bundle = cache / (receipt["bundle"]["sha256"] + ".tar.gz")
            if cached_bundle.exists():
                require(file_hash(cached_bundle) == receipt["bundle"]["sha256"], "Existing operation bundle cache changed")
            else:
                bundle.rename(cached_bundle)
            artifact_cache = repository / ".cache" / "operation-artifacts" / identity
            _directory(artifact_cache.parent)
            if not artifact_cache.exists(): output.rename(artifact_cache)
            destination = repository / "operation-products" / identity
            require(not destination.exists(), "Operation product destination exists outside replay")
            staging.rename(destination)
            return {"status": "accepted", **verified}
    finally:
        lock.unlink()


def extract_all(repository: Path, github_repository="sondreskarsten/norwegian-laws-history") -> list[dict]:
    return [extract_operations(repository, item["observation_id"], github_repository=github_repository, verify_replay=False)
            for item in list_observations(repository)]


def show_operations(repository: Path, refid: str, product_id: str | None = None) -> dict:
    chain = operation_products(repository, verify=False)
    require(bool(chain), "No operation evidence has been published")
    selected = next((r for r in chain if r["operation_product_id"] == product_id), None) if product_id else chain[-1]
    require(selected is not None, "Unknown operation product")
    selected = read_operation_product(repository, selected["operation_product_id"])
    root = artifact_tree(repository, selected)
    wanted = {r["source_occurrence_id"]: r for r in _gzip_rows(root / "index.jsonl.gz") if r["refid"] == refid}
    results = []
    for name in sorted({r["shard"] for r in wanted.values()}):
        for row in _gzip_rows(root / name):
            occurrence = row["act"]["source_occurrence_id"]
            if occurrence in wanted:
                index = wanted.pop(occurrence)
                require(_sha(canonical(row, newline=True)) == index["record_sha256"], "Operation record/index binding changed")
                results.append(row)
    require(not wanted, "Operation index references a missing act")
    return {"operation_product_id": selected["operation_product_id"], "observation_id": selected["observation_id"],
            "refid": refid, "status": "found" if results else "not_in_parsed_act_inventory", "occurrences": results}
