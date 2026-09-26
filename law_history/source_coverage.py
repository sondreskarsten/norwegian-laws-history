"""Source availability by document, without promoting it to legal coverage."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .ledger import list_observations, read_observation
from .validation import file_hash, read_json, require, timestamp

CONTRACT = "history-source-availability-v1"


def source_coverage(repository: Path, refid: str | None = None, known_at: str | None = None) -> dict:
    """Inventory accepted bytes, retaining occurrences and archive roles.

    A matching Lovtidend refid is a candidate original text, not a qualified
    enactment/baseline. Reader Markdown is explicitly outside primary evidence.
    No absence here proves that evidence is unavailable outside this ledger.
    """
    repository = Path(repository)
    cutoff = timestamp(known_at) if known_at is not None else None
    accepted = list_observations(repository)
    summaries = [s for s in accepted if cutoff is None or
                 s["knowledge_cutoff"] is not None and timestamp(s["knowledge_cutoff"]) <= cutoff]
    summaries.sort(key=lambda s: (s["knowledge_cutoff"] is not None,
        timestamp(s["knowledge_cutoff"]) if s["knowledge_cutoff"] is not None else None,
        s["observation_id"]))
    documents, inputs = {}, []

    def document(identity):
        return documents.setdefault(identity, {"refid": identity, "source_versions": {},
            "current_corpus_observations": [], "derived_reader_copies": []})

    for summary in summaries:
        observation = summary["observation_id"]
        receipt, checked, members = read_observation(repository, observation)
        require(checked == summary, "Observation changed during coverage inventory")
        inputs.append({"observation_id": observation, "knowledge_cutoff": summary["knowledge_cutoff"],
            "catalog_sha256": summary["catalog_sha256"], "receipt_sha256": summary["receipt_sha256"],
            "source_observation_sha256": summary["source_observation_sha256"], "scope": summary["scope"],
            "receipt_url": receipt["receipt_url"]})
        for member in members:
            identity = member["refid"]
            if not identity or refid is not None and identity != refid:
                continue
            row = document(identity)
            key = (member["role"], member["member_sha256"])
            version = row["source_versions"].setdefault(key, {"role": member["role"],
                "member_sha256": member["member_sha256"], "occurrences": []})
            version["occurrences"].append({"observation_id": observation,
                "source_occurrence_id": member["source_occurrence_id"],
                "archive_ordinal": member["archive_ordinal"], "member_ordinal": member["member_ordinal"],
                "member_path": member["member_path"], "selected": member["selected"],
                "parse_status": member["parse_status"]})
            if member["selected"] and member["role"] in {"laws", "forskrifter"}:
                if observation not in row["current_corpus_observations"]:
                    row["current_corpus_observations"].append(observation)

    # These copies have no accepted primary-source knowledge time. Include them
    # only in a present-day inventory, never in a historical knowledge query.
    archive = repository / "reader-archive/index.json"
    archive_proof = None
    if cutoff is None and archive.is_file():
        inventory = read_json(archive)
        require(inventory.get("schema") == "prior-reader-copy-inventory-v1", "Unknown reader archive")
        for copy in inventory["records"]:
            if refid is not None and copy["refid"] != refid:
                continue
            relative = Path(copy["copy_path"])
            require(not relative.is_absolute() and ".." not in relative.parts, "Unsafe reader copy path")
            content = archive.parent / relative
            require(file_hash(content) == copy["content_sha256"], "Retained reader copy changed")
            document(copy["refid"])["derived_reader_copies"].append({
                "content_sha256": copy["content_sha256"], "reader_copy_url": copy["reader_copy_url"],
                "primary_evidence": False, "knowledge_time": "unknown"})
        archive_proof = {"path": "reader-archive/index.json", "sha256": file_hash(archive)}

    totals = Counter()
    rows = []
    for identity, row in sorted(documents.items()):
        row["source_versions"] = [v for _, v in sorted(row["source_versions"].items())]
        has_promulgation = any(v["role"] == "amendment_acts" for v in row["source_versions"])
        has_current = bool(row["current_corpus_observations"])
        row["original_text_candidate"] = "retained_lovtidend_occurrence" if has_promulgation else "not_found_in_accepted_catalogs"
        row["historical_coverage"] = {"status": "not_assessed", "justified_baseline": None,
            "supported_legal_intervals": [], "gaps": [
                "original_text_and_legal_start_require_qualification" if has_promulgation else "original_promulgation_not_retained_under_this_refid",
                "complete_amendment_chain_not_established", "scoped_commencement_and_corrections_not_established"],
            "external_source_availability": "not_determined_by_this_inventory"}
        totals["documents"] += 1
        totals["with_current_corpus_observations"] += has_current
        totals["with_lovtidend_original_text_candidates"] += has_promulgation
        totals["derived_reader_only"] += not row["source_versions"] and bool(row["derived_reader_copies"])
        totals["distinct_role_and_source_hash_versions"] += len(row["source_versions"])
        rows.append(row)
    return {"contract": CONTRACT, "scope": "accepted_source_availability_not_legal_coverage",
        "requested_refid": refid, "requested_known_at": known_at,
        "latest_included_knowledge_cutoff": summaries[-1]["knowledge_cutoff"] if summaries else None,
        "inputs": inputs, "derived_archive": archive_proof, "counts": dict(totals), "documents": rows}
