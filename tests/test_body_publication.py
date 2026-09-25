"""Exercise qualified/rejected lookup and actual Git publication/replay."""
import contextlib
import io
from unittest.mock import patch
import unittest

from law_history import publication
from law_history.__main__ import main
from law_history.ledger import ingest
from law_history.source_body_products import qualify_bodies
from law_history.source_body_reader import read_body
from law_history.validation import read_json
import test_publication as git_fixtures
from test_source_body_products import small_xml, source_fixture


class BodyPublicationTests(unittest.TestCase):
    setUp = git_fixtures.PublicationTests.setUp
    tearDown = git_fixtures.PublicationTests.tearDown
    git = git_fixtures.PublicationTests.git
    accepted = git_fixtures.PublicationTests.accepted
    publish = git_fixtures.PublicationTests.publish
    remote_head = git_fixtures.PublicationTests.remote_head

    def test_qualified_lookup_rejected_output_and_checked_publication_replay(self):
        _, prior = self.accepted()
        self.publish()
        old_receipt = self.repository / 'publications' / (prior['materialization_id'] + '.json')
        old_bytes = old_receipt.read_bytes()
        source, observation, _ = source_fixture(self.root / 'body-source', [small_xml(),
            small_xml('lov/2024-01-01-2', context=' dir="rtl"')], observed='2026-09-25T13:00:00+00:00')
        ingest(str(source), self.repository)
        product = qualify_bodies(self.repository, observation['observation_id'], github_repository='fixture/history')
        identity = product['body_product_id']
        found = read_body(self.repository, 'lov/2024-01-01-1', identity)
        self.assertEqual(found['status'], 'qualified')
        self.assertFalse(found['source_requalification_in_this_read'])
        self.assertEqual(read_body(self.repository, 'lov/2024-01-01-2', identity)['status'], 'not_qualified')
        self.assertEqual(read_body(self.repository, 'lov/2024-01-01-3', identity)['status'], 'not_in_selected_observation')
        out = self.root / 'body.html'
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--repository', str(self.repository), 'body', 'lov/2024-01-01-1',
                                   '--product', identity, '--output', str(out)]), 0)
            rejected = self.root / 'rejected.html'
            self.assertEqual(main(['--repository', str(self.repository), 'body', 'lov/2024-01-01-2',
                                   '--product', identity, '--output', str(rejected)]), 2)
        self.assertEqual(out.read_bytes(), found['document']['html'].encode('utf-8'))
        self.assertFalse(rejected.exists())
        before = self.remote_head()
        with patch.object(publication, 'publish_body_bundle', side_effect=ValueError('Public release failed')):
            with self.assertRaisesRegex(ValueError, 'Public release failed'):
                self.publish()
        self.assertEqual(self.remote_head(), before)
        with patch.object(publication, 'publish_body_bundle', return_value={'status': 'published'}) as release:
            result = self.publish()
            release.assert_called_once()
        self.assertEqual(result['body_publication_count'], 1)
        self.assertEqual(result['remote_head'], self.remote_head())
        receipt = read_json(self.repository / 'body-publications' / (identity + '.json'))
        self.assertEqual(receipt['contract'], 'history-body-git-publication-v1')
        self.assertEqual(receipt['creation_commit'], result['data_commit'])
        self.assertEqual(old_receipt.read_bytes(), old_bytes)
        with patch.object(publication, 'read_body_product', side_effect=AssertionError('Old source read')), \
             patch.object(publication, 'publish_body_bundle', side_effect=AssertionError('Old release read')):
            replay = self.publish()
        self.assertEqual(replay['status'], 'already_published')
        self.assertEqual(replay['remote_head'], result['remote_head'])
        self.assertEqual(old_receipt.read_bytes(), old_bytes)


if __name__ == '__main__':
    unittest.main()
