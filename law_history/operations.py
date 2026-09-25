"""Preserve selected parsed acts and unresolved claims independently of the producer.

The caller must first validate the entire evidence bundle/catalog. This pure
interface rechecks the selected binding; it does not establish catalog membership
from a caller-supplied row or certify that the producer found every operation.
XML phrases are evidence candidates, never resolved commencement or target scope.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
from pathlib import PurePosixPath
import re
import xml.etree.ElementTree as ET

from .validation import (ACT_FIELDS, AMENDMENT_FIELDS, canonical, count, digest,
                         loads, require, timestamp, validate_receipt, value_hash)

VERSION = "history-operation-evidence-v1"
CLAIM_VERSION = "history-unresolved-legal-time-v1"
XML_PATH_VERSION = "xml-element-sibling-path-v1"
EXPRESSION_VERSION = "commencement-candidates-v1"
PARSED_PATH = "parsed-amendment-acts.v1.jsonl"
SOURCE_PATH = "source-observations.json"
_COMMENCEMENT = re.compile(
    r"\bi\s+kraft\b|\b(?:gjelder|gjeld)\s+(?:fra|frå)\b|"
    r"\b(?:Kongen|departementet)\s+(?:bestemmer|fastset)\b|\bikrafttred\w*", re.I)
_REPLACEMENT = re.compile(r"\bskal\s+(?:lyde|lyda)\b", re.I)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _identity(domain: str, value) -> str:
    return _sha(domain.encode("ascii") + b"\0" + canonical(value))


def _normalized(text: str) -> str:
    return re.sub(r"[ \t\r\n\f]+", " ", text).strip(" \t\r\n\f")


def _classes(node) -> set[str]:
    return set(node.get("class", "").split())


def _text(node) -> str:
    return "".join(node.itertext())


def _is_block(node) -> bool:
    return node.tag in {"p", "dd", "li"} or (
        node.tag == "article" and bool(_classes(node) & {"legalP", "defaultP"}))


def _text_runs(node) -> list[str]:
    """Keep separate runs around nested blocks, avoiding invented joined phrases."""
    runs = [node.text or ""]
    for child in node:
        if _is_block(child):
            runs.append("")
        else:
            child_runs = _text_runs(child)
            runs[-1] += child_runs[0]
            runs.extend(child_runs[1:])
        runs[-1] += child.tail or ""
    return runs


def _xml_index(raw: bytes):
    content = raw.decode("utf-8")
    # ElementTree does not fetch external resources; also reject entity/DTD
    # declarations rather than accepting expanded text with hidden provenance.
    require("<!ENTITY" not in content.upper(), "XML entity declarations are unsupported")
    doctypes = re.findall(r"<!DOCTYPE[^>]*>", content, re.I)
    require(all(re.fullmatch(r"<!DOCTYPE\s+html\s*>", d, re.I) for d in doctypes),
            "Unsupported XML document type")
    root = ET.fromstring(content)
    require(all(isinstance(n.tag, str) and not n.tag.startswith("{") for n in root.iter()),
            "Namespaced source XML is unsupported by this candidate extractor")
    nodes, paths, parents = [], {}, {}

    def visit(node, path):
        nodes.append(node); paths[node] = path
        seen = {}
        for child in node:
            seen[child.tag] = seen.get(child.tag, 0) + 1
            parents[child] = node
            visit(child, f"{path}/{child.tag}[{seen[child.tag]}]")

    visit(root, f"/{root.tag}[1]")
    return nodes, paths, parents


@lru_cache(maxsize=2)
def _artifact_context(manifest_bytes, source_bytes):
    # Exact immutable bytes are the cache keys. This avoids reparsing the same
    # large manifest for every act without trusting mutable caller dictionaries.
    return loads(manifest_bytes), loads(source_bytes), _sha(manifest_bytes), _sha(source_bytes)


def _validate(envelope, raw, member, receipt, manifest_bytes, source_bytes):
    require(isinstance(raw, bytes) and isinstance(manifest_bytes, bytes)
            and isinstance(source_bytes, bytes), "Exact source/manifest bytes are required")
    validate_receipt(receipt)
    manifest, observation, manifest_sha, source_sha = _artifact_context(manifest_bytes, source_bytes)
    require(manifest_sha == receipt["snapshot_manifest_sha256"],
            "Snapshot manifest digest mismatch")
    require(manifest.get("version") == 4 and manifest.get("evidence", {}).get("parsed_amendments") == PARSED_PATH
            and manifest.get("evidence", {}).get("observations") == SOURCE_PATH,
            "Unsupported parsed/source artifact contract")
    hashes = manifest["artifact_hashes"]
    require(digest(hashes.get(PARSED_PATH)) and source_sha == hashes.get(SOURCE_PATH),
            "Source observation/artifact digest mismatch")
    require(observation.get("schema_version") == "lovdata-source-evidence-v1"
            and observation.get("historical_knowledge_time_status") == "unknown"
            and observation.get("knowledge_cutoff_basis") == "local_archive_observation",
            "Unsupported observation clock semantics")
    cutoff = timestamp(observation["knowledge_cutoff"])
    require(isinstance(member, dict) and member.get("role") == "amendment_acts"
            and member.get("parse_status") == "parsed" and member.get("member_type") == "file",
            "Expected a parsed amendment-act member")
    for field in ("archive_ordinal", "member_ordinal", "member_size_bytes", "parsed_occurrence_ordinal"):
        require(count(member.get(field)), f"Invalid member {field}")
    require(isinstance(member.get("member_path"), str) and member["member_path"].endswith(".xml"),
            "Invalid XML member path")
    for field in ("archive_sha256", "member_sha256", "parsed_model_sha256", "source_occurrence_id"):
        require(digest(member.get(field)), f"Invalid member {field}")
    archives = observation["archives"]
    require(isinstance(archives, list) and member["archive_ordinal"] < len(archives),
            "Archive ordinal is outside observation")
    archive = archives[member["archive_ordinal"]]
    require(archive["archive_ordinal"] == member["archive_ordinal"]
            and archive["archive_sha256"] == member["archive_sha256"]
            and archive["role"] == member["role"]
            and archive["raw_path"] == f'raw/{member["archive_sha256"]}.tar.bz2'
            and hashes.get(archive["raw_path"]) == member["archive_sha256"],
            "Source archive binding mismatch")
    require(timestamp(archive["observed_at"]) <= cutoff, "Knowledge cutoff precedes observation")
    require(archive.get("historical_knowledge_time_status") == "unknown", "Invented historical knowledge time")
    if archive.get("retrieved_at") is None:
        require(archive.get("retrieval_time_status") == "unknown", "Invented retrieval time")
    else:
        timestamp(archive["retrieved_at"])
        require(archive.get("retrieval_time_status") == "recorded", "Retrieval-time status mismatch")
    require(len(raw) == member["member_size_bytes"] and _sha(raw) == member["member_sha256"],
            "Raw XML member size/digest mismatch")
    require(value_hash([member[k] for k in ("archive_ordinal", "archive_sha256", "member_ordinal",
            "member_path", "member_sha256", "role")]) == member["source_occurrence_id"],
            "Source occurrence identity mismatch")
    require(isinstance(envelope, dict) and envelope.get("schema_version") == "parsed-amendment-acts-v1"
            and envelope.get("source_occurrence_id") == member["source_occurrence_id"]
            and count(envelope.get("parsed_occurrence_ordinal"))
            and envelope["parsed_occurrence_ordinal"] == member["parsed_occurrence_ordinal"],
            "Parsed act occurrence mismatch")
    record = envelope["record"]
    require(isinstance(record, dict) and set(record) == ACT_FIELDS
            and record.get("refid") == member["refid"]
            and record.get("filename") == PurePosixPath(member["member_path"]).name
            and value_hash(record) == member["parsed_model_sha256"], "Parsed act/model binding mismatch")
    require(all(isinstance(record[k], str) for k in ACT_FIELDS - {"changes_to", "amendments"})
            and isinstance(record["changes_to"], list) and all(isinstance(v, str) for v in record["changes_to"])
            and isinstance(record["amendments"], list), "Malformed original act fields")
    expected = []
    for ordinal, amendment in enumerate(record["amendments"]):
        require(isinstance(amendment, dict) and set(amendment) == AMENDMENT_FIELDS
                and all(isinstance(v, str) for v in amendment.values()), "Malformed original operation")
        expected.append({"ordinal": ordinal, "target_status": "identified" if amendment["target_law"] else "unresolved",
                         "operation_status": "unresolved" if amendment["change_type"] == "unknown" else "identified"})
    occurrences = envelope.get("amendment_occurrences")
    require(isinstance(occurrences, list) and all(isinstance(v, dict) and count(v.get("ordinal")) for v in occurrences)
            and occurrences == expected and envelope.get("legal_valid_time") == {"status": "unresolved", "date": None}
            and envelope.get("fidelity") == "lossless_relative_to_parsed_model"
            and envelope.get("source_structure_status") == "not_verified", "Parsed operation/status mismatch")
    return manifest, observation, archive


def extract_act(envelope: dict, raw_xml: bytes, *, member: dict, receipt: dict,
                manifest_bytes: bytes, source_observation_bytes: bytes,
                publication: dict | None = None) -> dict:
    """Return an act, all producer operations and initial unresolved claims.

    All input rows must come from the caller's independently validated bundle.
    ``publication`` optionally records a caller-provided release-publication
    assertion as {published_at, evidence}; it is not an observed or legal date.
    No clock is read, file written, amendment applied or prior claim overwritten.
    """
    try:
        return _extract(envelope, raw_xml, member, receipt, manifest_bytes, source_observation_bytes, publication)
    except (KeyError, TypeError, AttributeError, IndexError, UnicodeError, ET.ParseError) as exc:
        raise ValueError(f"Malformed operation evidence: {exc}") from exc


def _extract(envelope, raw, member, receipt, manifest_bytes, source_bytes, publication):
    manifest, observation, archive = _validate(envelope, raw, member, receipt, manifest_bytes, source_bytes)
    nodes, paths, parents = _xml_index(raw)
    refids = [_normalized(_text(n)) for n in nodes if n.tag == "dd" and "refid" in _classes(n)]
    require(refids == [member["refid"]], "Source XML refid mismatch or ambiguity")
    if publication is not None:
        require(isinstance(publication, dict) and set(publication) == {"published_at", "evidence"}
                and isinstance(publication["evidence"], str) and bool(publication["evidence"].strip()),
                "Publication assertion requires its own evidence")
        timestamp(publication["published_at"])
    record = envelope["record"]
    occurrence = member["source_occurrence_id"]
    act_id = _identity("history-act-occurrence-v1", occurrence)
    model_sha = member["parsed_model_sha256"]
    parsed_revision_id = _identity("history-parsed-act-revision-v1", [occurrence, model_sha])
    context = {
        "observation_id": receipt["observation_id"], "release_tag": receipt["release_tag"] ,
        "receipt_url": receipt["receipt_url"], "producer_source_sha": receipt["source_sha"],
        "snapshot_manifest_sha256": receipt["snapshot_manifest_sha256"],
        "bundle_sha256": receipt["bundle"]["sha256"],
        "source_observation_sha256": _sha(source_bytes),
        "parser_identity": observation["parser_identity"], "parser_runtime": observation["parser_runtime"],
        "data_attribution": receipt["data_attribution"],
    }
    clocks = {
        "knowledge_cutoff": observation["knowledge_cutoff"],
        "knowledge_cutoff_basis": observation["knowledge_cutoff_basis"],
        "observed_at": archive["observed_at"], "retrieved_at": archive["retrieved_at"],
        "retrieval_time_status": archive["retrieval_time_status"],
        "historical_knowledge_time": {"status": "unknown", "at": None},
        "source_last_modified": archive["source_last_modified"],
        "source_date_published": record["date_published"],
        "source_date_in_force": record["date_in_force"],
        "release_publication": {"status": "caller_recorded" if publication else "unknown",
                                "assertion": publication},
    }
    parsed_pointer = {"artifact_path": PARSED_PATH, "artifact_sha256": manifest["artifact_hashes"][PARSED_PATH],
                      "parsed_occurrence_ordinal": envelope["parsed_occurrence_ordinal"], "json_pointer": "/record"}

    def source_pointer(node):
        return {"source_occurrence_id": occurrence, "member_sha256": member["member_sha256"],
                "path_version": XML_PATH_VERSION, "path": paths[node], "element_id": node.get("id")}

    def source_context(node):
        ancestors, cursor = [], node
        while cursor in parents:
            cursor = parents[cursor]
            if cursor.tag == "section":
                headings = [{"text": _text(c), "source": source_pointer(c)} for c in cursor if c.tag in {"h1", "h2", "h3", "h4"}]
                ancestors.append({"source": source_pointer(cursor), "headings": headings})
        parent = parents.get(node)
        siblings = list(parent) if parent is not None else []
        index = siblings.index(node) if siblings else 0
        previous = siblings[index - 1] if index else None
        return {"ancestor_sections": list(reversed(ancestors)), "preceding_sibling": None if previous is None else
                {"source": source_pointer(previous), "text": _text(previous)}}, previous

    expressions = []
    blocks = [n for n in nodes if _is_block(n)]
    for node in blocks:
        metadata = node.tag == "dd" and "dateInForce" in _classes(node)
        for run_ordinal, text in enumerate(_text_runs(node)):
            if not text.strip() or not (metadata or _COMMENCEMENT.search(text)):
                continue
            context_evidence, previous = source_context(node)
            replacement_ordinals = [i for i, op in enumerate(record["amendments"])
                                    if _normalized(text) and _normalized(op["new_text"])
                                    and _normalized(text) in _normalized(op["new_text"])]
            replacement_instruction = previous is not None and _REPLACEMENT.search(_text(previous)) is not None
            source = source_pointer(node)
            expression = {"method": EXPRESSION_VERSION, "text": text, "text_run_ordinal": run_ordinal,
                          "text_representation": "xml_character_data_without_whitespace_normalization",
                          "source": source, "context": context_evidence,
                          "role": "metadata_expression" if metadata else "replacement_text_candidate" if
                          (replacement_ordinals or replacement_instruction) else "commencement_candidate",
                          "producer_replacement_match_ordinals": replacement_ordinals,
                          "preceding_replacement_instruction": replacement_instruction,
                          "legal_scope_status": "unresolved"}
            expression["expression_id"] = _identity("history-commencement-expression-v1", expression)
            expressions.append(expression)
    act = {"contract": VERSION, "act_id": act_id, "parsed_revision_id": parsed_revision_id,
           "parsed_model_sha256": model_sha, "refid": record["refid"],
           "source_occurrence_id": occurrence, "source_member": member,
           "producer_envelope": envelope, "parsed_evidence": parsed_pointer,
           "context": context, "clocks": clocks, "source_url": archive["source_url"],
           "commencement_expressions": expressions,
           "expression_coverage": {"method": EXPRESSION_VERSION, "status": "candidates_only_not_complete",
                                   "scope_assignment": "not_performed"},
           "operation_coverage": "all_operations_in_producer_model_not_source_completeness"}
    operations = []
    for ordinal, original in enumerate(record["amendments"]):
        instruction = _normalized(original["instruction"])
        matches = [n for n in blocks if instruction and _normalized(_text(n)) == instruction]
        operations.append({"contract": VERSION,
            "operation_id": _identity("history-operation-revision-v1", [occurrence, model_sha, ordinal]),
            "act_id": act_id, "parsed_revision_id": parsed_revision_id, "parsed_model_sha256": model_sha,
            "source_occurrence_id": occurrence, "operation_ordinal": ordinal,
            "observation_id": receipt["observation_id"], "producer_record": original,
            "producer_status": envelope["amendment_occurrences"][ordinal],
            "target_resolution": {"status": "unresolved", "candidate_document": original["target_law"],
                                  "candidate_expression": original["target"], "basis": "producer_candidate_only"},
            "parsed_evidence": {**parsed_pointer, "json_pointer": f"/record/amendments/{ordinal}"},
            "source_alignment": {"status": "unique_text_match" if len(matches) == 1 else "unresolved",
                                 "reason": None if len(matches) == 1 else "ambiguous_text_match" if matches else "no_unique_text_match",
                                 "method": "xml_block_text_ascii_whitespace_v1",
                                 "candidates": [source_pointer(n) for n in matches]}})
    claims = []
    for kind, identity in [("act", act_id), *(("operation", op["operation_id"]) for op in operations)]:
        subject = {"kind": kind, "id": identity}
        if kind == "act":
            subject["parsed_revision_id"] = parsed_revision_id
        claim = {"contract": CLAIM_VERSION, "subject": subject,
                 "source_occurrence_id": occurrence, "observation_id": receipt["observation_id"],
                 "method": "retain_unresolved_no_legal_interpretation-v1", "supersedes": [],
                 "legal_valid_time": {"status": "unresolved", "from": None, "until": None,
                                      "reason": "source_expressions_have_not_been_scoped_or_legally_interpreted"},
                 "target_resolution_status": "unresolved" if kind == "operation" else "not_applicable",
                 "clocks": clocks, "parsed_evidence": parsed_pointer if kind == "act" else
                 next(op["parsed_evidence"] for op in operations if op["operation_id"] == identity),
                 "act_expression_candidates": [e["expression_id"] for e in expressions],
                 "expression_scope_assignment": "unresolved"}
        claim["claim_id"] = _identity(CLAIM_VERSION, claim)
        claims.append(claim)
    return deepcopy({"contract": VERSION, "act": act, "operations": operations, "claims": claims})
