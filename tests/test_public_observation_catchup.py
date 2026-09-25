"""Real small v4/v5 intake and product catch-up; only public transport is mocked."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from law_history.ledger import ingest, load_receipt
from test_consumer import fixture
from test_source_body_products import small_xml, source_fixture


SCRIPT = Path(__file__).parents[1] / '.github/scripts/ingest_public_observations.py'
spec = importlib.util.spec_from_file_location('public_observation_catchup', SCRIPT)
catchup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catchup)


class PublicObservationCatchupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='public-catchup-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = self.root / 'ledger'
        old, old_receipt, _ = fixture(self.root / 'v4', observed='2026-09-24T12:00:00+00:00')
        new, new_receipt, _ = source_fixture(self.root / 'v5', [small_xml(), small_xml(
            'lov/2024-01-01-2', context=' dir="rtl"')])
        self.identities = [old_receipt['observation_id'], new_receipt['observation_id']]
        self.paths = {receipt['receipt_url']: path for path, receipt in [(old, old_receipt), (new, new_receipt)]}
        self.releases = [dict(draft=False, tag_name=r['release_tag'], target_commitish=r['source_sha'],
                             published_at=str(i), assets=[{'name': n} for n in ('evidence.json', 'snapshot.tar.gz')])
                         for i, r in enumerate([old_receipt, new_receipt])]

    def run_catchup(self, report, *, fail_body=False):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(catchup, 'releases', return_value=reversed(self.releases)))
            stack.enter_context(patch.object(catchup, 'load_receipt', side_effect=lambda url: load_receipt(str(self.paths[url]))))
            stack.enter_context(patch.object(catchup, 'ingest', side_effect=lambda url, repo: ingest(str(self.paths[url]), repo)))
            stack.enter_context(patch.dict(os.environ, {'GITHUB_REPOSITORY': 'fixture/history'}))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            if fail_body:
                stack.enter_context(patch.object(catchup, 'qualify_all', side_effect=RuntimeError('body catch-up failed')))
            return catchup.synchronize(self.repository, 'fixture/evidence', report_path=report)

    def test_v4_pilot_operations_and_v5_full_body_catchup_replay(self):
        report_path = self.root / 'diagnostics/readback.json'
        report = self.run_catchup(report_path)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['publication_status'], 'not_attempted')
        self.assertEqual([r['observation_id'] for r in report['observations']], self.identities)
        self.assertEqual([r['snapshot_version'] for r in report['observations']], [4, 5])
        self.assertEqual(len(report['materializations']), 2)
        self.assertEqual(len(report['operation_products']), 2)
        self.assertEqual(len(report['body_products']), 1)
        body = report['body_products'][0]
        self.assertEqual(body['observation_id'], self.identities[1])
        self.assertEqual(body['counts'], {'selected': 2, 'laws': 2, 'forskrifter': 0, 'passed': 1, 'rejected': 1})
        self.assertNotIn('documents', body)
        receipt = self.repository / 'body-products' / body['body_product_id'] / 'receipt.json'
        before = receipt.read_bytes()
        replay = self.run_catchup(report_path)
        for key in ('observations', 'materializations', 'operation_products', 'body_products'):
            self.assertTrue(all(r['status'] == 'already_present' for r in replay[key]), key)
        self.assertEqual(before, receipt.read_bytes())
        self.assertEqual(json.loads(report_path.read_text()), replay)

    def test_failure_retains_completed_work_and_does_not_report_success(self):
        report_path = self.root / 'diagnostics/failed.json'
        with self.assertRaisesRegex(RuntimeError, 'body catch-up failed'):
            self.run_catchup(report_path, fail_body=True)
        report = json.loads(report_path.read_text())
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['phase'], 'body_qualification')
        self.assertEqual(report['publication_status'], 'not_attempted')
        self.assertEqual(report['error']['type'], 'RuntimeError')
        self.assertEqual(len(report['observations']), 2)
        self.assertEqual(len(report['materializations']), 2)
        self.assertEqual(len(report['operation_products']), 2)
        self.assertEqual(report['body_products'], [])
        self.assertFalse(report_path.with_name(report_path.name + '.tmp').exists())
