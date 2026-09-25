"""Consumer upgrades must not become implicit historical re-extraction requests."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from law_history.ledger import ingest
from law_history import operation_products as products
from test_consumer import fixture


class CatchupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="catchup-review-")
        self.root = Path(self.temporary.name)
        self.repository = self.root / "history"
        path, self.receipt, _ = fixture(self.root / "source")
        ingest(str(path), self.repository)
        self.first = products.extract_operations(self.repository, self.receipt["observation_id"])
        self.upgrade = deepcopy(products.generator_identity())
        self.upgrade["sources"]["validation.py"] = "d" * 64

    def tearDown(self):
        self.temporary.cleanup()

    def test_validator_upgrade_reuses_existing_without_old_input_or_artifact_reads(self):
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in (self.repository / "operation-products").rglob("*") if p.is_file()}
        with patch.object(products, "generator_identity", return_value=self.upgrade), \
                patch.object(products, "read_observation", side_effect=AssertionError("Reopened old input")), \
                patch.object(products, "read_operation_product", side_effect=AssertionError("Rehydrated old product")):
            result = products.extract_all(self.repository)
        self.assertEqual(result, [{**self.first, "status": "already_present"}])
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})

    def test_explicit_upgrade_appends_and_routine_catchup_reuses_latest_representation(self):
        old_path = self.repository / "operation-products" / self.first["operation_product_id"] / "receipt.json"
        old_bytes = old_path.read_bytes()
        with patch.object(products, "generator_identity", return_value=self.upgrade):
            updated = products.extract_operations(self.repository, self.receipt["observation_id"])
        self.assertEqual(updated["status"], "accepted")
        self.assertEqual(updated["parent_operation_product_id"], self.first["operation_product_id"])
        self.assertEqual(updated["generator"], self.upgrade)
        self.assertEqual(old_path.read_bytes(), old_bytes)
        # Even a return to the older code must not silently replace the newer
        # intentionally appended representation during routine catch-up.
        with patch.object(products, "read_operation_product", side_effect=AssertionError("Rehydrated old product")):
            self.assertEqual(products.extract_all(self.repository), [{**updated, "status": "already_present"}])

    def test_new_observation_and_other_destination_are_not_skipped(self):
        path, second, _ = fixture(self.root / "second", observed="2026-09-26T12:00:00+00:00")
        ingest(str(path), self.repository)
        reader = products.read_operation_product
        with patch.object(products, "generator_identity", return_value=self.upgrade), \
                patch.object(products, "read_operation_product", wraps=reader) as verified:
            result = products.extract_all(self.repository)
        self.assertEqual([r["status"] for r in result], ["already_present", "accepted"])
        self.assertEqual(verified.call_count, 1)
        self.assertEqual(result[1]["observation_id"], second["observation_id"])
        other = products.extract_operations(self.repository, self.receipt["observation_id"],
            github_repository="fixture/another-history", reuse_existing_observation=True)
        self.assertEqual(other["status"], "accepted")
        self.assertEqual(other["repository"], "fixture/another-history")


if __name__ == "__main__":
    unittest.main()
