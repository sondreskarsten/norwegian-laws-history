"""Receipt-to-source verification of the explicit source-body snapshot contract."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from law_history.ledger import ingest, raw_member
from law_history.source_body_gate import qualify_source_body
from law_history.validation import canonical, value_hash, SOURCE_BODY_CONTRACT
from test_consumer import fixture, bind_model

XML = (b'<html lang="nb"><head><base href="https://lovdata.no/"/></head><body>'
       b'<header><dl><dd class="refid">lov/2024-01-01-1</dd></dl></header>'
       b'<main class="documentBody" data-lovdata-URL="NL/lov/2024-01-01-1">'
       b'<article class="legalP">First <i>important</i> text.</article>'
       b'<article class="legalP">Second.</article></main></body></html>')


def body_model():
    context = {"html_lang": "nb", "html_attributes": {"lang": "nb"}, "head_attributes": {},
               "body_attributes": {}, "source_base": "https://lovdata.no/", "refid": "lov/2024-01-01-1"}
    root = {"tag": "main", "attributes": {"class": "documentBody", "data-lovdata-URL": "NL/lov/2024-01-01-1"},
            "children": [
                {"tag": "article", "attributes": {"class": "legalP"}, "children": ["First ",
                    {"tag": "i", "attributes": {}, "children": ["important"]}, " text."]},
                {"tag": "article", "attributes": {"class": "legalP"}, "children": ["Second."]}]}
    model = {"contract": SOURCE_BODY_CONTRACT[0], "member_sha256": hashlib.sha256(XML).hexdigest(),
             "context": context, "root": root}
    rehash(model)
    return model


def rehash(model):
    model["body_sha256"] = value_hash(model["root"])
    model["semantic_sha256"] = value_hash([model["contract"], model["context"], model["root"]])


def bind_v5(manifest, artifacts, body=None):
    bind_model(manifest, artifacts, {"source_body": body_model() if body is None else body})
    manifest.update(version=5, content_version=SOURCE_BODY_CONTRACT[0], formatter_version=SOURCE_BODY_CONTRACT[1])
    observation = json.loads(artifacts["source-observations.json"])
    parser = observation["parser_identity"]
    parser["source_files"]["source_body.py"] = "c" * 64
    parser["sha256"] = value_hash(parser["source_files"])
    artifacts["source-observations.json"] = canonical(observation, newline=True)


class SourceBodySnapshotTests(unittest.TestCase):
    def test_ingestion_checks_raw_body_and_preserves_legacy_observations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); ledger = root / "ledger"
            first, _, _ = fixture(root / "old")
            ingest(str(first), ledger)
            before = {p: p.read_bytes() for p in (ledger / "observations").rglob("*") if p.is_file()}
            source, receipt, raw = fixture(root / "new", raw_xml=XML, mutate=bind_v5)
            self.assertEqual(ingest(str(source), ledger)["status"], "accepted")
            self.assertEqual(raw_member(ledger, receipt["observation_id"], "lov/2024-01-01-1"), raw)
            self.assertTrue(all(p.read_bytes() == data for p, data in before.items()))
            self.assertEqual(ingest(str(source), ledger)["status"], "already_present")

    def test_rehashed_body_mutations_fail_before_acceptance(self):
        def swap(body): body["root"]["children"].reverse()
        def tail(body): body["root"]["children"][0]["children"][-1] = " changed."
        def attr(body): body["root"]["children"][0]["attributes"]["class"] = "defaultP"
        def context(body): body["context"]["body_attributes"]["dir"] = "rtl"
        def raw_digest(body): body["member_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); ledger = root / "ledger"
            for i, mutate in enumerate((swap, tail, attr, context, raw_digest)):
                body = body_model(); mutate(body); rehash(body)
                path, _, _ = fixture(root / str(i), raw_xml=XML,
                    mutate=lambda m, a: bind_v5(m, a, body))
                with self.subTest(case=mutate.__name__), self.assertRaises(ValueError):
                    ingest(str(path), ledger)
            self.assertEqual(list((ledger / "observations").iterdir()), [])

    def test_contract_downgrade_missing_capture_and_wrong_parser_identity_fail(self):
        def wrong_contract(m, a):
            bind_v5(m, a); m["version"] = 4
        def missing_capture(m, a):
            bind_v5(m, a)
            name = "laws/lov-2024-01-01-1.json"
            model = json.loads(a[name]); model.pop("source_body")
            a[name] = canonical(model, newline=True)
            member = json.loads(a["source-members.jsonl"])
            member["parsed_model_sha256"] = value_hash(model)
            member["selected_output_sha256"] = hashlib.sha256(a[name]).hexdigest()
            a["source-members.jsonl"] = canonical(member, newline=True)
        def wrong_parser(m, a):
            bind_v5(m, a)
            obs = json.loads(a["source-observations.json"])
            obs["parser_identity"]["source_files"].pop("source_body.py")
            obs["parser_identity"]["sha256"] = value_hash(obs["parser_identity"]["source_files"])
            a["source-observations.json"] = canonical(obs, newline=True)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for i, mutate in enumerate((wrong_contract, missing_capture, wrong_parser)):
                source, _, _ = fixture(root / str(i), raw_xml=XML, mutate=mutate)
                with self.subTest(case=mutate.__name__), self.assertRaises(ValueError):
                    ingest(str(source), root / "ledger")

    def test_reidentified_receipt_cannot_disagree_with_snapshot_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, receipt, _ = fixture(root / "source", raw_xml=XML, mutate=bind_v5)
            receipt["snapshot_version"] = 4
            core = {k: v for k, v in receipt.items() if k not in {"observation_id", "release_tag", "receipt_url"}}
            core["bundle"] = {k: v for k, v in core["bundle"].items() if k != "url"}
            identity = hashlib.sha256(canonical(core, newline=True)).hexdigest()
            receipt.update(observation_id=identity, release_tag="observation-" + identity)
            base = f'https://github.com/fixture/evidence/releases/download/{receipt["release_tag"]}/'
            receipt["receipt_url"] = base + "evidence.json"
            receipt["bundle"]["url"] = base + "snapshot.tar.gz"
            path.write_bytes(canonical(receipt, newline=True))
            with self.assertRaisesRegex(ValueError, "Receipt/snapshot version mismatch"):
                ingest(str(path), root / "ledger")

    def test_unsupported_inherited_context_is_retained_but_not_rendered(self):
        raw = XML.replace(b'<body>', b'<body dir="rtl">')
        body = body_model(); body["context"]["body_attributes"] = {"dir": "rtl"}
        body["member_sha256"] = hashlib.sha256(raw).hexdigest(); rehash(body)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, _, _ = fixture(root / "source", raw_xml=raw, mutate=lambda m, a: bind_v5(m, a, body))
            self.assertEqual(ingest(str(path), root / "ledger")["status"], "accepted")
            result = qualify_source_body(raw, body, expected_member_sha256=body["member_sha256"],
                expected_refid="lov/2024-01-01-1", source_occurrence_id="a" * 64)
            self.assertEqual(result["report"]["status"], "rejected")
            self.assertEqual(result["report"]["reasons"][0]["code"], "unsupported_context")
            self.assertIsNone(result["html"])


if __name__ == "__main__":
    unittest.main()
