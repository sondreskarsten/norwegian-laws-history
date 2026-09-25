"""Full input boundary, archive order, and atomic rejected-product checks."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from law_history.ledger import ingest
from law_history import operation_products as products
from law_history.validation import canonical, file_hash, loads
from test_consumer import fixture
from test_operations import evidence


class OperationProductTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="operation-product-test-")
        self.root = Path(self.temporary.name)
        self.repository = self.root / "history"
        path, self.receipt, _ = fixture(self.root / "input")
        ingest(str(path), self.repository)

    def tearDown(self):
        self.temporary.cleanup()

    def test_generator_identity_is_frozen_at_import_and_cannot_be_mutated(self):
        original = products.generator_identity()
        with patch.object(Path, "read_bytes", side_effect=AssertionError("Reopened edited generator source")):
            returned = products.generator_identity()
            returned["sources"]["operations.py"] = "f" * 64
            self.assertEqual(products.generator_identity(), original)

    def test_empty_inventory_still_has_verified_product_and_safe_replay(self):
        first = products.extract_operations(self.repository, self.receipt["observation_id"])
        self.assertEqual(first["counts"], {"acts": 0, "operations": 0, "claims": 0})
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in
                  (self.repository / "operation-products").rglob("*") if p.is_file()}
        self.assertEqual(products.extract_operations(self.repository, self.receipt["observation_id"])["status"], "already_present")
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})
        with self.assertRaisesRegex(ValueError, "parent changed"):
            products.extract_operations(self.repository, self.receipt["observation_id"], "none")
        shown = products.show_operations(self.repository, "lov/2024-01-01-1")
        self.assertEqual(shown["status"], "not_in_parsed_act_inventory")

    def test_rehashed_wrong_inventory_cannot_override_source_or_poison_chain(self):
        def malformed(snapshot, output, release, manifest, members):
            with products._gzip_writer(output / "acts/00000.jsonl.gz"):
                pass
            with products._gzip_writer(output / "index.jsonl.gz") as index:
                index.write(canonical({"ordinal": 0, "refid": "lov/2001-01-01-1", "source_occurrence_id": "a" * 64,
                    "parsed_revision_id": "b" * 64, "operations": 0, "shard": "acts/00000.jsonl.gz",
                    "record_sha256": "c" * 64}, newline=True))
            return {"acts": 1, "operations": 0, "claims": 1}, {}, ["acts/00000.jsonl.gz"]
        with patch.object(products, "_generate", malformed), self.assertRaisesRegex(ValueError, "counts differ from accepted"):
            products.extract_operations(self.repository, self.receipt["observation_id"])
        self.assertEqual(list((self.repository / "operation-products").iterdir()), [])
        self.assertFalse((self.repository / ".cache/operation-writer.lock").exists())

    def test_routine_catchup_fully_checks_only_new_products(self):
        first = products.extract_operations(self.repository, self.receipt["observation_id"])
        original_reader = products.read_operation_product
        with patch.object(products, "read_operation_product", wraps=original_reader) as verify, \
                patch.object(products, "read_observation", side_effect=AssertionError("Reopened old input")):
            replay = products.extract_all(self.repository)
        verify.assert_not_called()
        self.assertEqual(replay, [{**first, "status": "already_present"}])
        source, second, _ = fixture(self.root / "second", observed="2026-09-26T12:00:00+00:00")
        ingest(str(source), self.repository)
        with patch.object(products, "read_operation_product", wraps=original_reader) as verify:
            catchup = products.extract_all(self.repository)
        self.assertEqual([r["status"] for r in catchup], ["already_present", "accepted"])
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(verify.call_args.args[1], catchup[1]["operation_product_id"])
        self.assertEqual(catchup[1]["observation_id"], second["observation_id"])
        with patch.object(products, "read_operation_product", wraps=original_reader) as verify:
            products.extract_operations(self.repository, self.receipt["observation_id"])
        verify.assert_called_once_with(self.repository, first["operation_product_id"])

    def test_unavailable_unselected_release_does_not_block_pinned_query(self):
        from law_history import operation_transport
        first = products.extract_operations(self.repository, self.receipt["observation_id"])
        source, second, _ = fixture(self.root / "second", observed="2026-09-26T12:00:00+00:00")
        ingest(str(source), self.repository)
        later = products.extract_operations(self.repository, second["observation_id"])
        cache = self.repository / ".cache/operation-artifacts" / later["operation_product_id"]
        cache.rename(self.root / "unavailable-later-artifacts")
        original_reader = products.read_operation_product
        with patch.object(operation_transport, "ensure_bundle", side_effect=ValueError("Unselected release unavailable")) as download, \
                patch.object(products, "read_operation_product", wraps=original_reader) as verify:
            shown = products.show_operations(self.repository, "lov/2024-01-01-1", first["operation_product_id"])
            self.assertEqual(shown["operation_product_id"], first["operation_product_id"])
            verify.assert_called_once_with(self.repository, first["operation_product_id"])
            download.assert_not_called()
            with self.assertRaisesRegex(ValueError, "Unselected release unavailable"):
                products.operation_products(self.repository)

    def test_explicit_replay_still_rejects_corrupt_artifacts(self):
        first = products.extract_operations(self.repository, self.receipt["observation_id"])
        path = self.repository / ".cache/operation-artifacts" / first["operation_product_id"] / "index.jsonl.gz"
        path.write_bytes(b"corrupt artifact")
        with self.assertRaisesRegex(ValueError, "artifact bytes changed"):
            products.extract_operations(self.repository, self.receipt["observation_id"])

    def test_nonempty_records_bind_identity_source_clocks_and_unresolved_scope(self):
        for changed in (None, "refid", "act_id", "historical_time", "observed_at", "source_date",
                        "publication_time", "claim_scope", "claim_target", "expression_scope"):
            with self.subTest(changed=changed):
                inputs = evidence()
                row = products.extract_act(**inputs)
                if changed == "refid": row["act"]["refid"] = "lov/2001-04-06-12"
                if changed == "act_id": row["operations"][0]["act_id"] = "f" * 64
                if changed == "historical_time":
                    row["act"]["clocks"]["historical_knowledge_time"] = {"status": "known", "at": "2001-04-06T00:00:00Z"}
                if changed == "observed_at": row["act"]["clocks"]["observed_at"] = "2001-04-06T00:00:00Z"
                if changed == "source_date": row["act"]["clocks"]["source_date_in_force"] = "2001-04-06"
                if changed == "publication_time":
                    row["act"]["clocks"]["release_publication"] = {"status": "known", "assertion": "2001-04-06"}
                if changed == "claim_scope": row["claims"][0]["expression_scope_assignment"] = "resolved"
                if changed == "claim_target": row["claims"][1]["target_resolution_status"] = "resolved"
                if changed == "expression_scope": row["act"]["commencement_expressions"][0]["legal_scope_status"] = "resolved"
                for claim in row["claims"]:
                    claim["clocks"] = row["act"]["clocks"]
                    claim["claim_id"] = products._identity(products.CLAIM_VERSION,
                        {key: value for key, value in claim.items() if key != "claim_id"})
                root = self.root / (changed or "valid"); root.mkdir()
                name = "acts/00000.jsonl.gz"
                with products._gzip_writer(root / name) as stream:
                    stream.write(canonical(row, newline=True))
                act = row["act"]
                receipt = {**act["context"], "parsed_acts_sha256": act["parsed_evidence"]["artifact_sha256"],
                           "knowledge_cutoff": act["clocks"]["knowledge_cutoff"], "shards": [name],
                           "counts": {"acts": 1, "operations": 3, "claims": 4}}
                index = [{"shard": name, "record_sha256": products._sha(canonical(row, newline=True)),
                          "refid": act["refid"], "source_occurrence_id": act["source_occurrence_id"],
                          "parsed_revision_id": act["parsed_revision_id"], "operations": 3}]
                if changed:
                    with self.assertRaisesRegex(ValueError, "binding changed|identity/status changed|source clocks|unsupported interpretation"):
                        products._verify_records(root, receipt, index, [inputs["member"]], loads(inputs["source_observation_bytes"]))
                else:
                    products._verify_records(root, receipt, index, [inputs["member"]], loads(inputs["source_observation_bytes"]))

    def test_empty_shard_cannot_satisfy_nonempty_index(self):
        with products._gzip_writer(self.root / "empty.jsonl.gz"):
            pass
        receipt = {"shards": ["empty.jsonl.gz"], "counts": {"acts": 1, "operations": 0, "claims": 1}}
        with self.assertRaisesRegex(ValueError, "shard counts"):
            products._verify_records(self.root, receipt, [{"shard": "empty.jsonl.gz"}], [{}], {})

    def test_declared_prefix_order_overrides_interleaved_tar_order(self):
        archive = self.root / "raw/test.tar.bz2"
        archive.parent.mkdir()
        paths = ["2001/nl-a.xml", "2001/sf-b.xml", "2001/nl-c.xml"]
        with tarfile.open(archive, "w:bz2") as stream:
            for name in paths:
                data = name.encode(); info = tarfile.TarInfo(name); info.size = len(data)
                stream.addfile(info, io.BytesIO(data))
        sha = file_hash(archive)
        members = [{"archive_ordinal": 0, "member_ordinal": i, "member_path": name,
                    "member_size_bytes": len(name.encode())} for i, name in enumerate(paths)]
        source = canonical({"archives": [{"role": "amendment_acts", "archive_ordinal": 0,
            "archive_sha256": sha, "raw_path": "raw/test.tar.bz2", "prefixes": ["nl-", "sf-"]}]})
        found = list(products._ordered_sources(self.root, members, source))
        self.assertEqual([row[0]["member_ordinal"] for row in found], [0, 2, 1])
        self.assertEqual([raw for _, raw in found], [paths[i].encode() for i in (0, 2, 1)])


if __name__ == "__main__":
    unittest.main()
