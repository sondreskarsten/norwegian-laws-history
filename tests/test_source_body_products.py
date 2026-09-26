"""Full selected-corpus products from real retained XML and small contract fixtures."""
from copy import deepcopy
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from law_history import source_body_products as products
from law_history.ledger import ingest, raw_member
from law_history.validation import canonical, value_hash, SOURCE_BODY_CONTRACT
from test_consumer import fixture

FIXTURES = Path(__file__).parent / "fixtures/source_body"


def small_xml(refid="lov/2024-01-01-1", *, content="First important text.", context=""):
    return (f'<html lang="nb"><head><base href="https://lovdata.no/"/></head><body{context}>'
            f'<header><dl><dd class="refid">{refid}</dd></dl></header>'
            f'<main class="documentBody" data-lovdata-URL="NL/{refid}">'
            f'<article class="legalP">{content}</article></main></body></html>').encode()


def captured(raw):
    """Small independent fixture serializer; production uses the producer capture."""
    root = ET.fromstring(raw)
    body = root.find("body")
    head = root.find("head")
    refid = root.find('.//dd[@class="refid"]').text.strip()
    def node(element):
        children = [element.text] if element.text else []
        for child in element:
            children.append(node(child))
            if child.tail: children.append(child.tail)
        return {"tag": element.tag, "attributes": dict(element.attrib), "children": children}
    tree = node(body.find('main[@class="documentBody"]'))
    context = {"html_lang": root.get("lang"), "html_attributes": dict(root.attrib),
               "head_attributes": dict(head.attrib), "body_attributes": dict(body.attrib),
               "source_base": head.find("base").get("href"), "refid": refid}
    return {"contract": SOURCE_BODY_CONTRACT[0], "member_sha256": hashlib.sha256(raw).hexdigest(),
            "context": context, "root": tree, "body_sha256": value_hash(tree),
            "semantic_sha256": value_hash([SOURCE_BODY_CONTRACT[0], context, tree])}


def source_fixture(directory, documents, *, observed="2026-09-25T12:00:00+00:00"):
    def configure(manifest, artifacts):
        obs = json.loads(artifacts["source-observations.json"])
        template = deepcopy(obs["archives"][0])
        for name in list(artifacts):
            if name.startswith("raw/"): del artifacts[name]
        obs["archives"] = []
        obs["parser_identity"]["source_files"]["source_body.py"] = "c" * 64
        obs["parser_identity"]["sha256"] = value_hash(obs["parser_identity"]["source_files"])
        members, counts = [], {"laws": 0, "forskrifter": 0, "amendment_acts": 0}
        for role in ("laws", "forskrifter"):
            selected = [(raw, captured(raw)) for raw in documents
                        if (raw_refid(raw).startswith("lov/") if role == "laws" else not raw_refid(raw).startswith("lov/"))]
            if not selected and role == "forskrifter": continue
            archive_bytes = io.BytesIO()
            with tarfile.open(fileobj=archive_bytes, mode="w:bz2") as archive:
                for ordinal, (raw, body) in enumerate(selected):
                    info = tarfile.TarInfo(f"nested/{ordinal}.xml"); info.size = len(raw)
                    archive.addfile(info, io.BytesIO(raw))
            data = archive_bytes.getvalue(); digest = hashlib.sha256(data).hexdigest()
            path = f"raw/{digest}.tar.bz2"; artifacts[path] = data
            archive_ordinal = len(obs["archives"])
            obs["archives"].append({**template, "role": role, "archive_ordinal": archive_ordinal,
                "archive_sha256": digest, "raw_path": path, "size_bytes": len(data),
                "member_count": len(selected), "parsed_occurrence_count": len(selected)})
            for ordinal, (raw, body) in enumerate(selected):
                refid = body["context"]["refid"]
                model = {"refid": refid, "title": refid, "source_body": body}
                name = f"{role}/{refid.replace('/', '-')}.json"
                artifacts[name] = canonical(model, newline=True)
                members.append({"archive_ordinal": archive_ordinal, "archive_sha256": digest, "role": role,
                    "member_ordinal": ordinal, "member_path": f"nested/{ordinal}.xml", "member_type": "file",
                    "member_size_bytes": len(raw), "member_sha256": body["member_sha256"], "parse_status": "parsed",
                    "refid": refid, "parsed_occurrence_ordinal": ordinal, "parsed_model_sha256": value_hash(model),
                    "source_occurrence_id": value_hash([archive_ordinal, digest, ordinal, f"nested/{ordinal}.xml", body["member_sha256"], role]),
                    "selected": True, "selected_output_path": name,
                    "selected_output_sha256": hashlib.sha256(artifacts[name]).hexdigest()})
            counts[role] = len(selected)
        artifacts["source-observations.json"] = canonical(obs, newline=True)
        artifacts["source-members.jsonl"] = b"".join(canonical(row, newline=True) for row in members)
        manifest.update(version=5, content_version=SOURCE_BODY_CONTRACT[0], formatter_version=SOURCE_BODY_CONTRACT[1],
                        law_count=counts["laws"], forskrift_count=counts["forskrifter"])
        manifest["evidence"].update(archive_count=len(obs["archives"]), member_count=len(members), parsed_occurrence_counts=counts)
    return fixture(directory, present=False, observed=observed, mutate=configure)


def raw_refid(raw):
    return ET.fromstring(raw).find('.//dd[@class="refid"]').text.strip()


class SourceBodyProductTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="body-products-test-")
        self.root = Path(self.temp.name); self.repository = self.root / "ledger"
        self.sequence = 0

    def tearDown(self):
        self.temp.cleanup()

    def accept(self, documents):
        self.sequence += 1
        path, receipt, _ = source_fixture(self.root / str(self.sequence), documents,
            observed=f"2026-09-{24 + self.sequence:02d}T12:00:00+00:00")
        ingest(str(path), self.repository)
        return receipt["observation_id"]

    def build(self, documents):
        return products.qualify_bodies(self.repository, self.accept(documents))

    def rows(self, receipt, name="inventory.jsonl.gz"):
        return list(products._rows(products.artifact_tree(self.repository, receipt) / name))

    def test_three_real_complex_bodies_and_rejected_context_cover_full_inventory(self):
        raws = [(FIXTURES / name).read_bytes() for name in
                ("lov-1687-04-15.xml", "lov-1751-10-02.xml", "forskrift-1969-06-27-4.xml")]
        self.assertEqual(len(raws), 3)
        rejected = small_xml(context=' dir="rtl"')
        receipt = self.build([*raws, rejected])
        self.assertEqual(receipt["counts"], {"selected": 4, "laws": 3, "forskrifter": 1, "passed": 3, "rejected": 1})
        inventory = self.rows(receipt)
        self.assertEqual({row["refid"] for row in inventory}, {raw_refid(raw) for raw in [*raws, rejected]})
        failed = [row for row in inventory if row["status"] == "rejected"]
        self.assertEqual(failed[0]["qualification"]["reasons"][0]["code"], "unsupported_context")
        self.assertIsNone(failed[0]["payload"])
        documents = [doc for shard in receipt["shards"] for doc in self.rows(receipt, shard)]
        self.assertEqual(len(documents), 3)
        for doc in documents:
            row = next(row for row in inventory if row["refid"] == doc["refid"])
            raw = next(raw for raw in raws if raw_refid(raw) == doc["refid"])
            self.assertEqual(doc["source_body"], captured(raw))
            self.assertEqual(raw_member(self.repository, receipt["observation_id"], doc["refid"]), raw)
            self.assertEqual(hashlib.sha256(canonical(doc, newline=True)).hexdigest(), row["payload"]["record_sha256"])
            self.assertIn(doc["stylesheet"], doc["html"])
        self.assertEqual(products.read_body_product(self.repository, receipt["body_product_id"])["counts"], receipt["counts"])
        files = list((self.repository / "body-products").rglob("*"))
        self.assertEqual([path.name for path in files if path.is_file()], ["receipt.json"])

    def test_no_pilot_cap_and_routine_replay_avoids_old_source_or_bundle(self):
        receipt = self.build([small_xml(f"lov/2024-01-01-{i}") for i in range(1, 24)])
        self.assertEqual(receipt["counts"]["selected"], 23)
        before = (self.repository / "body-products" / receipt["body_product_id"] / "receipt.json").read_bytes()
        changed = products.generator_identity(); changed["python"] = "new-runtime"
        with patch.object(products, "generator_identity", return_value=changed), patch.object(products, "_input", side_effect=AssertionError("old input read")), patch.object(products, "artifact_tree", side_effect=AssertionError("old bundle read")):
            result = products.qualify_all(self.repository)
        self.assertEqual(result[0]["status"], "already_present")
        self.assertEqual(before, (self.repository / "body-products" / receipt["body_product_id"] / "receipt.json").read_bytes())
        value = products.generator_identity(); value["sources"].clear()
        self.assertTrue(products.generator_identity()["sources"])

    def test_rejection_absence_and_reentry_preserve_last_qualified_comparison(self):
        first = self.build([small_xml()])
        preserved = {path: path.read_bytes() for path in (self.repository / "body-products").rglob("receipt.json")}
        rejected = self.build([small_xml(context=' dir="rtl"')])
        missing = self.build([])
        for receipt in (rejected, missing):
            baseline = self.rows(receipt, "last-qualified.jsonl.gz")
            self.assertEqual(baseline[0]["body_product_id"], first["body_product_id"])
        returning = self.build([small_xml(content="Changed source words.")])
        row = self.rows(returning)[0]
        self.assertEqual(row["comparison"]["body_product_id"], first["body_product_id"])
        self.assertEqual(row["change"], "observed_body_change")
        self.assertEqual(returning["parent_body_product_id"], missing["body_product_id"])
        self.assertEqual(returning["legal_valid_time"], products.LEGAL)
        self.assertTrue(all(path.read_bytes() == data for path, data in preserved.items()))
        self.assertEqual(len(products.body_products(self.repository, verify=False)), 4)

    def test_explicit_updated_representation_appends_and_unchanged_body_is_not_legal_change(self):
        first = self.build([small_xml()])
        generator = products.generator_identity(); generator["python"] = "new-runtime"
        with patch.object(products, "generator_identity", return_value=generator):
            second = products.qualify_bodies(self.repository, first["observation_id"])
        self.assertEqual(second["status"], "accepted")
        self.assertNotEqual(second["body_product_id"], first["body_product_id"])
        self.assertEqual(self.rows(second)[0]["change"], "unchanged")
        self.assertEqual(products.qualify_bodies(self.repository, second["observation_id"], reuse_existing_observation=True)["body_product_id"], second["body_product_id"])

    def test_selected_raw_identity_corruption_and_extra_artifact_fail(self):
        receipt = self.build([small_xml()])
        tree = products.artifact_tree(self.repository, receipt)
        (tree / "extra.txt").write_text("not declared")
        with self.assertRaisesRegex(ValueError, "membership"):
            products.read_body_product(self.repository, receipt["body_product_id"])
        (tree / "extra.txt").unlink()
        source = self.repository / ".cache" / "bundles"
        # Supply a separately unpacked source, then change the selected model.
        release, _, _ = products.read_observation(self.repository, receipt["observation_id"])
        snapshot = self.root / "snapshot"; snapshot.mkdir()
        products.unpack_bundle(products.source_bundle(self.repository, release), snapshot, release)
        model = next((snapshot / "laws").glob("*.json"))
        model.write_bytes(model.read_bytes().replace(b"First", b"Other"))
        with self.assertRaises(ValueError):
            products.read_body_product(self.repository, receipt["body_product_id"], snapshot=snapshot)

    def test_reidentified_invented_prior_comparison_rejected_by_direct_parent(self):
        first = self.build([small_xml()]); second = self.build([small_xml(content="Changed.")])
        original = products.artifact_tree(self.repository, second)
        stage = self.root / "forged"; stage.mkdir()
        for path in original.rglob("*"):
            if path.is_file():
                out = stage / path.relative_to(original); out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(path.read_bytes())
        rows = list(products._rows(stage / "inventory.jsonl.gz"))
        rows[0]["comparison"]["semantic_sha256"] = "0" * 64
        (stage / "inventory.jsonl.gz").unlink()
        with products._gzip_writer(stage / "inventory.jsonl.gz") as stream:
            for row in rows: stream.write(canonical(row, newline=True))
        receipt = deepcopy(second); receipt.pop("status")
        receipt["artifact_hashes"] = {name: products.file_hash(stage / name) for name in receipt["artifact_hashes"]}
        receipt["bundle"] = products._bundle(stage, self.root / "forged.tar.gz", receipt["artifact_hashes"])
        core = {k: v for k, v in receipt.items() if k not in {"body_product_id", "release_tag"}}
        identity = hashlib.sha256(canonical(core, newline=True)).hexdigest()
        receipt.update(body_product_id=identity, release_tag="bodies-" + identity)
        receipt["bundle"]["url"] = f'https://github.com/{receipt["repository"]}/releases/download/{receipt["release_tag"]}/bodies.tar.gz'
        destination = self.root / "forged-ledger/body-products" / identity; destination.mkdir(parents=True)
        (destination / "receipt.json").write_bytes(canonical(receipt, newline=True))
        with self.assertRaisesRegex(ValueError, "differs from source"):
            products.read_body_product(self.root / "forged-ledger", identity, ledger_repository=self.repository, artifacts=stage)

    def test_legacy_input_not_promoted_and_expected_parent_checked(self):
        path, old, _ = fixture(self.root / "legacy")
        ingest(str(path), self.repository)
        self.assertEqual(products.qualify_all(self.repository), [])
        with self.assertRaisesRegex(ValueError, "v5"):
            products.qualify_bodies(self.repository, old["observation_id"])
        first = self.build([small_xml()])
        with self.assertRaisesRegex(ValueError, "parent changed"):
            products.qualify_bodies(self.repository, first["observation_id"], expected_parent="none")

    def test_historical_reprocessing_compares_only_eligible_source_prefix(self):
        first = self.build([small_xml()])
        second = self.build([small_xml(content="Later observed text.")])
        before = {path: path.read_bytes() for path in (self.repository / "body-products").rglob("receipt.json")}
        generator = products.generator_identity(); generator["python"] = "new-runtime"
        with patch.object(products, "generator_identity", return_value=generator):
            old_rebuilt = products.qualify_bodies(self.repository, first["observation_id"])
            latest_rebuilt = products.qualify_bodies(self.repository, second["observation_id"])
            replay = products.qualify_bodies(self.repository, first["observation_id"], reuse_existing_observation=True)
        self.assertEqual(old_rebuilt["parent_body_product_id"], second["body_product_id"])
        self.assertEqual(old_rebuilt["comparison_product_id"], first["body_product_id"])
        self.assertEqual(self.rows(old_rebuilt)[0]["change"], "unchanged")
        self.assertEqual(latest_rebuilt["parent_body_product_id"], old_rebuilt["body_product_id"])
        self.assertEqual(latest_rebuilt["comparison_product_id"], second["body_product_id"])
        self.assertEqual(self.rows(latest_rebuilt)[0]["change"], "unchanged")
        self.assertEqual(replay["body_product_id"], old_rebuilt["body_product_id"])
        self.assertEqual(products.body_products(self.repository, verify=False)[-1]["body_product_id"], latest_rebuilt["body_product_id"])
        self.assertTrue(all(path.read_bytes() == data for path, data in before.items()))
        forged = deepcopy(old_rebuilt); forged.pop("status")
        forged["comparison_product_id"] = second["body_product_id"]
        core = {key: value for key, value in forged.items() if key not in {"body_product_id", "release_tag"}}
        core["bundle"] = {key: value for key, value in core["bundle"].items() if key != "url"}
        identity = hashlib.sha256(canonical(core, newline=True)).hexdigest()
        forged.update(body_product_id=identity, release_tag="bodies-" + identity)
        forged["bundle"]["url"] = f'https://github.com/{forged["repository"]}/releases/download/{forged["release_tag"]}/bodies.tar.gz'
        destination = self.root / "forged-future/body-products" / identity; destination.mkdir(parents=True)
        (destination / "receipt.json").write_bytes(canonical(forged, newline=True))
        with self.assertRaisesRegex(ValueError, "comparison differs"):
            products.read_body_product(self.root / "forged-future", identity, ledger_repository=self.repository,
                artifacts=products.artifact_tree(self.repository, old_rebuilt))


if __name__ == "__main__":
    unittest.main()
