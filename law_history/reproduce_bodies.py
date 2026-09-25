"""Regenerate one published complete body product with network access denied."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import urllib.request
from unittest.mock import patch

from .body_transport import ensure_bundle as body_bundle
from .ledger import _directory, ensure_bundle as source_bundle, read_observation
from .publication import _creation_receipt, _git, _text
from .source_body_products import (artifact_tree, body_products, generator_identity,
                                   qualify_bodies, read_body_receipt)
from .validation import canonical, file_hash, read_json, require


def reproduce(repository: Path, identity: str) -> dict:
    repository = Path(repository).absolute()
    target = read_body_receipt(repository, identity)
    require(target["generator"] == generator_identity(),
            "Reproduction requires the exact generator source, Python and zlib runtime")
    name = "body-publications/" + identity + ".json"
    path = repository / name
    publication = read_json(path)
    expected = _creation_receipt(repository, target, publication["github_repository"],
                                 publication["branch"], body=True)
    require(path.read_bytes() == canonical(expected, newline=True)
            and _git(repository, "cat-file", "blob", "HEAD:" + name).stdout == path.read_bytes(),
            "Body publication proof is changed or not committed")
    chain = body_products(repository, verify=False)
    index = next(i for i, item in enumerate(chain) if item["body_product_id"] == identity)
    original = {item["body_product_id"]: file_hash(repository / "body-products" /
                item["body_product_id"] / "receipt.json") for item in chain}
    release, _, _ = read_observation(repository, target["observation_id"])
    source = source_bundle(repository, release)
    published_bundle = body_bundle(repository, target)
    published_artifacts = artifact_tree(repository, target)
    comparison = target["comparison_product_id"]
    previous_bundle = (body_bundle(repository, read_body_receipt(repository, comparison))
                       if comparison else None)
    _directory(repository / ".cache")
    with tempfile.TemporaryDirectory(prefix="reproduce-bodies-", dir=repository / ".cache") as temporary:
        fresh = Path(temporary)
        # All ancestor observation clocks participate in comparison selection.
        # Only the target raw source is needed for regeneration.
        observations = {target["observation_id"], *(item["observation_id"] for item in chain[:index])}
        for observation in observations:
            read_observation(repository, observation)
            shutil.copytree(repository / "observations" / observation,
                            fresh / "observations" / observation)
        for item in chain[:index]:
            prior = item["body_product_id"]
            shutil.copytree(repository / "body-products" / prior, fresh / "body-products" / prior)
        for bundle, directory in ((source, "bundles"), (previous_bundle, "body-bundles")):
            if bundle is not None:
                cached = fresh / ".cache" / directory / bundle.name
                cached.parent.mkdir(parents=True, exist_ok=True)
                os.link(bundle, cached)
        # An unchanged/empty prior product can share the same bundle digest.
        # Only its comparison dependency is cached; the target receipt and
        # artifact tree must still be newly generated.
        require(not (fresh / "body-products" / identity).exists()
                and not (fresh / ".cache/body-artifacts" / identity).exists(),
                "Target receipt or artifact tree was copied instead of regenerated")
        with ExitStack() as denied:
            for module, attr in ((urllib.request, "urlopen"), (socket, "socket"),
                                 (socket, "create_connection"), (socket, "getaddrinfo")):
                denied.enter_context(patch.object(module, attr,
                    side_effect=AssertionError("Offline body reproduction attempted network access")))
            generated = qualify_bodies(fresh, target["observation_id"],
                expected_parent=target["parent_body_product_id"] or "none",
                github_repository=target["repository"])
        require(generated["status"] == "accepted" and generated["body_product_id"] == identity,
                "Regenerated body product identity differs from publication")
        fresh_receipt = fresh / "body-products" / identity / "receipt.json"
        require(fresh_receipt.read_bytes() == (repository / "body-products" / identity / "receipt.json").read_bytes(),
                "Regenerated body receipt differs from publication")
        require((fresh / ".cache/body-bundles" / published_bundle.name).is_file()
                and (fresh / ".cache/body-artifacts" / identity).is_dir(),
                "Generation did not produce a local body bundle and artifact tree")
        regenerated_bundle = body_bundle(fresh, generated)
        require(file_hash(regenerated_bundle) == file_hash(published_bundle)
                and regenerated_bundle.stat().st_size == published_bundle.stat().st_size,
                "Regenerated body bundle differs from publication")
        regenerated_artifacts = artifact_tree(fresh, generated)
        matches = {"receipt.json": file_hash(fresh_receipt)}
        for name in target["artifact_hashes"]:
            actual = file_hash(regenerated_artifacts / name)
            require(actual == file_hash(published_artifacts / name) == target["artifact_hashes"][name],
                    "Regenerated body artifact differs from publication: " + name)
            matches[name] = actual
    require(original == {item["body_product_id"]: file_hash(repository / "body-products" /
                item["body_product_id"] / "receipt.json") for item in body_products(repository, verify=False)},
            "Original body products changed during reproduction")
    return {"contract": "history-offline-source-body-reproduction-v1", "status": "reproduced",
            "body_product_id": identity, "observation_id": target["observation_id"],
            "checked_checkout": _text(repository, "rev-parse", "HEAD"),
            "publication": publication, "generator": target["generator"],
            "source_bundle_sha256": file_hash(source), "body_bundle_sha256": file_hash(published_bundle),
            "comparison_dependency": comparison,
            "network_during_regeneration": "denied", "target_product_copied": False,
            "artifact_hashes": matches, "preserved_product_receipts": original,
            "legal_valid_time": target["legal_valid_time"],
            "scope": "exact published observed-body representation; not legal reconstruction or a clean fork"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("product")
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = reproduce(args.repository, args.product)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "body_product_id", "network_during_regeneration")}))
