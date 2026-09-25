"""Checked parent/replay/quarantine behavior; real qualified outputs have separate readback evidence."""
from pathlib import Path
import tempfile
import unittest

from test_consumer import fixture
from law_history.ledger import ingest
from law_history.materialize import materialize, materializations, read_materialization
from law_history.validation import file_hash


class MaterializationTests(unittest.TestCase):
    def test_real_bound_fixture_replays_and_preserves_quarantine(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt, _, _ = fixture(root / 'input')
            ledger = root / 'ledger'
            observed = ingest(str(receipt), ledger)
            result = materialize(ledger, observed['observation_id'], ['lov/2024-01-01-1'], 'none')
            self.assertEqual(result['status'], 'accepted')
            # Its untyped source article cannot be promoted by the strict grammar.
            self.assertEqual(result['documents'][0]['status'], 'failed')
            self.assertNotIn('body_path', result['documents'][0])
            before = {p.relative_to(ledger).as_posix(): (file_hash(p), p.stat().st_mtime_ns)
                      for folder in ('observations', 'materializations')
                      for p in (ledger / folder).rglob('*') if p.is_file()}
            self.assertEqual(materialize(ledger, observed['observation_id'], ['lov/2024-01-01-1'])['status'], 'already_present')
            after = {p.relative_to(ledger).as_posix(): (file_hash(p), p.stat().st_mtime_ns)
                     for folder in ('observations', 'materializations')
                     for p in (ledger / folder).rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            lock = ledger / '.cache' / 'materialization-writer.lock'
            lock.write_text('another writer\n', encoding='ascii')
            with self.assertRaisesRegex(ValueError, 'writer lock exists'):
                materialize(ledger, observed['observation_id'], ['lov/2024-01-01-1'])
            self.assertEqual(lock.read_text(encoding='ascii'), 'another writer\n')
            lock.unlink()
            with self.assertRaisesRegex(ValueError, 'parent changed'):
                materialize(ledger, observed['observation_id'], ['lov/2024-01-01-1'], 'none')
            fresh = root / 'fresh'
            ingest(str(receipt), fresh)
            independent = materialize(fresh, observed['observation_id'], ['lov/2024-01-01-1'], 'none')
            self.assertEqual(independent['materialization_id'], result['materialization_id'])
            path = ledger / 'materializations' / result['materialization_id'] / 'README.md'
            path.write_bytes(path.read_bytes() + b'Changed')
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                read_materialization(ledger, result['materialization_id'])

    def test_second_observation_appends_with_checked_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger = root / 'ledger'
            outputs = []
            for number in (1, 2):
                receipt, _, _ = fixture(root / f'input{number}', observed=f'2026-09-2{number}T12:00:00+00:00')
                observed = ingest(str(receipt), ledger)
                outputs.append(materialize(ledger, observed['observation_id'], ['lov/2024-01-01-1'],
                                           outputs[-1]['materialization_id'] if outputs else 'none'))
            self.assertEqual(outputs[1]['parent_materialization_id'], outputs[0]['materialization_id'])
            self.assertEqual([r['materialization_id'] for r in materializations(ledger)],
                             [r['materialization_id'] for r in outputs])


if __name__ == '__main__':
    unittest.main()
