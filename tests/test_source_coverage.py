from pathlib import Path
import tempfile
import unittest

from law_history.ledger import ingest
from law_history.source_coverage import source_coverage
from test_consumer import fixture


class SourceCoverageTests(unittest.TestCase):
    def test_retained_source_is_not_a_historical_baseline_and_cutoff_excludes_future(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "ledger"
            first, receipt, _ = fixture(root / "first")
            ingest(str(first), repository)
            second, _, _ = fixture(root / "second", observed="2026-09-26T12:00:00+00:00", present=False)
            ingest(str(second), repository)
            result = source_coverage(repository, "lov/2024-01-01-1", "2026-09-25T13:00:00Z")
            self.assertEqual(len(result["inputs"]), 1)
            row = result["documents"][0]
            self.assertEqual(row["current_corpus_observations"], [receipt["observation_id"]])
            self.assertEqual(row["original_text_candidate"], "not_found_in_accepted_catalogs")
            self.assertIsNone(row["historical_coverage"]["justified_baseline"])
            self.assertEqual(row["historical_coverage"]["supported_legal_intervals"], [])
            self.assertEqual(source_coverage(repository, known_at="2000-01-01T00:00:00Z")["documents"], [])
            self.assertEqual(len(source_coverage(repository)["inputs"]), 2)

    def test_invalid_cutoff_and_changed_accepted_catalog_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); repository = root / "ledger"
            first, receipt, _ = fixture(root / "first")
            ingest(str(first), repository)
            with self.assertRaises(ValueError):
                source_coverage(repository, known_at="2026-09-25")
            catalog = repository / "observations" / receipt["observation_id"] / "members.jsonl"
            with catalog.open("ab") as stream:
                stream.write(b"\n")
            with self.assertRaisesRegex(ValueError, "changed"):
                source_coverage(repository)
