"""Append proposed interpretations without changing exported evidence or legal state.

No evidence method is registered here. Dates and scope submitted to this store
are assertions, never eligible reconstruction inputs, even when their cited
evidence locations are verified. Publication separately binds exact proposal
bytes to checked Git creation receipts.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import os
from pathlib import Path
import sys
import tempfile

from .ledger import _directory, _regular
from .operation_products import _gzip_rows, artifact_tree, read_operation_product
from .validation import canonical, digest, file_hash, read_json, require, timestamp, value_hash

CONTRACT = "history-later-claim-v1"
REQUEST = "history-later-claim-request-v1"
METHOD = "manual-proposal-v1"
ELIGIBILITY = {"eligible": False, "reason": "no_registered_evidence_method"}
CUTOFF_BASIS = "submitted_assertion_bounded_by_retained_evidence_not_historical_knowledge_proof"


def _identity(domain, value):
    return hashlib.sha256(domain.encode("ascii") + b"\0" + canonical(value)).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _keys(value, keys, label):
    require(isinstance(value, dict) and set(value) == set(keys), f"Unsupported {label} fields")


class _Evidence:
    """Fully verify each distinct cited product once per operation."""

    def __init__(self, repository):
        self.repository = repository
        self.products, self.acts = {}, {}

    def act(self, product_id, refid, occurrence):
        require(digest(product_id) and digest(occurrence) and isinstance(refid, str), "Invalid pinned act identity")
        key = product_id, occurrence
        if product_id not in self.products:
            receipt = read_operation_product(self.repository, product_id)
            root = artifact_tree(self.repository, receipt)
            index = {row["source_occurrence_id"]: row for row in _gzip_rows(root / "index.jsonl.gz")}
            self.products[product_id] = receipt, root, index
        receipt, root, index = self.products[product_id]
        require(occurrence in index and index[occurrence]["refid"] == refid, "Act/source occurrence is not in pinned product")
        if key not in self.acts:
            entry = index[occurrence]
            rows = [row for row in _gzip_rows(root / entry["shard"])
                    if row["act"]["source_occurrence_id"] == occurrence]
            require(len(rows) == 1 and hashlib.sha256(canonical(rows[0], newline=True)).hexdigest() == entry["record_sha256"],
                    "Pinned act record changed")
            self.acts[key] = rows[0]
        return receipt, index[occurrence], self.acts[key]

    def references(self, product_id, refid, occurrence):
        _, _, row = self.act(product_id, refid, occurrence)
        common = {"operation_product_id": product_id, "refid": refid, "source_occurrence_id": occurrence}
        found = [({**common, "kind": "parsed_act", "location": row["act"]["parsed_evidence"]},
                  row["act"]["producer_envelope"]["record"])]
        for operation in row["operations"]:
            found.append(({**common, "kind": "parsed_operation", "operation_id": operation["operation_id"],
                           "location": operation["parsed_evidence"]}, operation["producer_record"]))
            for pointer in operation["source_alignment"]["candidates"]:
                found.append(({**common, "kind": "instruction_candidate", "operation_id": operation["operation_id"],
                               "location": pointer}, {"pointer": pointer, "instruction": operation["producer_record"]["instruction"]}))
        for expression in row["act"]["commencement_expressions"]:
            found.append(({**common, "kind": "commencement_candidate", "expression_id": expression["expression_id"],
                           "location": expression["source"]}, expression))
        return found

    def reference(self, reference):
        require(isinstance(reference, dict), "Expected typed evidence reference")
        product_id, refid, occurrence = (reference[key] for key in
            ("operation_product_id", "refid", "source_occurrence_id"))
        matches = [value for candidate, value in self.references(product_id, refid, occurrence) if reference == candidate]
        require(len(matches) == 1, "Evidence location does not resolve exactly in pinned act")
        receipt, entry, _ = self.act(product_id, refid, occurrence)
        return {"reference": reference, "operation_receipt_sha256": file_hash(
                    self.repository / "operation-products" / product_id / "receipt.json"),
                "bundle_sha256": receipt["bundle"]["sha256"], "act_record_sha256": entry["record_sha256"],
                "value_sha256": value_hash(matches[0]), "knowledge_cutoff": receipt["knowledge_cutoff"]}


def _target(evidence, target):
    _keys(target, ("operation_product_id", "refid", "source_occurrence_id", "subject"), "target")
    subject = target["subject"]
    require(isinstance(subject, dict) and subject.get("kind") in ("act", "operation") and digest(subject.get("id")),
            "Invalid claim subject")
    receipt, entry, row = evidence.act(target["operation_product_id"], target["refid"], target["source_occurrence_id"])
    act = row["act"]
    candidates = [act] if subject["kind"] == "act" else row["operations"]
    identity_key = "act_id" if subject["kind"] == "act" else "operation_id"
    matched = [item for item in candidates if item[identity_key] == subject["id"]]
    require(len(matched) == 1, "Subject does not belong to pinned source act")
    exact_subject = {"kind": subject["kind"], "id": subject["id"],
                     "parsed_revision_id": act["parsed_revision_id"], "parsed_model_sha256": act["parsed_model_sha256"]}
    require(subject == exact_subject, "Subject parsed revision/model binding differs")
    initial = [claim for claim in row["claims"] if claim["subject"]["kind"] == subject["kind"]
               and claim["subject"]["id"] == subject["id"]]
    require(len(initial) == 1, "Initial unresolved claim is missing or ambiguous")
    binding = {**target, "observation_id": receipt["observation_id"], "knowledge_cutoff": receipt["knowledge_cutoff"],
               "operation_receipt_sha256": file_hash(evidence.repository / "operation-products" /
                                                     target["operation_product_id"] / "receipt.json"),
               "act_record_sha256": entry["record_sha256"], "source_member": act["source_member"],
               "parsed_evidence": matched[0]["parsed_evidence"]}
    return binding, initial[0]


def _request(evidence, request):
    _keys(request, ("contract", "target", "knowledge_cutoff", "supersedes", "method", "assertion", "evidence"), "claim request")
    require(request["contract"] == REQUEST and request["method"] == METHOD, "No registered interpretation/evidence method exists")
    binding, initial = _target(evidence, request["target"])
    cutoff = timestamp(request["knowledge_cutoff"])
    require(cutoff >= timestamp(binding["knowledge_cutoff"]), "Claim cutoff precedes target product knowledge")
    require(isinstance(request["supersedes"], list) and len(request["supersedes"]) == 1
            and digest(request["supersedes"][0]), "A proposal must supersede one exact current claim")
    assertion = request["assertion"]
    _keys(assertion, ("text", "proposed_scope", "proposed_legal_valid_time"), "proposed assertion")
    require(all(isinstance(assertion[key], str) and 0 < len(assertion[key].strip()) <= 20000
                for key in ("text", "proposed_scope")), "Proposal text/scope is missing or too large")
    interval = assertion["proposed_legal_valid_time"]
    _keys(interval, ("from", "until"), "proposed date assertion")
    for value in interval.values():
        require(value is None or isinstance(value, str) and date.fromisoformat(value).isoformat() == value,
                "Proposed date must be null or an exact ISO calendar date")
    references = request["evidence"]
    require(isinstance(references, list) and 1 <= len(references) <= 20, "Expected 1 to 20 pinned evidence references")
    require(len({value_hash(reference) for reference in references}) == len(references), "Duplicate evidence reference")
    resolved = [evidence.reference(reference) for reference in references]
    require(all(timestamp(reference["knowledge_cutoff"]) <= cutoff for reference in resolved),
            "Claim cutoff precedes cited evidence knowledge")
    return binding, initial, resolved


def _path(repository, target):
    key = _identity("history-later-claim-subject-v1", {
        "operation_product_id": target["operation_product_id"],
        "source_occurrence_id": target["source_occurrence_id"], "subject": target["subject"]})
    # The complete identities remain in every hashed record. A short bucket
    # avoids three nested 64-character components that break ordinary Windows
    # Git checkouts. Colliding bucket prefixes share the same writer lock.
    return repository / "later-claims" / key[:2]


def _history(evidence, target):
    binding, initial = _target(evidence, target)
    directory = _path(evidence.repository, target)
    entries, requests = {}, set()
    if directory.exists():
        for path in (directory, *directory.parents):
            require(not path.is_symlink() and not getattr(path, "is_junction", lambda: False)(), "Linked claim storage")
        require(directory.is_dir(), "Claim storage is not a directory")
        for path in directory.iterdir():
            _regular(path)
            require(path.suffix == ".json" and digest(path.stem), "Unexpected claim artifact")
            record = read_json(path)
            _keys(record, ("contract", "claim_id", "request_id", "request", "target_binding", "evidence_bindings",
                           "recorded_at", "status", "reconstruction_eligibility", "knowledge_cutoff_basis"), "stored claim")
            core = {key: value for key, value in record.items() if key != "claim_id"}
            require(record["contract"] == CONTRACT and record["claim_id"] == path.stem == _identity(CONTRACT, core)
                    and path.read_bytes() == canonical(record, newline=True), "Claim identity or canonical bytes changed")
            require(record["request_id"] == _identity(REQUEST, record["request"])
                    and record["request_id"] not in requests, "Repeated or changed proposal request identity")
            require(_path(evidence.repository, record["request"]["target"]) == directory,
                    "Claim is stored in the wrong subject bucket")
            if record["request"]["target"] != target:
                continue
            verified, _, references = _request(evidence, record["request"])
            require(verified == binding == record["target_binding"] and references == record["evidence_bindings"],
                    "Stored claim subject/source/evidence binding changed")
            require(record["status"] == "proposed" and record["reconstruction_eligibility"] == ELIGIBILITY
                    and record["knowledge_cutoff_basis"] == CUTOFF_BASIS, "Proposed claim cannot become eligible")
            require(timestamp(record["recorded_at"]) >= timestamp(record["request"]["knowledge_cutoff"]),
                    "Claim cutoff is after actual recorded time")
            entries[path.stem] = record; requests.add(record["request_id"])
    ordered, parent = [], initial["claim_id"]
    cutoff = timestamp(binding["knowledge_cutoff"])
    recorded = None
    while len(ordered) < len(entries):
        children = [record for record in entries.values() if record["request"]["supersedes"] == [parent]]
        require(len(children) == 1, "Claim supersedes chain is disconnected, forked, or belongs to another subject")
        record = children[0]
        require(record not in ordered and timestamp(record["request"]["knowledge_cutoff"]) >= cutoff,
                "Claim cutoff regresses or chain is cyclic")
        require(recorded is None or timestamp(record["recorded_at"]) >= recorded, "Actual claim recording time regresses")
        ordered.append(record); parent = record["claim_id"]
        cutoff, recorded = timestamp(record["request"]["knowledge_cutoff"]), timestamp(record["recorded_at"])
    return binding, initial, ordered


def propose_claim(repository: Path, request: dict) -> dict:
    """Accept a fully bound proposal locally; never assign legal eligibility."""
    repository = Path(repository).absolute()
    request = deepcopy(request)
    evidence = _Evidence(repository)
    binding, initial, references = _request(evidence, request)
    directory = _path(repository, request["target"])
    cache = repository / ".cache"; _directory(cache)
    lock = cache / ("later-claim-" + directory.parent.name + "-" + directory.name + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError("Claim writer lock exists; inspect the previous writer before retrying") from exc
    try:
        os.close(descriptor)
        _, _, prior = _history(evidence, request["target"])
        request_id = _identity(REQUEST, request)
        replay = next((record for record in prior if record["request_id"] == request_id), None)
        if replay is not None:
            require(replay["request"] == request, "Proposal request identity conflict")
            return {"status": "already_present", "claim": replay}
        parent = prior[-1]["claim_id"] if prior else initial["claim_id"]
        require(request["supersedes"] == [parent], "Proposal must supersede the current claim of this exact subject")
        cutoff = timestamp(request["knowledge_cutoff"])
        require(not prior or cutoff >= timestamp(prior[-1]["request"]["knowledge_cutoff"]), "Claim cutoff regresses")
        recorded_at = _now()
        require(cutoff <= timestamp(recorded_at), "Claim cutoff is after actual recorded time")
        require(not prior or timestamp(recorded_at) >= timestamp(prior[-1]["recorded_at"]), "Actual claim recording time regresses")
        core = {"contract": CONTRACT, "request_id": request_id, "request": request,
                "target_binding": binding, "evidence_bindings": references, "recorded_at": recorded_at,
                "status": "proposed", "reconstruction_eligibility": deepcopy(ELIGIBILITY), "knowledge_cutoff_basis": CUTOFF_BASIS}
        record = {**core, "claim_id": _identity(CONTRACT, core)}
        _directory(directory)
        with tempfile.TemporaryDirectory(prefix="later-claim-", dir=cache) as temporary:
            staged = Path(temporary) / "claim.json"; staged.write_bytes(canonical(record, newline=True))
            os.link(staged, directory / (record["claim_id"] + ".json"))
        return {"status": "accepted_proposal", "claim": record}
    finally:
        lock.unlink()


def claim_history(repository: Path, target: dict) -> dict:
    """Return all versions; 'current' means current proposal, never legal state."""
    evidence = _Evidence(Path(repository).absolute())
    binding, initial, history = _history(evidence, target)
    return {"contract": CONTRACT, "target_binding": binding, "initial_unresolved_claim": initial,
            "current_proposal": history[-1] if history else None, "proposed_claim_history": history,
            "current_claim_id": history[-1]["claim_id"] if history else initial["claim_id"],
            "eligible_reconstruction_inputs": [], "registered_evidence_methods": [],
            "available_evidence_references": [reference for reference, _ in evidence.references(
                target["operation_product_id"], target["refid"], target["source_occurrence_id"])]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path("."))
    commands = parser.add_subparsers(dest="command", required=True)
    propose = commands.add_parser("propose", help="Append an explicitly non-materializable assertion")
    propose.add_argument("request", type=Path)
    history = commands.add_parser("history", help="Read initial, current proposed, and prior claims")
    history.add_argument("target", type=Path, help="JSON target with pinned product, occurrence and exact subject revision")
    args = parser.parse_args(argv)
    try:
        result = propose_claim(args.repository, read_json(args.request)) if args.command == "propose" else \
                 claim_history(args.repository, read_json(args.target))
        sys.stdout.write(canonical(result, newline=True).decode("utf-8"))
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        print(f"Claim rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
