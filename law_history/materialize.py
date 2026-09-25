"""Append-only, bounded observed-body projections; never historical legal states."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import tarfile
import tempfile

from .ledger import _directory, _regular, ensure_bundle, list_observations, read_observation
from .structure import VERSION, qualify
from .validation import canonical, digest, file_hash, read_json, require, safe_name, unpack_bundle, validate_snapshot

CONTRACT = "history-materialization-v1"
PILOT_REFIDS = (
    "lov/1845-06-07", "lov/1949-07-28-15", "forskrift/2022-09-02-1529",
    "lov/1916-07-21-2", "lov/2011-04-15-11", "lov/1967-12-15-9",
    "forskrift/2026-09-18-1871",
)


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def generator_identity():
    package = Path(__file__).parent
    return {"contract": VERSION, "materializer": CONTRACT,
            "source_sha256": {name: _hash((package / name).read_bytes().replace(b"\r\n", b"\n"))
                              for name in ("materialize.py", "structure.py")},
            "python": platform.python_version(), "implementation": platform.python_implementation()}


def read_materialization(repository: Path, identity: str) -> dict:
    require(digest(identity), "Expected a materialization digest")
    root = repository / "materializations" / identity
    for part in (root, *root.parents):
        require(not part.is_symlink() and not getattr(part, "is_junction", lambda: False)(), "Linked materialization")
    _regular(root / "receipt.json")
    receipt = read_json(root / "receipt.json")
    require(isinstance(receipt, dict) and (root / "receipt.json").read_bytes() == canonical(receipt, newline=True),
            "Noncanonical materialization receipt bytes")
    core = {k: v for k, v in receipt.items() if k != "materialization_id"}
    require(receipt.get("contract") == CONTRACT and receipt.get("materialization_id") == identity
            and _hash(canonical(core, newline=True)) == identity, "Materialization receipt identity changed")
    require(receipt.get("kind") == "observed_document_body_projection" and digest(receipt.get("observation_id"))
            and (receipt.get("parent_materialization_id") is None
                 or digest(receipt.get("parent_materialization_id")))
            and receipt.get("parent_materialization_id") != identity, "Invalid materialization lineage")
    refids, documents = receipt.get("refids"), receipt.get("documents")
    require(isinstance(refids, list) and all(isinstance(r, str) for r in refids)
            and refids == sorted(set(refids)) and 0 < len(refids) <= 20
            and isinstance(documents, list) and len(documents) == len(refids)
            and [d.get("refid") for d in documents] == refids, "Invalid materialization document scope")
    hashes = receipt.get("artifact_hashes")
    require(isinstance(hashes, dict) and hashes, "Missing materialization artifacts")
    actual = set()
    for path in root.rglob("*"):
        require(not path.is_symlink() and not getattr(path, "is_junction", lambda: False)(), "Linked product artifact")
        if path.is_file(): actual.add(path.relative_to(root).as_posix())
    require(actual == set(hashes) | {"receipt.json"}, "Materialization artifact membership changed")
    for name, checksum in hashes.items():
        require(safe_name(name) == name and digest(checksum), "Invalid product identity")
        _regular(root / name)
        require(file_hash(root / name) == checksum, "Materialized product bytes changed")
    require(receipt.get("legal_valid_time") == {"status": "unresolved", "from": None, "until": None}
            and receipt.get("observation_canonical_status") == "not_verified", "Unsupported materialization claim")
    for document in documents:
        require(document.get("status") in {"passed", "failed", "not_verified"}, "Invalid qualification status")
        if "qualification_path" in document:
            name = safe_name(document["qualification_path"])
            require(name in hashes, "Qualification is outside artifact inventory")
            report = read_json(root / name)
            require(report.get("status") == document["status"] and report.get("refid") == document["refid"]
                    and report.get("observation_id") == receipt["observation_id"], "Qualification binding changed")
        if document["status"] == "passed":
            require("qualification_path" in document and report.get("unclassified_source_remainder") == 0
                    and not report.get("reasons"), "Passed product lacks complete qualification")
            require(document.get("body_path") in hashes and document.get("html_path") in hashes
                    and hashes[document["body_path"]] == document.get("body_sha256")
                    and hashes[document["html_path"]] == report.get("canonical_html_sha256"),
                    "Qualified product identity changed")
        else:
            require(not any(k in document for k in ("body_path", "html_path", "body_sha256")),
                    "Unqualified document has promoted content")
    return receipt


def materializations(repository: Path) -> list[dict]:
    directory = repository / "materializations"
    if not directory.exists(): return []
    require(not directory.is_symlink() and not getattr(directory, "is_junction", lambda: False)(),
            "Linked materialization directory")
    entries = {}
    for path in directory.iterdir():
        require(path.is_dir() and digest(path.name), "Unexpected materialization entry")
        entries[path.name] = read_materialization(repository, path.name)
    ordered, parent = [], None
    while len(ordered) < len(entries):
        children = [r for r in entries.values() if r["parent_materialization_id"] == parent]
        require(len(children) == 1, "Materialization chain is disconnected or forked")
        item = children[0]
        require(item not in ordered, "Cyclic materialization chain")
        ordered.append(item); parent = item["materialization_id"]
    return ordered


def _source_bytes(root: Path, selected: list[dict]) -> dict[str, bytes]:
    result = {}
    for archive_sha in sorted({r["archive_sha256"] for r in selected}):
        wanted = {r["member_ordinal"]: r for r in selected if r["archive_sha256"] == archive_sha}
        archive = root / "raw" / (archive_sha + ".tar.bz2")
        require(file_hash(archive) == archive_sha, "Raw archive changed before projection")
        with tarfile.open(archive, "r:bz2") as stream:
            for ordinal, member in enumerate(stream):
                if ordinal not in wanted: continue
                row = wanted.pop(ordinal)
                require(member.isfile() and member.name == row["member_path"]
                        and member.size == row["member_size_bytes"], "Projection source member changed")
                with stream.extractfile(member) as source: data = source.read()
                require(_hash(data) == row["member_sha256"], "Projection XML digest mismatch")
                result[row["source_occurrence_id"]] = data
        require(not wanted, "Projection source member absent")
    return result


def _materialize(repository: Path, observation_id: str, refids=None, expected_parent="auto") -> dict:
    scope = sorted(set(refids or PILOT_REFIDS))
    require(0 < len(scope) <= 20 and all(isinstance(r, str) and r.startswith(("lov/", "forskrift/"))
            and safe_name(r.replace("/", "-")) == r.replace("/", "-") for r in scope), "Invalid bounded projection scope")
    release, summary, _ = read_observation(repository, observation_id)
    chain = materializations(repository)
    parent = chain[-1]["materialization_id"] if chain else None
    require(expected_parent == "auto" or expected_parent == parent
            or expected_parent == "none" and parent is None, "Materialization parent changed")
    generator = generator_identity()
    for previous in chain:
        if (previous["observation_id"] == observation_id and previous["refids"] == scope
                and previous["generator"] == generator):
            return {"status": "already_present", **previous}
    bundle = ensure_bundle(repository, release)
    _directory(repository / "materializations")
    with tempfile.TemporaryDirectory(prefix="project-", dir=repository / ".cache") as temporary:
        work = Path(temporary)
        snapshot = work / "snapshot"; snapshot.mkdir()
        names = unpack_bundle(bundle, snapshot, release)
        manifest, observation, members = validate_snapshot(snapshot, names)
        require(manifest["artifact_hashes"]["source-observations.json"] == summary["source_observation_sha256"],
                "Accepted observation differs from bundle")
        chosen = [m for m in members if m["refid"] in scope and m["selected"]
                  and m["role"] in ("laws", "forskrifter") and m["member_type"] == "file"]
        raw = _source_bytes(snapshot, chosen)
        output = work / "product"; output.mkdir()
        records = []

        def write(name, data):
            target = output / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        prior_documents = {d["refid"]: d for d in chain[-1]["documents"]} if chain else {}
        for refid in scope:
            candidates = [m for m in chosen if m["refid"] == refid]
            if len(candidates) != 1:
                records.append({"refid": refid, "status": "not_verified", "reason": "selected_source_missing_or_ambiguous"})
                continue
            member = candidates[0]
            raw_bytes = raw[member["source_occurrence_id"]]
            model_path = member["selected_output_path"]
            model_bytes = (snapshot / model_path).read_bytes()
            require(_hash(model_bytes) == member["selected_output_sha256"], "Projection model bytes changed")
            model = read_json(snapshot / model_path)
            report, accounting, source_events, paths, model_events, rendered = qualify(raw_bytes, model, refid)
            stem = refid.replace("/", "-"); directory = "documents/" + stem
            report.update(observation_id=observation_id, source_occurrence_id=member["source_occurrence_id"],
                          archive_sha256=member["archive_sha256"], member_ordinal=member["member_ordinal"],
                          member_path=member["member_path"], raw_member_sha256=member["member_sha256"],
                          model_sha256=member["selected_output_sha256"], receipt_url=release["receipt_url"])
            record = {"refid": refid, "status": report["status"], "qualification_path": directory + "/qualification.json",
                      "source_occurrence_id": member["source_occurrence_id"], "raw_member_sha256": member["member_sha256"]}
            if report["status"] == "passed":
                require(rendered is not None and source_events == model_events, "Incomplete qualified projection")
                payload = canonical({"contract": VERSION, "refid": refid, "events": model_events}, newline=True)
                write(directory + "/body.json", payload)
                write(directory + "/body.html", rendered.encode("utf-8"))
                record.update(body_path=directory + "/body.json", html_path=directory + "/body.html",
                              body_sha256=_hash(payload))
                old = prior_documents.get(refid)
                if not old or not old.get("body_sha256"):
                    record["projection_change"] = "first_qualified_projection"
                elif old["body_sha256"] == record["body_sha256"]:
                    record["projection_change"] = "unchanged"
                elif old.get("raw_member_sha256") == record["raw_member_sha256"]:
                    record["projection_change"] = "representation_change"
                else:
                    record["projection_change"] = "observed_text_change"
            write(directory + "/qualification.json", canonical(report, newline=True))
            write(directory + "/source-accounting.json", canonical({"nodes": accounting, "event_source_paths": paths}, newline=True))
            records.append(record)
        write("inventory.json", canonical({"scope": "explicit selected pilot; all other source members remain raw observations",
              "requested": len(scope), "qualified": sum(r["status"] == "passed" for r in records),
              "unqualified": sum(r["status"] != "passed" for r in records), "documents": records}, newline=True))
        index = ["# Observed document bodies", "", "These products describe source bytes observed by the collector. "
                 "They do not establish when the text legally applied. Unsupported documents remain available as raw evidence.",
                 "", "Observation: `" + observation_id + "`", "", "Knowledge cutoff: " + observation["knowledge_cutoff"],
                 "", "[Source receipt](" + release["receipt_url"] + ") · [Product inventory](inventory.json)", "",
                 "| Document | Qualification | Readback |", "|---|---|---|"]
        for record in records:
            links = []
            if record["status"] == "passed":
                links += ["[Download readable HTML](" + record["html_path"] + "?raw=1)",
                          "[Ordered body](" + record["body_path"] + ")"]
            if record.get("qualification_path"):
                links += ["[Qualification and source identity](" + record["qualification_path"] + ")"]
            index.append("| " + record["refid"] + " | " + record["status"] + " | " + " · ".join(links) + " |")
        index += ["", "Open downloaded HTML in a browser. Qualification applies to the declared document-body grammar; "
                  "the whole observation remains unverified for canonical legal text. Legal dates remain unresolved.", "",
                  "Exact XML remains retrievable with `law-history raw REFID --observation " + observation_id + "`. "
                  "Use `show REFID` to find the source occurrence if more than one is available.", ""]
        write("README.md", "\n".join(index).encode("utf-8"))
        hashes = {p.relative_to(output).as_posix(): file_hash(p) for p in sorted(output.rglob("*")) if p.is_file()}
        receipt = {"contract": CONTRACT, "kind": "observed_document_body_projection",
                   "observation_id": observation_id, "parent_materialization_id": parent,
                   "knowledge_cutoff": observation["knowledge_cutoff"], "knowledge_cutoff_basis": "local_archive_observation",
                   "refids": scope, "generator": generator, "artifact_hashes": hashes, "documents": records,
                   "producer_source_sha": release["source_sha"],
                   "producer_content_contract": manifest["content_version"],
                   "producer_formatter_contract": manifest["formatter_version"],
                   "parser_identity": observation["parser_identity"], "parser_runtime": observation["parser_runtime"],
                   "source_receipt_url": release["receipt_url"], "source_bundle_sha256": release["bundle"]["sha256"],
                   "observation_canonical_status": "not_verified",
                   "legal_valid_time": {"status": "unresolved", "from": None, "until": None},
                   "change_kind": "representation_change" if any(r["observation_id"] == observation_id for r in chain) else "new_observation",
                   "data_attribution": release["data_attribution"]}
        identity = _hash(canonical(receipt, newline=True)); receipt["materialization_id"] = identity
        write("receipt.json", canonical(receipt, newline=True))
        current = materializations(repository)
        require((current[-1]["materialization_id"] if current else None) == parent, "Materialization parent advanced")
        destination = repository / "materializations" / identity
        require(not destination.exists(), "Materialization already exists with unexpected processing state")
        output.rename(destination)
    return {"status": "accepted", **read_materialization(repository, identity)}


def materialize(repository: Path, observation_id: str, refids=None, expected_parent="auto") -> dict:
    """Hold one exclusive writer lock across parent inspection and atomic publication."""
    _directory(repository / ".cache")
    lock = repository / ".cache" / "materialization-writer.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError("Materialization writer lock exists. If an earlier run was interrupted, "
                         "confirm its recorded process is no longer running before removing the lock.") from None
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write(str(os.getpid()) + "\n")
        return _materialize(repository, observation_id, refids, expected_parent)
    finally:
        lock.unlink()


def materialize_all(repository: Path) -> list[dict]:
    return [materialize(repository, item["observation_id"]) for item in list_observations(repository)]
