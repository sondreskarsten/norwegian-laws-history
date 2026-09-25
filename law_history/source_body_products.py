"""Full selected v5 corpus qualification, separate from the frozen pilot.

Only passed bodies receive reader payloads. Rejection is inventoried, never
rendered as passed text. These are observed source bodies, not legal states.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import gzip
import hashlib
import html
import os
from pathlib import Path
import platform
import re
import tarfile
import tempfile
import zlib

from .body_transport import ensure_bundle, _validate_bundle
from .ledger import CATALOG_FIELDS, _directory, _regular, ensure_bundle as source_bundle, list_observations, read_observation
from .source_body_gate import GATE_VERSION, MAX_BYTES, qualify_source_body
from .validation import canonical, digest, file_hash, loads, read_json, require, safe_name, timestamp, unpack_bundle, validate_snapshot, value_hash

CONTRACT = "history-source-body-product-v1"
NAME = "bodies.tar.gz"
SHARD_DOCUMENTS = 100
FIXED_ARTIFACTS = {"inventory.jsonl.gz", "last-qualified.jsonl.gz"}
LEGAL = {"status": "unresolved", "from": None, "until": None}
_TOKEN = object()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


_GENERATOR = {"contract": CONTRACT, "gate": GATE_VERSION,
    "sources": {name: _sha((Path(__file__).parent / name).read_bytes().replace(b"\r\n", b"\n"))
                for name in ("source_body_products.py", "source_body_gate.py", "validation.py", "ledger.py", "body_transport.py")},
    "python": platform.python_version(), "zlib": zlib.ZLIB_RUNTIME_VERSION}


def generator_identity():
    return deepcopy(_GENERATOR)


@contextmanager
def _gzip_writer(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream, gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0, compresslevel=6) as output:
        yield output


def _rows(path):
    with gzip.open(path, "rb") as stream:
        for line in stream:
            row = loads(line)
            require(isinstance(row, dict) and line == canonical(row, newline=True), "Noncanonical body product row")
            yield row


def _no_links(path):
    for item in (path, *path.parents):
        require(not item.is_symlink() and not getattr(item, "is_junction", lambda: False)(), "Linked body product storage")


def read_body_receipt(repository: Path, identity: str) -> dict:
    require(digest(identity), "Expected a body product digest")
    root = Path(repository) / "body-products" / identity; _no_links(root)
    _regular(root / "receipt.json")
    receipt = read_json(root / "receipt.json")
    require(isinstance(receipt, dict) and set(receipt) == {"contract", "repository", "observation_id",
        "parent_body_product_id", "comparison_product_id", "generator", "gate_version", "coverage", "legal_valid_time", "knowledge_cutoff",
        "source_receipt_url", "source_bundle_sha256", "snapshot_manifest_sha256", "source_observation_sha256",
        "counts", "shards", "artifact_hashes", "bundle", "body_product_id", "release_tag"}, "Unsupported body receipt fields")
    require((root / "receipt.json").read_bytes() == canonical(receipt, newline=True), "Noncanonical body receipt")
    core = {key: value for key, value in receipt.items() if key not in {"body_product_id", "release_tag"}}
    core["bundle"] = {key: value for key, value in receipt.get("bundle", {}).items() if key != "url"}
    require(receipt.get("contract") == CONTRACT and receipt.get("body_product_id") == identity
            and _sha(canonical(core, newline=True)) == identity, "Body product identity changed")
    require(digest(receipt.get("observation_id")) and (receipt.get("parent_body_product_id") is None
            or digest(receipt["parent_body_product_id"])) and (receipt.get("comparison_product_id") is None
            or digest(receipt["comparison_product_id"])), "Invalid body product lineage")
    project = receipt.get("repository"); bundle = receipt.get("bundle", {})
    require(isinstance(project, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", project)
            and receipt.get("release_tag") == "bodies-" + identity and bundle.get("name") == NAME
            and digest(bundle.get("sha256")) and type(bundle.get("bytes")) is int and bundle["bytes"] > 0
            and bundle.get("url") == f"https://github.com/{project}/releases/download/bodies-{identity}/{NAME}",
            "Invalid body release descriptor")
    require(receipt.get("coverage") == "all_selected_laws_and_regulations_in_accepted_v5_snapshot"
            and receipt.get("legal_valid_time") == LEGAL, "Unsupported body product scope or legal claim")
    require(all(digest(receipt.get(key)) for key in
                ("source_bundle_sha256", "snapshot_manifest_sha256", "source_observation_sha256")), "Invalid body source identity")
    if receipt["knowledge_cutoff"] is not None: timestamp(receipt["knowledge_cutoff"])
    counts, hashes, shards = receipt.get("counts", {}), receipt.get("artifact_hashes"), receipt.get("shards")
    require(set(counts) == {"selected", "laws", "forskrifter", "passed", "rejected"}
            and all(type(value) is int and value >= 0 for value in counts.values())
            and counts["selected"] == counts["laws"] + counts["forskrifter"] == counts["passed"] + counts["rejected"],
            "Invalid body qualification counts")
    require(isinstance(hashes, dict) and isinstance(shards, list) and len(shards) == len(set(shards))
            and shards == sorted(shards) and all(re.fullmatch(r"documents/[0-9]{5}\.jsonl\.gz", name) for name in shards)
            and set(hashes) == FIXED_ARTIFACTS | set(shards), "Invalid body artifact inventory")
    require(all(safe_name(name) == name and digest(sha) for name, sha in hashes.items()), "Invalid body artifact digest")
    require({path.name for path in root.iterdir()} == {"receipt.json"}, "Only the body receipt belongs in Git")
    return receipt


def body_products(repository: Path, *, verify=True) -> list[dict]:
    directory = Path(repository) / "body-products"
    if not directory.exists(): return []
    _no_links(directory); require(directory.is_dir(), "Body products path is not a directory")
    entries = {}
    for path in directory.iterdir():
        require(path.is_dir() and digest(path.name), "Unexpected body product entry")
        entries[path.name] = read_body_receipt(repository, path.name)
    ordered, parent = [], None
    while len(ordered) < len(entries):
        children = [row for row in entries.values() if row["parent_body_product_id"] == parent]
        require(len(children) == 1 and children[0] not in ordered, "Body product chain is disconnected, forked or cyclic")
        require(children[0]["comparison_product_id"] is None or children[0]["comparison_product_id"] in
                {row["body_product_id"] for row in ordered}, "Body comparison is outside its ancestor prefix")
        ordered.append(children[0]); parent = children[0]["body_product_id"]
    if verify:
        for row in ordered: read_body_product(repository, row["body_product_id"])
    return ordered


def _comparison(repository, parent, observation_id, project, *, chain=None):
    """Select a prior representation without using later source knowledge.

    Global append order and source observation order are distinct. Historical
    reprocessing appends to the former but compares only within the latter.
    """
    chain = body_products(repository, verify=False) if chain is None else chain
    prefix = []
    if parent is not None:
        positions = [i for i, row in enumerate(chain) if row["body_product_id"] == parent]
        require(len(positions) == 1, "Body product parent is not in the accepted chain")
        prefix = chain[:positions[0] + 1]
    accepted = list_observations(repository)
    summaries = {row["observation_id"]: row for row in accepted}
    require(observation_id in summaries, "Body source observation is not accepted")
    # Keep the ledger's deterministic tie ordering, while refusing a source
    # clock to claim knowledge later than the selected target's actual clock.
    ranks = {row["observation_id"]: i for i, row in enumerate(accepted)}
    cutoff = summaries[observation_id]["knowledge_cutoff"]
    candidates = []
    for position, row in enumerate(prefix):
        source = summaries.get(row["observation_id"])
        require(source is not None and row["knowledge_cutoff"] == source["knowledge_cutoff"],
                "Ancestor body source clock differs from accepted observation")
        old_cutoff = source["knowledge_cutoff"]
        no_later_clock = old_cutoff is None or cutoff is not None and timestamp(old_cutoff) <= timestamp(cutoff)
        if row["repository"] == project and ranks[row["observation_id"]] <= ranks[observation_id] and no_later_clock:
            candidates.append((ranks[row["observation_id"]], position, row["body_product_id"]))
    return max(candidates)[2] if candidates else None


def _check_artifacts(root, receipt):
    _no_links(root); require(root.is_dir(), "Body artifact cache is missing")
    actual = set()
    for path in root.rglob("*"):
        _no_links(path)
        if path.is_file(): actual.add(path.relative_to(root).as_posix())
    require(actual == set(receipt["artifact_hashes"]), "Body artifact membership changed")
    for name, checksum in receipt["artifact_hashes"].items():
        _regular(root / name); require(file_hash(root / name) == checksum, "Body artifact bytes changed")


def artifact_tree(repository: Path, receipt: dict) -> Path:
    root = Path(repository) / ".cache/body-artifacts" / receipt["body_product_id"]
    if not root.exists():
        bundle = ensure_bundle(repository, receipt)
        _directory(root.parent)
        with tempfile.TemporaryDirectory(prefix="unpack-", dir=root.parent) as temporary:
            stage = Path(temporary) / "artifacts"; stage.mkdir()
            with tarfile.open(bundle, "r|gz") as stream:
                for member in stream:
                    name = safe_name(member.name)
                    require(member.isfile() and not member.issparse() and name in receipt["artifact_hashes"], "Invalid body member")
                    path = stage / name; path.parent.mkdir(parents=True, exist_ok=True)
                    with stream.extractfile(member) as incoming, path.open("xb") as output:
                        while chunk := incoming.read(1024 * 1024): output.write(chunk)
            _check_artifacts(stage, receipt)
            try: stage.rename(root)
            except FileExistsError: pass
    _check_artifacts(root, receipt)
    return root


@dataclass(frozen=True)
class _ValidatedInput:
    token: object
    repository: Path
    root: Path
    release: dict
    summary: dict
    manifest: dict
    observation: dict
    members: list


@contextmanager
def _input(repository, observation_id, snapshot=None):
    release, summary, accepted = read_observation(repository, observation_id)
    require(release["snapshot_version"] == 5, "Rich body qualification requires accepted snapshot v5")
    _directory(repository / ".cache")
    with tempfile.TemporaryDirectory(prefix="body-input-", dir=repository / ".cache") as temporary:
        if snapshot is None:
            root = Path(temporary) / "snapshot"; root.mkdir()
            names = unpack_bundle(source_bundle(repository, release), root, release)
        else:
            root = Path(snapshot)
            names = set(read_json(root / "manifest.json")["artifact_hashes"]) | {"manifest.json"}
        require(file_hash(root / "manifest.json") == release["snapshot_manifest_sha256"], "Body source snapshot identity changed")
        manifest, observation, members = validate_snapshot(root, names)
        require(manifest["version"] == 5 and manifest["artifact_hashes"]["source-observations.json"] == summary["source_observation_sha256"]
                and [{key: row[key] for key in CATALOG_FIELDS} for row in members] == accepted,
                "Body input differs from accepted observation")
        yield _ValidatedInput(_TOKEN, repository, root, release, summary, manifest, observation, members)


def _selected(source):
    return [row for row in source.members if row["role"] in ("laws", "forskrifter") and row["selected"]]


def _documents(source):
    """Yield one selected raw member/model at a time, in catalog archive order."""
    chosen = _selected(source)
    for archive in source.observation["archives"]:
        wanted = {row["member_ordinal"]: row for row in chosen if row["archive_ordinal"] == archive["archive_ordinal"]}
        if not wanted: continue
        path = source.root / archive["raw_path"]
        require(file_hash(path) == archive["archive_sha256"], "Body raw archive changed")
        with tarfile.open(path, "r|bz2") as stream:
            for ordinal, member in enumerate(stream):
                if ordinal not in wanted: continue
                row = wanted.pop(ordinal)
                require(member.isfile() and member.name == row["member_path"] and member.size == row["member_size_bytes"]
                        and member.size <= MAX_BYTES, "Body raw member identity/size changed")
                with stream.extractfile(member) as incoming: raw = incoming.read(MAX_BYTES + 1)
                require(len(raw) == member.size and _sha(raw) == row["member_sha256"], "Body raw member bytes changed")
                model_path = source.root / row["selected_output_path"]
                require(file_hash(model_path) == row["selected_output_sha256"], "Selected body model bytes changed")
                model = read_json(model_path)
                require(value_hash(model) == row["parsed_model_sha256"], "Selected body model identity changed")
                yield row, raw, model
        require(not wanted, "Body archive omitted selected members")


def _prior(repository, parent):
    if parent is None: return {}
    receipt = read_body_receipt(repository, parent)
    root = artifact_tree(repository, receipt)
    found = {}
    for row in _rows(root / "last-qualified.jsonl.gz"):
        require(row["refid"] not in found and (row["body_product_id"] == "self" or digest(row["body_product_id"])),
                "Invalid prior qualified inventory")
        value = deepcopy(row)
        if value["body_product_id"] == "self": value["body_product_id"] = parent
        found[row["refid"]] = value
    return found


def _html(refid, fragment, stylesheet):
    return ('<!doctype html>\n<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>' + html.escape(refid) + '</title><style>' + stylesheet + '</style></head><body>' + fragment + '</body></html>\n')


def _classification(old, record):
    if old is None: return "first_qualified_body"
    if old["semantic_sha256"] == record["semantic_sha256"]:
        return "unchanged" if all(old[key] == record[key] for key in ("html_sha256", "stylesheet_sha256")) else "representation_change"
    return "representation_change" if old["raw_member_sha256"] == record["raw_member_sha256"] else "observed_body_change"


def _generate(source, output, prior):
    baseline = deepcopy(prior)
    counts = {"selected": 0, "laws": 0, "forskrifter": 0, "passed": 0, "rejected": 0}
    shards, current_name, context, shard = [], None, None, None
    try:
        with _gzip_writer(output / "inventory.jsonl.gz") as inventory:
            for ordinal, (member, raw, model) in enumerate(_documents(source)):
                body = model["source_body"]
                result = qualify_source_body(raw, body, expected_member_sha256=member["member_sha256"],
                    expected_refid=member["refid"], source_occurrence_id=member["source_occurrence_id"])
                status = result["report"]["status"]
                require(status in ("passed", "rejected"), "Unsupported body qualification status")
                record = {"ordinal": ordinal, "refid": member["refid"], "role": member["role"], "source_member": member,
                    "source_occurrence_id": member["source_occurrence_id"], "raw_member_sha256": member["member_sha256"],
                    "parsed_model_sha256": member["parsed_model_sha256"], "selected_model_sha256": member["selected_output_sha256"],
                    "source_body_model_sha256": value_hash(body), "body_sha256": body["body_sha256"],
                    "semantic_sha256": body["semantic_sha256"], "status": status, "qualification": result["report"],
                    "comparison": prior.get(member["refid"]), "change": "not_qualified", "payload": None}
                if status == "passed":
                    require(result["html"] is not None and result["stylesheet"] is not None, "Passed body omitted reader payload")
                    document = {"refid": member["refid"], "source_occurrence_id": member["source_occurrence_id"],
                                "source_body": body, "html": _html(member["refid"], result["html"], result["stylesheet"]),
                                "stylesheet": result["stylesheet"]}
                    name = f"documents/{ordinal // SHARD_DOCUMENTS:05d}.jsonl.gz"
                    if current_name != name:
                        if context is not None: context.__exit__(None, None, None)
                        current_name = name; shards.append(name)
                        context = _gzip_writer(output / name); shard = context.__enter__()
                    data = canonical(document, newline=True); shard.write(data)
                    record.update(html_sha256=_sha(document["html"].encode("utf-8")),
                                  stylesheet_sha256=_sha(document["stylesheet"].encode("utf-8")),
                                  payload={"shard": name, "record_sha256": _sha(data)})
                    record["change"] = _classification(record["comparison"], record)
                    baseline[member["refid"]] = {"body_product_id": "self", **{key: record[key] for key in
                        ("refid", "source_occurrence_id", "raw_member_sha256", "body_sha256", "semantic_sha256", "html_sha256", "stylesheet_sha256")}}
                else:
                    require(result["html"] is None and result["stylesheet"] is None and result["report"].get("reasons"),
                            "Rejected body must have reasons and no reader payload")
                inventory.write(canonical(record, newline=True))
                counts["selected"] += 1; counts[member["role"]] += 1; counts[status] += 1
    finally:
        if context is not None: context.__exit__(None, None, None)
    require(counts["selected"] == len(_selected(source)) == source.manifest["law_count"] + source.manifest["forskrift_count"],
            "Body qualification did not cover every selected document")
    with _gzip_writer(output / "last-qualified.jsonl.gz") as stream:
        for refid in sorted(baseline): stream.write(canonical(baseline[refid], newline=True))
    return counts, shards


def _audit(source, receipt, root, prior):
    require(source.token is _TOKEN and source.release["observation_id"] == receipt["observation_id"], "Wrong validated body input")
    require(receipt["source_receipt_url"] == source.release["receipt_url"]
            and receipt["source_bundle_sha256"] == source.release["bundle"]["sha256"]
            and receipt["snapshot_manifest_sha256"] == source.release["snapshot_manifest_sha256"]
            and receipt["source_observation_sha256"] == source.summary["source_observation_sha256"]
            and receipt["knowledge_cutoff"] == source.observation["knowledge_cutoff"]
            and receipt["gate_version"] == GATE_VERSION, "Body product source/gate binding changed")
    with tempfile.TemporaryDirectory(prefix="body-audit-", dir=source.repository / ".cache") as temporary:
        expected = Path(temporary)
        counts, shards = _generate(source, expected, prior)
        require(counts == receipt["counts"] and shards == receipt["shards"], "Body qualification inventory changed")
        for name in receipt["artifact_hashes"]:
            # The published gzip bytes retain their own exact digest. Comparing
            # canonical uncompressed bytes permits equivalent zlib runtimes.
            with gzip.open(root / name, "rb") as actual, gzip.open(expected / name, "rb") as rebuilt:
                require(hashlib.file_digest(actual, "sha256").hexdigest() == hashlib.file_digest(rebuilt, "sha256").hexdigest(),
                        "Body qualification or prior-qualified inventory differs from source")


def read_body_product(repository: Path, identity: str, *, snapshot: Path | None = None,
                      ledger_repository: Path | None = None, artifacts: Path | None = None, _validated=None) -> dict:
    """Full audit: exact artifact bytes, validated v5 source, all gate outcomes."""
    repository = Path(repository).absolute(); ledger = Path(ledger_repository or repository).absolute()
    receipt = read_body_receipt(repository, identity)
    root = Path(artifacts) if artifacts is not None else artifact_tree(ledger, receipt)
    _check_artifacts(root, receipt)
    comparison = _comparison(ledger, receipt["parent_body_product_id"], receipt["observation_id"], receipt["repository"])
    require(receipt["comparison_product_id"] == comparison, "Body comparison differs from eligible accepted source history")
    prior = _prior(ledger, comparison)
    if _validated is not None:
        require(isinstance(_validated, _ValidatedInput) and _validated.token is _TOKEN and _validated.repository == ledger,
                "Invalid invocation-local validation context")
        _audit(_validated, receipt, root, prior)
    else:
        with _input(ledger, receipt["observation_id"], snapshot) as source: _audit(source, receipt, root, prior)
    return receipt


def _bundle(output, path, hashes):
    with path.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0, compresslevel=1) as zipped:
        with tarfile.open(fileobj=zipped, mode="w|") as stream:
            for name in sorted(hashes):
                file = output / name; require(file_hash(file) == hashes[name], "Body artifact changed before bundling")
                info = tarfile.TarInfo(name); info.size = file.stat().st_size; info.mode = 0o644; info.mtime = 0
                with file.open("rb") as incoming: stream.addfile(info, incoming)
    return {"name": NAME, "sha256": file_hash(path), "bytes": path.stat().st_size}


def qualify_bodies(repository: Path, observation_id: str, expected_parent="auto", snapshot: Path | None = None,
                   github_repository="sondreskarsten/norwegian-laws-history", *, verify_replay=True, reuse_existing_observation=False) -> dict:
    repository = Path(repository).absolute(); _directory(repository / ".cache")
    require(isinstance(github_repository, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", github_repository), "Invalid body repository")
    lock = repository / ".cache/body-writer.lock"
    try: descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc: raise ValueError("Body writer lock exists; inspect its prior writer before retrying") from exc
    try:
        os.close(descriptor)
        chain = body_products(repository, verify=False)
        parent = chain[-1]["body_product_id"] if chain else None
        require(expected_parent == "auto" or expected_parent == parent or expected_parent == "none" and parent is None,
                "Body product parent changed")
        generator = generator_identity()
        for old in reversed(chain):
            if old["observation_id"] == observation_id and old["repository"] == github_repository and (reuse_existing_observation or old["generator"] == generator):
                if verify_replay: read_body_product(repository, old["body_product_id"], snapshot=snapshot)
                return {"status": "already_present", **old}
        comparison = _comparison(repository, parent, observation_id, github_repository, chain=chain)
        prior = _prior(repository, comparison)
        with _input(repository, observation_id, snapshot) as source, tempfile.TemporaryDirectory(prefix="body-product-", dir=repository / ".cache") as temporary:
            work = Path(temporary); output = work / "artifacts"; output.mkdir()
            counts, shards = _generate(source, output, prior)
            hashes = {name: file_hash(output / name) for name in [*sorted(FIXED_ARTIFACTS), *shards]}
            bundle = work / NAME
            core = {"contract": CONTRACT, "repository": github_repository, "observation_id": observation_id,
                "parent_body_product_id": parent, "comparison_product_id": comparison, "generator": generator, "gate_version": GATE_VERSION,
                "coverage": "all_selected_laws_and_regulations_in_accepted_v5_snapshot", "legal_valid_time": deepcopy(LEGAL),
                "knowledge_cutoff": source.observation["knowledge_cutoff"], "source_receipt_url": source.release["receipt_url"],
                "source_bundle_sha256": source.release["bundle"]["sha256"], "snapshot_manifest_sha256": source.release["snapshot_manifest_sha256"],
                "source_observation_sha256": source.summary["source_observation_sha256"], "counts": counts, "shards": shards,
                "artifact_hashes": hashes, "bundle": _bundle(output, bundle, hashes)}
            identity = _sha(canonical(core, newline=True)); tag = "bodies-" + identity
            receipt = {**core, "body_product_id": identity, "release_tag": tag,
                       "bundle": {**core["bundle"], "url": f"https://github.com/{github_repository}/releases/download/{tag}/{NAME}"}}
            stage = work / "body-products" / identity; stage.mkdir(parents=True)
            (stage / "receipt.json").write_bytes(canonical(receipt, newline=True))
            verified = read_body_product(work, identity, ledger_repository=repository, artifacts=output, _validated=source)
            cache = repository / ".cache/body-bundles"; _directory(cache)
            target = cache / (receipt["bundle"]["sha256"] + ".tar.gz")
            if target.exists(): _validate_bundle(target, receipt)
            else: os.link(bundle, target)
            artifacts = repository / ".cache/body-artifacts" / identity; _directory(artifacts.parent)
            if artifacts.exists(): _check_artifacts(artifacts, receipt)
            else: output.rename(artifacts)
            destination = repository / "body-products" / identity; _directory(destination.parent)
            require(not destination.exists(), "Unexpected existing body product destination")
            stage.rename(destination)
            return {"status": "accepted", **verified}
    finally:
        lock.unlink()


def qualify_all(repository: Path, github_repository="sondreskarsten/norwegian-laws-history") -> list[dict]:
    results = []
    for observation in list_observations(repository):
        release, _, _ = read_observation(repository, observation["observation_id"])
        if release["snapshot_version"] != 5: continue
        results.append(qualify_bodies(repository, observation["observation_id"], github_repository=github_repository,
                                      verify_replay=False, reuse_existing_observation=True))
    return results
