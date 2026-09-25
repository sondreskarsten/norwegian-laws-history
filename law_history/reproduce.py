"""Reproduce one published body product with its exact generator, offline."""
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

from .ledger import _directory, ensure_bundle, read_observation
from .materialize import generator_identity, materializations, materialize, read_materialization
from .publication import _creation_receipt, _text
from .validation import canonical, file_hash, read_json, require


def reproduce(repository: Path, identity: str) -> dict:
    repository = Path(repository).absolute()
    target = read_materialization(repository, identity)
    require(target["generator"] == generator_identity(),
            "Reproduction requires the product's exact generator source and Python runtime")
    published_path = repository / "publications" / (identity + ".json")
    published = read_json(published_path)
    expected = _creation_receipt(repository, target, published["github_repository"], published["branch"])
    require(published == expected and published_path.read_bytes() == canonical(expected, newline=True),
            "Published product Git receipt changed")
    chain = materializations(repository)
    index = next(i for i, item in enumerate(chain) if item["materialization_id"] == identity)
    original = {item["materialization_id"]: file_hash(repository / "materializations" /
                 item["materialization_id"] / "receipt.json") for item in chain}
    release, _, _ = read_observation(repository, target["observation_id"])
    bundle = ensure_bundle(repository, release)
    _directory(repository / ".cache")
    with tempfile.TemporaryDirectory(prefix="reproduce-", dir=repository / ".cache") as temporary:
        fresh = Path(temporary)
        observed = fresh / "observations" / target["observation_id"]
        shutil.copytree(repository / "observations" / target["observation_id"], observed)
        for item in chain[:index]:
            key = item["materialization_id"]
            shutil.copytree(repository / "materializations" / key, fresh / "materializations" / key)
        cached = fresh / ".cache" / "bundles" / bundle.name
        cached.parent.mkdir(parents=True)
        os.link(bundle, cached)
        require(not (fresh / "materializations" / identity).exists(), "Target was copied instead of regenerated")
        # The bundle is already cached. Deny both URL access and direct socket/DNS
        # access during the complete source validation and fresh generation.
        with ExitStack() as denied:
            for module, name in ((urllib.request, "urlopen"), (socket, "socket"),
                                 (socket, "create_connection"), (socket, "getaddrinfo")):
                denied.enter_context(patch.object(module, name, side_effect=AssertionError("Offline reproduction attempted network access")))
            generated = materialize(fresh, target["observation_id"], target["refids"],
                                    target["parent_materialization_id"] or "none")
        require(generated["status"] == "accepted" and generated["materialization_id"] == identity,
                "Freshly generated product identity differs from publication")
        matches = {}
        for name in [*target["artifact_hashes"], "receipt.json"]:
            path = Path("materializations") / identity / name
            require((fresh / path).read_bytes() == (repository / path).read_bytes(),
                    "Regenerated artifact differs from publication: " + name)
            matches[name] = file_hash(fresh / path)
    require(original == {item["materialization_id"]: file_hash(repository / "materializations" /
                item["materialization_id"] / "receipt.json") for item in materializations(repository)},
            "Published product chain changed during reproduction")
    return {"contract": "history-offline-body-reproduction-v1", "status": "reproduced",
            "materialization_id": identity, "observation_id": target["observation_id"],
            "checked_checkout": _text(repository, "rev-parse", "HEAD"),
            "publication": published, "generator": target["generator"],
            "source_bundle_sha256": file_hash(bundle), "network_during_regeneration": "denied",
            "target_product_copied": False, "artifact_hashes": matches,
            "preserved_prior_product_receipts": original,
            "legal_valid_time": target["legal_valid_time"],
            "scope": "selected published observed-body product; not a clean-fork publication or legal-state reconstruction"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("materialization")
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = reproduce(args.repository, args.materialization)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "materialization_id", "observation_id", "network_during_regeneration")}))
