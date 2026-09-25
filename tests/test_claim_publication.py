"""Proposals retain their exact bytes, source bindings and checked Git provenance."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from law_history import later_claims as claims, publication
from law_history.claim_publication import checked_claims
from law_history.ledger import ingest
from law_history.operation_products import extract_operations, show_operations
from law_history.validation import canonical, file_hash, read_json
from test_later_claims import operation_fixture
import test_publication as git_fixtures


class ClaimPublicationTests(unittest.TestCase):
    setUp = git_fixtures.PublicationTests.setUp
    tearDown = git_fixtures.PublicationTests.tearDown
    git = git_fixtures.PublicationTests.git
    remote_head = git_fixtures.PublicationTests.remote_head
    publish = git_fixtures.PublicationTests.publish

    def test_publish_replay_and_supersession_preserve_proposed_claims_and_creation_receipts(self):
        source, release, _ = operation_fixture(self.root / "source", "2020-01-01T12:00:00+00:00")
        ingest(str(source), self.repository)
        product = extract_operations(self.repository, release["observation_id"], github_repository="fixture/history")
        row = show_operations(self.repository, "lov/2001-04-06-11", product["operation_product_id"])["occurrences"][0]
        act, operation = row["act"], row["operations"][0]
        target = {"operation_product_id": product["operation_product_id"], "refid": act["refid"],
            "source_occurrence_id": act["source_occurrence_id"], "subject": {"kind": "operation",
                "id": operation["operation_id"], "parsed_revision_id": act["parsed_revision_id"],
                "parsed_model_sha256": act["parsed_model_sha256"]}}
        history = claims.claim_history(self.repository, target)
        request = {"contract": claims.REQUEST, "target": target, "knowledge_cutoff": "2020-01-01T12:00:00+00:00",
            "supersedes": [history["current_claim_id"]], "method": claims.METHOD,
            "assertion": {"text": "Fixture proposal, not a legal finding.", "proposed_scope": "Fixture scope",
                "proposed_legal_valid_time": {"from": None, "until": None}},
            "evidence": [history["available_evidence_references"][0]]}
        first = claims.propose_claim(self.repository, request)["claim"]
        files, _ = checked_claims(self.repository)
        original = {name: (self.repository / name).read_bytes() for name in files}
        with patch.object(publication, "publish_bundle", side_effect=ValueError("Unverified public export")):
            with self.assertRaisesRegex(ValueError, "Unverified public export"):
                self.publish()
        self.assertEqual(self.remote_head(), self.initial)
        with patch.object(publication, "publish_bundle", return_value={"verification": "offline_release_fixture"}):
            result = self.publish()
        self.assertEqual(result["claim_publication_count"], 1)
        receipt = result["claim_publications"][0]
        self.assertEqual(receipt["claim_id"], first["claim_id"])
        self.assertEqual(receipt["creation_commit"], result["data_commit"])
        self.assertEqual(receipt["expected_git_parent"], self.initial)
        self.assertEqual(receipt["claim_status"], "proposed")
        self.assertFalse(receipt["reconstruction_eligibility"]["eligible"])
        for name, content in original.items():
            self.assertEqual(self.git("show", f"refs/heads/main:{name}", cwd=self.remote).encode("utf-8"), content)
        first_receipt = self.repository / "claim-publications" / (first["claim_id"] + ".json")
        receipt_bytes = first_receipt.read_bytes()
        with patch.object(publication, "publish_bundle", side_effect=AssertionError("Release replay is unnecessary")), \
             patch.object(claims, "read_operation_product", side_effect=AssertionError("Published claims must not requalify old releases")), \
             patch.object(claims, "artifact_tree", side_effect=AssertionError("Published claims must not read old bundles")):
            replay = self.publish()
            self.assertEqual(replay["status"], "already_published")
        with patch.object(publication, "publish_bundle", side_effect=AssertionError("Release replay is unnecessary")):
            later = deepcopy(request); later["supersedes"] = [first["claim_id"]]
            later["assertion"]["text"] = "A later fixture proposal."
            second = claims.propose_claim(self.repository, later)["claim"]
            before = self.remote_head()
            with patch.object(claims, "read_operation_product", side_effect=ValueError("New claim evidence unavailable")):
                with self.assertRaisesRegex(ValueError, "New claim evidence unavailable"):
                    self.publish()
            self.assertEqual(self.remote_head(), before)
            with patch.object(claims, "read_operation_product", wraps=claims.read_operation_product) as reader:
                appended = self.publish()
            self.assertEqual(reader.call_count, 1)
        self.assertEqual(appended["claim_publication_count"], 2)
        self.assertEqual(first_receipt.read_bytes(), receipt_bytes)
        self.assertTrue(all((self.repository / name).read_bytes() == content for name, content in original.items()))
        self.assertEqual(claims.claim_history(self.repository, target)["current_claim_id"], second["claim_id"])
        # A claim without its committed publication proof cannot use the shortcut.
        first_receipt.unlink()
        try:
            with patch.object(claims, "read_operation_product", side_effect=ValueError("Missing publication requires source")):
                with self.assertRaisesRegex(ValueError, "Missing publication requires source"):
                    checked_claims(self.repository)
        finally:
            first_receipt.write_bytes(receipt_bytes)
        name, content = next(iter(original.items()))
        (self.repository / name).unlink()
        try:
            with patch.object(claims, "read_operation_product", side_effect=AssertionError("Missing prefix must fail cheaply")):
                with self.assertRaisesRegex(ValueError, "missing retained records"):
                    checked_claims(self.repository)
        finally:
            (self.repository / name).write_bytes(content)
        (self.repository / name).write_bytes(content.replace(b"Fixture scope", b"Changed scope"))
        with patch.object(claims, "read_operation_product", side_effect=AssertionError("Tamper must fail cheaply")):
            with self.assertRaisesRegex(ValueError, "identity or canonical bytes changed"):
                self.publish()
        (self.repository / name).write_bytes(content)
        # A rewritten prior receipt cannot be accepted merely because the new head exists.
        first_receipt.write_bytes(canonical({**receipt, "claim_status": "established"}, newline=True))
        with self.assertRaisesRegex(ValueError, "provenance changed"):
            self.publish()


if __name__ == "__main__":
    unittest.main()
