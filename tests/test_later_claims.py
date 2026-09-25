"""Real accepted snapshots/products plus a controlled clock; no network or Git writes."""
from copy import deepcopy
import io
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from law_history import later_claims as claims
from law_history.ledger import ingest
from law_history.operation_products import extract_operations, show_operations
from law_history.validation import canonical, file_hash, loads, value_hash
from test_consumer import fixture
from test_operations import SOURCE, evidence


def operation_fixture(directory, observed, raw=SOURCE):
    def mutate(manifest, artifacts):
        archive_buffer = io.BytesIO()
        member_path = "acts/nl-source.xml"
        with tarfile.open(fileobj=archive_buffer, mode="w:bz2") as stream:
            info = tarfile.TarInfo(member_path); info.size = len(raw)
            stream.addfile(info, io.BytesIO(raw))
        archive_bytes = archive_buffer.getvalue()
        archive_sha = claims.hashlib.sha256(archive_bytes).hexdigest()
        archive_path = f"raw/{archive_sha}.tar.bz2"
        artifacts[archive_path] = archive_bytes
        envelope = evidence(observed=observed, raw=raw)["envelope"]
        envelope["record"]["filename"] = "nl-source.xml"
        member_sha = claims.hashlib.sha256(raw).hexdigest()
        occurrence = value_hash([1, archive_sha, 0, member_path, member_sha, "amendment_acts"])
        envelope["source_occurrence_id"] = occurrence
        connection = sqlite3.connect(directory / "amendments.db")
        connection.execute("INSERT INTO amendment_acts VALUES (?,3)", (envelope["record"]["refid"],))
        connection.executemany("INSERT INTO amendments VALUES (?,?)", [(n, envelope["record"]["refid"]) for n in range(3)])
        connection.commit(); connection.close()
        artifacts["amendments.db"] = (directory / "amendments.db").read_bytes()
        member = {"archive_ordinal": 1, "archive_sha256": archive_sha, "role": "amendment_acts",
                  "member_ordinal": 0, "member_path": member_path, "member_type": "file", "member_size_bytes": len(raw),
                  "member_sha256": member_sha, "parse_status": "parsed", "refid": envelope["record"]["refid"],
                  "parsed_occurrence_ordinal": 0, "parsed_model_sha256": value_hash(envelope["record"]),
                  "source_occurrence_id": occurrence, "selected": True, "selected_output_path": "amendments.db",
                  "selected_output_sha256": claims.hashlib.sha256(artifacts["amendments.db"]).hexdigest()}
        artifacts["source-members.jsonl"] += canonical(member, newline=True)
        artifacts["parsed-amendment-acts.v1.jsonl"] = canonical(envelope, newline=True)
        source = loads(artifacts["source-observations.json"])
        source["archives"].append({"archive_ordinal": 1, "archive_sha256": archive_sha, "raw_path": archive_path,
            "size_bytes": len(archive_bytes), "role": "amendment_acts", "prefixes": ["nl-", "sf-"],
            "original_filename": "fixture-acts.tar.bz2", "observed_at": observed, "retrieved_at": None,
            "retrieval_time_status": "unknown", "historical_knowledge_time_status": "unknown",
            "source_url": None, "source_last_modified": None, "member_count": 1, "parsed_occurrence_count": 1})
        artifacts["source-observations.json"] = canonical(source, newline=True)
        manifest.update(amendment_act_count=1, amendment_count=3)
        manifest["evidence"].update(archive_count=2, member_count=2, parsed_amendment_count=3)
        manifest["evidence"]["parsed_occurrence_counts"]["amendment_acts"] = 1
    return fixture(directory, observed=observed, mutate=mutate)


class LaterClaimTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="later-claims-test-")
        self.root = Path(self.temporary.name)
        self.repository = self.root / "history"
        self.product, self.row = self.product_at("first", "2026-09-25T12:00:00+00:00")
        act = self.row["act"]; operation = self.row["operations"][0]
        self.target = {"operation_product_id": self.product["operation_product_id"], "refid": act["refid"],
            "source_occurrence_id": act["source_occurrence_id"], "subject": {"kind": "operation", "id": operation["operation_id"],
                "parsed_revision_id": act["parsed_revision_id"], "parsed_model_sha256": act["parsed_model_sha256"]}}
        history = claims.claim_history(self.repository, self.target)
        self.request = {"contract": claims.REQUEST, "target": self.target, "knowledge_cutoff": "2026-09-26T12:00:00+00:00",
            "supersedes": [history["current_claim_id"]], "method": claims.METHOD,
            "assertion": {"text": "A proposed interpretation, not an established legal result.",
                "proposed_scope": "Proposed scope only", "proposed_legal_valid_time": {"from": "2001-04-06", "until": None}},
            "evidence": [next(r for r in history["available_evidence_references"] if r["kind"] == "commencement_candidate")]}

    def tearDown(self):
        self.temporary.cleanup()

    def product_at(self, label, observed, raw=SOURCE):
        receipt_path, receipt, _ = operation_fixture(self.root / label, observed, raw)
        ingest(str(receipt_path), self.repository)
        product = extract_operations(self.repository, receipt["observation_id"])
        row = show_operations(self.repository, "lov/2001-04-06-11", product["operation_product_id"])["occurrences"][0]
        return product, row

    def propose(self, request=None, now="2026-09-27T12:00:00+00:00"):
        with patch.object(claims, "_now", return_value=now):
            return claims.propose_claim(self.repository, request or self.request)

    def immutable_files(self):
        return {p.relative_to(self.repository).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for top in ("operation-products", ".cache/operation-artifacts", "later-claims")
                for p in (self.repository / top).rglob("*") if p.is_file()}

    def test_later_knowledge_appends_preserves_old_bytes_and_exposes_full_history(self):
        original = self.immutable_files()
        first = self.propose()["claim"]
        after_first = self.immutable_files()
        self.assertTrue(all(after_first[name] == content for name, content in original.items()))
        second_request = deepcopy(self.request)
        second_request.update(supersedes=[first["claim_id"]], knowledge_cutoff="2026-09-28T12:00:00+00:00")
        second_request["assertion"]["text"] = "Later reasoning changes the proposed interpretation."
        second = self.propose(second_request, "2026-09-29T12:00:00+00:00")["claim"]
        after_second = self.immutable_files()
        self.assertTrue(all(after_second[name] == content for name, content in after_first.items()))
        history = claims.claim_history(self.repository, self.target)
        self.assertEqual([c["claim_id"] for c in history["proposed_claim_history"]], [first["claim_id"], second["claim_id"]])
        self.assertEqual(history["current_proposal"], second)
        self.assertEqual(history["initial_unresolved_claim"], self.row["claims"][1])
        self.assertEqual(history["eligible_reconstruction_inputs"], [])
        self.assertEqual(history["registered_evidence_methods"], [])
        self.assertTrue(all(c["status"] == "proposed" and c["reconstruction_eligibility"]["eligible"] is False
                            for c in history["proposed_claim_history"]))
        replay = self.propose(now="2026-10-01T12:00:00+00:00")
        self.assertEqual(replay, {"status": "already_present", "claim": first})
        self.assertEqual(after_second, self.immutable_files())

    def test_wrong_source_subject_revision_parent_cutoffs_and_eligibility_reject_without_append(self):
        mutations = {
            "source": lambda r: r["target"].update(source_occurrence_id="f" * 64),
            "subject": lambda r: r["target"]["subject"].update(id="f" * 64),
            "revision": lambda r: r["target"]["subject"].update(parsed_revision_id="f" * 64),
            "model": lambda r: r["target"]["subject"].update(parsed_model_sha256="f" * 64),
            "parent": lambda r: r.update(supersedes=[self.row["claims"][2]["claim_id"]]),
            "source_cutoff": lambda r: r.update(knowledge_cutoff="2001-04-06T00:00:00+00:00"),
            "future_cutoff": lambda r: r.update(knowledge_cutoff="2031-01-01T00:00:00+00:00"),
            "missing_zone": lambda r: r.update(knowledge_cutoff="2026-09-26T12:00:00"),
            "injected_eligibility": lambda r: r.update(reconstruction_eligibility={"eligible": True}),
            "unregistered_method": lambda r: r.update(method="official-commencement-proved-v1"),
            "wrong_location": lambda r: r["evidence"][0]["location"].update(path="/invented[1]"),
            "wrong_evidence_source": lambda r: r["evidence"][0].update(source_occurrence_id="f" * 64),
        }
        before = self.immutable_files()
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                request = deepcopy(self.request); mutation(request)
                with self.assertRaises(ValueError): self.propose(request)
                self.assertEqual(before, self.immutable_files())

    def test_later_cross_product_evidence_is_pinned_and_cannot_precede_its_cutoff(self):
        product, row = self.product_at("later", "2026-09-28T12:00:00+00:00", SOURCE.replace(b"straks", b"1. januar 2027"))
        expression = next(item for item in row["act"]["commencement_expressions"] if "2027" in item["text"])
        self.assertNotEqual(row["act"]["source_occurrence_id"], self.row["act"]["source_occurrence_id"])
        reference = {"operation_product_id": product["operation_product_id"], "refid": row["act"]["refid"],
            "source_occurrence_id": row["act"]["source_occurrence_id"], "kind": "commencement_candidate",
            "expression_id": expression["expression_id"], "location": expression["source"]}
        request = deepcopy(self.request); request["evidence"].append(reference)
        with self.assertRaisesRegex(ValueError, "precedes cited evidence"):
            self.propose(request)
        request["knowledge_cutoff"] = "2026-09-29T12:00:00+00:00"
        original_reader = claims.read_operation_product
        with patch.object(claims, "read_operation_product", wraps=original_reader) as reader:
            record = self.propose(request, "2026-09-30T12:00:00+00:00")["claim"]
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(record["target_binding"]["operation_product_id"], self.product["operation_product_id"])
        self.assertEqual(record["evidence_bindings"][1]["reference"], reference)
        self.assertFalse(record["reconstruction_eligibility"]["eligible"])

    def test_stale_supersedes_and_regressing_later_cutoff_reject(self):
        first = self.propose()["claim"]
        stale = deepcopy(self.request); stale["assertion"]["text"] = "Different stale proposal"
        with self.assertRaisesRegex(ValueError, "current claim"): self.propose(stale)
        stale["supersedes"] = [first["claim_id"]]
        stale["knowledge_cutoff"] = "2026-09-25T13:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "cutoff regresses"): self.propose(stale)

    def test_act_and_operation_have_separate_initial_claim_chains(self):
        request = deepcopy(self.request)
        request["target"]["subject"].update(kind="act", id=self.row["act"]["act_id"])
        request["supersedes"] = [self.row["claims"][0]["claim_id"]]
        act_claim = self.propose(request)["claim"]
        operation_claim = self.propose()["claim"]
        self.assertNotEqual(act_claim["claim_id"], operation_claim["claim_id"])
        self.assertEqual(claims.claim_history(self.repository, request["target"])["current_claim_id"], act_claim["claim_id"])
        self.assertEqual(claims.claim_history(self.repository, self.target)["current_claim_id"], operation_claim["claim_id"])

    def test_existing_writer_lock_rejects_without_touching_export_or_claims(self):
        directory = claims._path(self.repository, self.target)
        lock = self.repository / ".cache" / ("later-claim-" + directory.parent.name + "-" + directory.name + ".lock")
        lock.write_bytes(b"Existing writer")
        before = self.immutable_files()
        with self.assertRaisesRegex(ValueError, "writer lock exists"):
            self.propose()
        self.assertEqual(before, self.immutable_files())
        self.assertEqual(lock.read_bytes(), b"Existing writer")

    def test_rehashed_stored_promotion_and_fork_are_rejected(self):
        record = self.propose()["claim"]
        path = claims._path(self.repository, self.target) / (record["claim_id"] + ".json")
        original = path.read_bytes()
        changed = deepcopy(record); changed["reconstruction_eligibility"]["eligible"] = True
        core = {k: v for k, v in changed.items() if k != "claim_id"}
        changed["claim_id"] = claims._identity(claims.CONTRACT, core)
        other = path.with_name(changed["claim_id"] + ".json")
        path.rename(self.root / "retained-original.json"); other.write_bytes(canonical(changed, newline=True))
        with self.assertRaisesRegex(ValueError, "cannot become eligible"):
            claims.claim_history(self.repository, self.target)
        other.rename(self.root / "rejected-promotion.json"); path.write_bytes(original)
        changed = deepcopy(record); changed["request"]["assertion"]["text"] = "Conflicting sibling proposal"
        changed["request_id"] = claims._identity(claims.REQUEST, changed["request"])
        changed["claim_id"] = claims._identity(claims.CONTRACT, {k: v for k, v in changed.items() if k != "claim_id"})
        path.with_name(changed["claim_id"] + ".json").write_bytes(canonical(changed, newline=True))
        with self.assertRaisesRegex(ValueError, "forked"):
            claims.claim_history(self.repository, self.target)

    def test_standalone_cli_proposes_and_reads_history(self):
        request = deepcopy(self.request)
        request["knowledge_cutoff"] = "2026-09-25T12:00:00+00:00"
        request_path = self.root / "request.json"; request_path.write_bytes(canonical(request, newline=True))
        target_path = self.root / "target.json"; target_path.write_bytes(canonical(self.target, newline=True))
        result = subprocess.run([sys.executable, "-m", "law_history.later_claims", "--repository", str(self.repository),
                                 "propose", str(request_path)], capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        accepted = loads(result.stdout)
        self.assertEqual(accepted["status"], "accepted_proposal")
        result = subprocess.run([sys.executable, "-m", "law_history.later_claims", "--repository", str(self.repository),
                                 "history", str(target_path)], capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(loads(result.stdout)["current_proposal"]["claim_id"], accepted["claim"]["claim_id"])


if __name__ == "__main__":
    unittest.main()
