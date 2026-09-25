"""Small synthetic contract fixtures; real release verification is recorded separately."""
from copy import deepcopy
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest

from law_history.ledger import ingest, raw_member, show_document
from law_history.validation import canonical, file_hash, value_hash


def fixture(directory, *, present=True, observed="2026-09-25T12:00:00+00:00", mutate=None, unsafe=False):
    directory.mkdir()
    xml = b'<main class="documentBody"><article>Retained exact source.</article></main>'
    model = {"refid": "lov/2024-01-01-1", "title": "Synthetic contract fixture"}
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w:bz2") as raw:
        if present:
            info = tarfile.TarInfo("nested/source.xml"); info.size = len(xml)
            raw.addfile(info, io.BytesIO(xml))
    archive_content = archive_bytes.getvalue()
    archive_sha = hashlib.sha256(archive_content).hexdigest()
    archive_path = f"raw/{archive_sha}.tar.bz2"
    artifacts = {archive_path: archive_content}
    model_path = "laws/lov-2024-01-01-1.json"
    if present:
        artifacts[model_path] = canonical(model, newline=True)
    database = directory / "amendments.db"
    conn = sqlite3.connect(database)
    conn.execute("CREATE TABLE amendment_acts (refid TEXT,amendment_count INTEGER)")
    conn.execute("CREATE TABLE amendments (id INTEGER,act_refid TEXT)")
    conn.commit(); conn.close()
    artifacts["amendments.db"] = database.read_bytes()
    parser_files = {key: "a" * 64 for key in ("parser.py", "models.py", "evidence.py")}
    observation = {"schema_version": "lovdata-source-evidence-v1", "parser_identity": {
        "package_version": "fixture", "source_files": parser_files, "sha256": value_hash(parser_files)},
        "parser_runtime": {"python_implementation": "CPython", "python_version": "3.12.0", "html_backend": "html.parser",
                           "dependencies": {"beautifulsoup4": None, "soupsieve": None, "lxml": None}, "unknown_dependency_version": None},
        "knowledge_cutoff": observed, "knowledge_cutoff_basis": "local_archive_observation",
        "historical_knowledge_time_status": "unknown", "structural_coverage_status": "not_verified",
        "source_attribution": "Lovdata public data; NLOD 2.0",
        "archives": [{"archive_ordinal": 0, "archive_sha256": archive_sha, "raw_path": archive_path,
                      "size_bytes": len(archive_content), "role": "laws", "prefixes": [],
                      "original_filename": "fixture.tar.bz2", "observed_at": observed,
                      "retrieved_at": None, "retrieval_time_status": "unknown", "historical_knowledge_time_status": "unknown",
                      "source_url": None, "source_last_modified": None, "member_count": int(present), "parsed_occurrence_count": int(present)}]}
    member_sha = hashlib.sha256(xml).hexdigest()
    member = {"archive_ordinal": 0, "archive_sha256": archive_sha, "role": "laws", "member_ordinal": 0,
              "member_path": "nested/source.xml", "member_type": "file", "member_size_bytes": len(xml),
              "member_sha256": member_sha, "parse_status": "parsed", "refid": model["refid"],
              "parsed_occurrence_ordinal": 0, "parsed_model_sha256": value_hash(model),
              "source_occurrence_id": value_hash([0, archive_sha, 0, "nested/source.xml", member_sha, "laws"]),
              "selected": True, "selected_output_path": model_path,
              "selected_output_sha256": hashlib.sha256(artifacts.get(model_path, b"")).hexdigest()}
    artifacts["source-observations.json"] = canonical(observation, newline=True)
    artifacts["source-members.jsonl"] = canonical(member, newline=True) if present else b""
    artifacts["parsed-amendment-acts.v1.jsonl"] = b""
    manifest = {"version": 4, "content_version": "legacy-paragraphs-v1", "formatter_version": "law-markdown-v1",
                "law_count": int(present), "forskrift_count": 0, "amendment_act_count": 0, "amendment_count": 0,
                "duplicate_policy": "last-occurrence-wins", "duplicate_counts": {"laws": 0, "forskrifter": 0, "amendment_acts": 0},
                "evidence": {"version": "lovdata-source-evidence-v1", "observations": "source-observations.json",
                             "members": "source-members.jsonl", "parsed_amendments": "parsed-amendment-acts.v1.jsonl",
                             "archive_count": 1, "member_count": int(present), "unresolved_member_count": 0,
                             "parsed_occurrence_counts": {"laws": int(present), "forskrifter": 0, "amendment_acts": 0}, "parsed_amendment_count": 0}}
    if mutate:
        mutate(manifest, artifacts)
    manifest["artifact_hashes"] = {name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()}
    artifacts["manifest.json"] = canonical(manifest, newline=True)
    bundle = directory / "snapshot.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        for name, data in sorted(artifacts.items()):
            info = tarfile.TarInfo(name); info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if unsafe:
            info = tarfile.TarInfo("unsafe"); info.type = tarfile.SYMTYPE; info.linkname = "../outside"
            tar.addfile(info)
    receipt = {"version": 1, "contract": "lovdata-observation-release-v1", "repository": "fixture/evidence",
               "source_sha": "b" * 40, "snapshot_version": 4,
               "snapshot_manifest_sha256": hashlib.sha256(artifacts["manifest.json"]).hexdigest(),
               "bundle": {"name": "snapshot.tar.gz", "sha256": file_hash(bundle), "bytes": bundle.stat().st_size},
               "member_count": len(artifacts) + int(unsafe),
               "data_attribution": {"provider": "Lovdata", "license": "NLOD 2.0", "license_url": "https://data.norge.no/nlod/no/2.0"},
               "interpretation": "Synthetic contract fixture, not legal source evidence"}
    identity = hashlib.sha256(canonical(receipt, newline=True)).hexdigest()
    receipt.update(observation_id=identity, release_tag="observation-" + identity)
    base = f'https://github.com/fixture/evidence/releases/download/{receipt["release_tag"]}/'
    receipt["bundle"]["url"] = base + "snapshot.tar.gz"; receipt["receipt_url"] = base + "evidence.json"
    path = directory / "evidence.json"; path.write_bytes(canonical(receipt, newline=True))
    return path, receipt, xml


class ConsumerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="history-consumer-test-")
        self.root = Path(self.temp.name); self.ledger = self.root / "ledger"

    def tearDown(self):
        self.temp.cleanup()

    def test_replay_preserves_prior_source_and_observed_absence(self):
        path, receipt, xml = fixture(self.root / "first")
        self.assertEqual(ingest(str(path), self.ledger)["status"], "accepted")
        before = {p.relative_to(self.ledger): p.read_bytes() for p in (self.ledger / "observations").rglob("*") if p.is_file()}
        self.assertEqual(ingest(str(path), self.ledger)["status"], "already_present")
        self.assertEqual(before, {p.relative_to(self.ledger): p.read_bytes() for p in (self.ledger / "observations").rglob("*") if p.is_file()})
        second, _, _ = fixture(self.root / "second", present=False, observed="2026-09-26T12:00:00+00:00")
        ingest(str(second), self.ledger)
        shown = show_document(self.ledger, "lov/2024-01-01-1")
        self.assertEqual([row["status"] for row in shown["observations"]], ["present", "not_present_in_observation"])
        self.assertEqual(shown["legal_valid_time"]["status"], "unresolved")
        self.assertEqual(raw_member(self.ledger, receipt["observation_id"], "lov/2024-01-01-1"), xml)

    def test_changed_identity_payload_or_derived_url_is_rejected(self):
        path, receipt, _ = fixture(self.root / "first")
        ingest(str(path), self.ledger)
        for change in (lambda r: r.update(interpretation="changed"), lambda r: r["bundle"].update(url="https://example.com/wrong")):
            altered = deepcopy(receipt); change(altered); path.write_bytes(canonical(altered))
            with self.assertRaises(ValueError):
                ingest(str(path), self.ledger)
        self.assertEqual(len(list((self.ledger / "observations").iterdir())), 1)

    def test_changed_source_scope_is_unknown_not_observed_absence(self):
        first, _, _ = fixture(self.root / "first")
        ingest(str(first), self.ledger)
        def different_scope(manifest, artifacts):
            observation = json.loads(artifacts["source-observations.json"])
            observation["archives"][0]["original_filename"] = "different-selection.tar.bz2"
            artifacts["source-observations.json"] = canonical(observation, newline=True)
        second, _, _ = fixture(self.root / "second", present=False,
                               observed="2026-09-26T12:00:00+00:00", mutate=different_scope)
        ingest(str(second), self.ledger)
        shown = show_document(self.ledger, "lov/2024-01-01-1")["observations"][-1]
        self.assertEqual(shown["status"], "scope_not_comparable")
        self.assertFalse(shown["scope_comparable"])

    def test_corrupt_bundle_and_link_member_fail_before_acceptance(self):
        for unsafe in (False, True):
            path, _, _ = fixture(self.root / str(unsafe), unsafe=unsafe)
            if not unsafe:
                with (path.parent / "snapshot.tar.gz").open("ab") as stream: stream.write(b"corrupt")
            with self.assertRaises(ValueError): ingest(str(path), self.ledger)
        self.assertEqual(list((self.ledger / "observations").iterdir()), [])

    def test_rehashed_member_binding_and_count_fail_preserving_prior_observation(self):
        path, _, _ = fixture(self.root / "good"); ingest(str(path), self.ledger)
        def bad_member(manifest, artifacts):
            row = json.loads(artifacts["source-members.jsonl"]); row["member_sha256"] = "0" * 64
            artifacts["source-members.jsonl"] = canonical(row, newline=True)
        def bad_count(manifest, artifacts): manifest["law_count"] = 2
        def extra(manifest, artifacts): artifacts["unexpected.txt"] = b"not part of the contract"
        for i, mutation in enumerate((bad_member, bad_count, extra)):
            path, _, _ = fixture(self.root / f"bad{i}", mutate=mutation)
            with self.assertRaises(ValueError): ingest(str(path), self.ledger)
        self.assertEqual(len(list((self.ledger / "observations").iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
