"""Export committed observed-body versions for a static reader, without changing the ledger."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import tempfile

from .publication import _creation_receipt, _git, _text
from .source_body_products import artifact_tree, body_products, _rows, LEGAL
from .validation import canonical, read_json, require, value_hash

SCOPE = "recorded_qualification_and_exact_published_bytes"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def export_reader(repository: Path, output: Path) -> dict:
    repository, output = Path(repository).resolve(), Path(output).absolute()
    require(not output.exists(), "Reader export destination already exists")
    head = _text(repository, "rev-parse", "HEAD")
    chain = body_products(repository, verify=False)
    remote = _text(repository, "remote", "get-url", "origin")
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?", remote)
    require(match is not None, "Reader export requires a public GitHub origin")
    project = match.group(1)
    pinned = {}

    def committed(name):
        data = (repository / name).read_bytes()
        require(_git(repository, "cat-file", "blob", head + ":" + name).stdout == data,
                "Reader evidence is changed or uncommitted: " + name)
        pinned[name] = data
        return data

    for receipt in chain:
        identity = receipt["body_product_id"]
        require(receipt["repository"] == project, "Reader product belongs to another repository")
        committed("body-products/" + identity + "/receipt.json")
        proof_name = "body-publications/" + identity + ".json"
        proof = json.loads(committed(proof_name))
        require(proof["github_repository"] == project
                and canonical(_creation_receipt(repository, receipt, project, proof["branch"], body=True), newline=True) == pinned[proof_name],
                "Reader product publication proof is invalid")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".reader-export-", dir=output.parent) as temporary:
        fresh = Path(temporary) / "export"
        fresh.mkdir()
        versions = defaultdict(list)
        products = []
        for receipt in chain:
            identity = receipt["body_product_id"]
            tree = artifact_tree(repository, receipt)
            base = f"https://github.com/{project}/blob/{head}/"
            summary = {key: receipt[key] for key in ("body_product_id", "observation_id", "knowledge_cutoff", "counts", "gate_version", "source_receipt_url")}
            summary.update(receipt_url=base + f"body-products/{identity}/receipt.json",
                           publication_url=base + f"body-publications/{identity}.json",
                           bundle_url=receipt["bundle"]["url"])
            products.append(summary)
            source_name = "observations/" + receipt["observation_id"] + "/receipt.json"
            source = json.loads(committed(source_name))
            require(source["bundle"]["sha256"] == receipt["source_bundle_sha256"], "Reader source bundle differs")
            inventory = list(_rows(tree / "inventory.jsonl.gz"))
            require(len({r["refid"] for r in inventory}) == len(inventory), "Duplicate reader inventory identity")
            by_shard = defaultdict(dict)
            counts = dict.fromkeys(receipt["counts"], 0)
            for row in inventory:
                status, refid = row["status"], row["refid"]
                require(status in ("passed", "rejected") and row["qualification"]["status"] == status, "Invalid recorded qualification")
                member = row["source_member"]
                require(member["refid"] == refid and member["source_occurrence_id"] == row["source_occurrence_id"]
                        and member["member_sha256"] == row["raw_member_sha256"], "Reader source member differs")
                version = {key: summary[key] for key in ("body_product_id", "observation_id", "knowledge_cutoff", "source_receipt_url", "bundle_url", "receipt_url", "publication_url")}
                version.update({key: row[key] for key in ("source_occurrence_id", "status", "change", "semantic_sha256", "body_sha256")})
                version.update(reasons=row["qualification"].get("reasons", []), legal_valid_time=LEGAL,
                               html_sha256=None, html_path=None, source_bundle_url=source["bundle"]["url"],
                               source_member={key: member[key] for key in ("archive_sha256", "member_path", "member_sha256", "member_ordinal", "role")})
                versions[refid].append(version)
                if status == "passed":
                    pointer = row["payload"]
                    require(pointer["shard"] in receipt["shards"], "Reader payload shard is outside receipt")
                    by_shard[pointer["shard"]][refid] = (row, version)
                else:
                    require(row["payload"] is None and version["reasons"], "Rejected body exposes a payload or lacks a reason")
                counts["selected"] += 1
                counts[row["role"]] += 1
                counts[status] += 1
            require(counts == receipt["counts"] and set(by_shard) == set(receipt["shards"]), "Reader inventory counts/shards differ")
            for shard, expected in by_shard.items():
                for payload in _rows(tree / shard):
                    refid = payload["refid"]
                    require(refid in expected, "Unexpected or duplicate reader payload")
                    row, version = expected.pop(refid)
                    data = payload["html"].encode("utf-8")
                    require(_sha(canonical(payload, newline=True)) == row["payload"]["record_sha256"]
                            and payload["source_occurrence_id"] == row["source_occurrence_id"]
                            and value_hash(payload["source_body"]) == row["source_body_model_sha256"]
                            and _sha(data) == row["html_sha256"]
                            and _sha(payload["stylesheet"].encode("utf-8")) == row["stylesheet_sha256"], "Reader payload bytes or source binding differ")
                    name = "bodies/" + row["html_sha256"] + ".html"
                    path = fresh / name
                    path.parent.mkdir(exist_ok=True)
                    if path.exists():
                        require(path.read_bytes() == data, "Reader HTML digest collision")
                    else:
                        path.write_bytes(data)
                    version.update(html_sha256=row["html_sha256"], html_path=name)
                require(not expected, "Reader shard omitted qualified documents")
        index = {"contract": "history-reader-export-v1", "history_repository": project, "history_commit": head,
                 "scope": SCOPE, "source_requalification_in_this_export": False, "legal_valid_time": LEGAL,
                 "products": products, "documents": {}}
        for refid, rows in sorted(versions.items()):
            document = {"contract": "history-reader-document-v1", "refid": refid,
                        "history_repository": project, "history_commit": head, "scope": SCOPE,
                        "legal_valid_time": LEGAL, "versions": rows}
            data = canonical(document, newline=True)
            name = "documents/" + _sha(refid.encode("utf-8")) + ".json"
            (fresh / name).parent.mkdir(exist_ok=True)
            (fresh / name).write_bytes(data)
            index["documents"][refid] = {"path": name, "metadata_sha256": _sha(data), "versions": len(rows),
                                          "qualified_versions": sum(row["status"] == "passed" for row in rows)}
        (fresh / "index.json").write_bytes(canonical(index, newline=True))
        require(_text(repository, "rev-parse", "HEAD") == head
                and all((repository / name).read_bytes() == data for name, data in pinned.items()),
                "History checkout changed during reader export")
        require(not output.exists(), "Reader export destination appeared during generation")
        fresh.rename(output)
    return {"status": "exported", "history_commit": head, "products": len(products),
            "documents": len(index["documents"]), "index_sha256": _sha(canonical(index, newline=True))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_reader(args.repository, args.output)))
