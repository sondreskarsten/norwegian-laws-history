"""Retrieve one qualified payload from a pinned, byte-verified body product."""
from pathlib import Path
import hashlib

from .validation import canonical, require, value_hash


def read_body(repository: Path, refid: str, product_id: str) -> dict:
    """Verify product artifact bytes without rerunning the whole corpus gate.

    This is retrieval of a product's recorded qualification. Use read_body_product
    for independent requalification against raw source; the distinction is
    returned explicitly with every lookup.
    """
    from .source_body_products import artifact_tree, read_body_receipt, _rows
    receipt = read_body_receipt(repository, product_id)
    root = artifact_tree(repository, receipt)
    matches = [row for row in _rows(root / "inventory.jsonl.gz") if row["refid"] == refid]
    require(len(matches) <= 1, "Body inventory contains duplicate selected identities")
    result = {"body_product_id": product_id, "observation_id": receipt["observation_id"],
              "knowledge_cutoff": receipt["knowledge_cutoff"], "refid": refid,
              "legal_valid_time": receipt["legal_valid_time"],
              "read_verification": "pinned_receipt_and_exact_artifact_bytes",
              "source_requalification_in_this_read": False, "document": None}
    if not matches:
        return {**result, "status": "not_in_selected_observation"}
    row = matches[0]
    result["qualification"] = row["qualification"]
    result["source_occurrence_id"] = row["source_occurrence_id"]
    if row["status"] == "rejected":
        require(row["payload"] is None and row["qualification"]["status"] == "rejected"
                and row["qualification"].get("reasons"), "Rejected body has inconsistent qualification")
        return {**result, "status": "not_qualified"}
    require(row["status"] == row["qualification"]["status"] == "passed", "Unknown body qualification")
    pointer = row["payload"]
    require(isinstance(pointer, dict) and pointer.get("shard") in receipt["shards"], "Body payload points outside receipt")
    documents = [item for item in _rows(root / pointer["shard"]) if item["refid"] == refid]
    require(len(documents) == 1, "Body payload is missing or duplicated")
    document = documents[0]
    require(hashlib.sha256(canonical(document, newline=True)).hexdigest() == pointer["record_sha256"]
            and document["source_occurrence_id"] == row["source_occurrence_id"]
            and value_hash(document["source_body"]) == row["source_body_model_sha256"]
            and hashlib.sha256(document["html"].encode("utf-8")).hexdigest() == row["html_sha256"]
            and hashlib.sha256(document["stylesheet"].encode("utf-8")).hexdigest() == row["stylesheet_sha256"],
            "Body payload/source/representation identities disagree")
    return {**result, "status": "qualified", "document": document}
