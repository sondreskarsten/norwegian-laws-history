"""Reader output uses exact published bytes and refuses uncommitted evidence."""
from pathlib import Path
import json
import unittest
from unittest.mock import patch

from law_history import reader_export
from law_history.source_body_reader import read_body
import test_reproduce_bodies as fixtures


class ReaderExportTests(unittest.TestCase):
    setUp = fixtures.BodyReproductionTests.setUp
    tearDown = fixtures.BodyReproductionTests.tearDown
    git = fixtures.BodyReproductionTests.git
    publish = fixtures.BodyReproductionTests.publish
    remote_head = fixtures.BodyReproductionTests.remote_head
    published = fixtures.BodyReproductionTests.published

    def test_published_versions_exact_html_rejection_and_failed_proof(self):
        first = self.published('one', 'First observed text.', '2026-09-25T12:00:00+00:00')
        second = self.published('two', 'Second observed text.', '2026-09-26T12:00:00+00:00')
        original_text = reader_export._text
        def text(repository, *args):
            if args == ('remote', 'get-url', 'origin'):
                return 'https://github.com/fixture/history.git'
            return original_text(repository, *args)
        with patch.object(reader_export, '_text', side_effect=text):
            output = self.root / 'reader'
            result = reader_export.export_reader(self.repository, output)
            self.assertEqual((result['products'], result['documents']), (2, 2))
            index = json.loads((output / 'index.json').read_bytes())
            self.assertEqual(index['history_repository'], 'fixture/history')
            self.assertEqual(index['history_commit'], self.remote_head())
            for refid, pointer in index['documents'].items():
                data = (output / pointer['path']).read_bytes()
                self.assertEqual(reader_export._sha(data), pointer['metadata_sha256'])
                document = json.loads(data)
                self.assertEqual([v['body_product_id'] for v in document['versions']], [first['body_product_id'], second['body_product_id']])
                for version in document['versions']:
                    retrieved = read_body(self.repository, refid, version['body_product_id'])
                    if version['status'] == 'passed':
                        self.assertEqual((output / version['html_path']).read_bytes(), retrieved['document']['html'].encode('utf-8'))
                    else:
                        self.assertIsNone(version['html_path'])
                        self.assertEqual(retrieved['status'], 'not_qualified')
            with self.assertRaisesRegex(ValueError, 'destination already exists'):
                reader_export.export_reader(self.repository, output)
            receipt = self.repository / 'body-products' / second['body_product_id'] / 'receipt.json'
            saved = receipt.read_bytes()
            receipt.unlink()
            try:
                with self.assertRaisesRegex(ValueError, 'membership differs'):
                    reader_export.export_reader(self.repository, self.root / 'incomplete')
                self.assertFalse((self.root / 'incomplete').exists())
            finally:
                receipt.write_bytes(saved)
            proof = self.repository / 'body-publications' / (second['body_product_id'] + '.json')
            proof.write_bytes(proof.read_bytes() + b' ')
            bad = self.root / 'not-exported'
            with self.assertRaisesRegex(ValueError, 'changed or uncommitted'):
                reader_export.export_reader(self.repository, bad)
            self.assertFalse(bad.exists())


if __name__ == '__main__':
    unittest.main()
