"""Real Git body publications regenerated from source, including a comparison ancestor."""
from copy import deepcopy
from pathlib import Path
import socket
import unittest
from unittest.mock import patch
import urllib.request

from law_history import publication, reproduce_bodies as reproduction
from law_history.ledger import ingest
from law_history.source_body_products import artifact_tree, qualify_bodies
from law_history.validation import canonical, file_hash, read_json
import test_publication as git_fixtures
from test_source_body_products import small_xml, source_fixture


class BodyReproductionTests(unittest.TestCase):
    setUp = git_fixtures.PublicationTests.setUp
    tearDown = git_fixtures.PublicationTests.tearDown
    git = git_fixtures.PublicationTests.git
    publish = git_fixtures.PublicationTests.publish
    remote_head = git_fixtures.PublicationTests.remote_head

    def published(self, label, text, observed):
        source, release, _ = source_fixture(self.root / label,
            [small_xml(content=text), small_xml('lov/2024-01-01-2', context=' dir="rtl"')],
            observed=observed)
        ingest(str(source), self.repository)
        product = qualify_bodies(self.repository, release['observation_id'],
                                 github_repository='fixture/history')
        # Only GitHub release transport is replaced; the actual Git creation,
        # append-only commit, push, readback and publication proof run normally.
        with patch.object(publication, 'publish_body_bundle',
                          return_value={'verification': 'offline_release_fixture'}):
            self.publish()
        return product

    def test_two_products_regenerate_exact_bytes_offline_without_changing_receipts(self):
        first = self.published('one', 'First important text.', '2026-09-25T12:00:00+00:00')
        second = self.published('two', 'Later observed text.', '2026-09-26T12:00:00+00:00')
        self.assertEqual(second['parent_body_product_id'], first['body_product_id'])
        self.assertEqual(second['comparison_product_id'], first['body_product_id'])
        self.assertEqual(second['counts'], {'selected': 2, 'laws': 2, 'forskrifter': 0,
                                           'passed': 1, 'rejected': 1})
        original = {path: path.read_bytes() for directory in ('body-products', 'body-publications')
                    for path in (self.repository / directory).rglob('*.json')}
        for path, data in original.items():
            name = path.relative_to(self.repository).as_posix()
            self.assertEqual(publication._git(self.repository, 'cat-file', 'blob', 'HEAD:' + name).stdout, data)
        head = self.git('rev-parse', 'HEAD').strip()
        real_qualify = reproduction.qualify_bodies

        for target in (first, second):
            with self.subTest(product=target['body_product_id']):
                identity = target['body_product_id']
                expected_artifacts = {name: (artifact_tree(self.repository, target) / name).read_bytes()
                                      for name in target['artifact_hashes']}
                expected_bundle = reproduction.body_bundle(self.repository, target).read_bytes()

                def regenerate(fresh, observation, **options):
                    fresh = Path(fresh)
                    self.assertFalse((fresh / 'body-products' / identity).exists())
                    self.assertFalse((fresh / '.cache/body-bundles' /
                                      (target['bundle']['sha256'] + '.tar.gz')).exists())
                    if target['comparison_product_id']:
                        self.assertTrue((fresh / 'body-products' / first['body_product_id'] / 'receipt.json').is_file())
                    for network in (lambda: urllib.request.urlopen('https://example.invalid/'),
                                    lambda: socket.socket(),
                                    lambda: socket.create_connection(('example.invalid', 443)),
                                    lambda: socket.getaddrinfo('example.invalid', 443)):
                        with self.assertRaisesRegex(AssertionError, 'Offline body reproduction attempted network access'):
                            network()
                    result = real_qualify(fresh, observation, **options)
                    self.assertEqual((fresh / 'body-products' / identity / 'receipt.json').read_bytes(),
                                     original[self.repository / 'body-products' / identity / 'receipt.json'])
                    self.assertEqual(reproduction.body_bundle(fresh, result).read_bytes(), expected_bundle)
                    self.assertEqual({name: (artifact_tree(fresh, result) / name).read_bytes()
                                      for name in result['artifact_hashes']}, expected_artifacts)
                    return result

                with patch.object(reproduction, 'qualify_bodies', side_effect=regenerate) as generated:
                    result = reproduction.reproduce(self.repository, identity)
                generated.assert_called_once()
                self.assertEqual(result['status'], 'reproduced')
                self.assertEqual(result['checked_checkout'], head)
                self.assertEqual(result['network_during_regeneration'], 'denied')
                self.assertFalse(result['target_product_copied'])
                self.assertEqual(result['body_bundle_sha256'], target['bundle']['sha256'])
                self.assertEqual(result['generator'], target['generator'])
                self.assertEqual(result['artifact_hashes'], {**target['artifact_hashes'],
                    'receipt.json': file_hash(self.repository / 'body-products' / identity / 'receipt.json')})
                self.assertEqual(result['preserved_product_receipts'], {
                    product['body_product_id']: file_hash(self.repository / 'body-products' /
                                                          product['body_product_id'] / 'receipt.json')
                    for product in (first, second)})
                self.assertEqual({path: path.read_bytes() for path in original}, original)
                self.assertEqual(self.git('rev-parse', 'HEAD').strip(), head)
                self.assertEqual(self.remote_head(), head)

    def test_python_zlib_or_generator_mismatch_fails_before_fetch_or_generation(self):
        target = self.published('one', 'First text.', '2026-09-25T12:00:00+00:00')
        for field in ('python', 'zlib', 'sources'):
            with self.subTest(field=field):
                different = deepcopy(target['generator'])
                if field == 'sources':
                    different['sources']['source_body_gate.py'] = '0' * 64
                else:
                    different[field] = 'different-runtime'
                with patch.object(reproduction, 'generator_identity', return_value=different), \
                     patch.object(reproduction, 'source_bundle', side_effect=AssertionError('Fetched before runtime check')), \
                     patch.object(reproduction, 'qualify_bodies', side_effect=AssertionError('Generated with wrong runtime')):
                    with self.assertRaisesRegex(ValueError, 'exact generator source, Python and zlib'):
                        reproduction.reproduce(self.repository, target['body_product_id'])

    def test_changed_or_uncommitted_creation_proof_fails_before_generation(self):
        target = self.published('one', 'First text.', '2026-09-25T12:00:00+00:00')
        identity = target['body_product_id']
        path = self.repository / 'body-publications' / (identity + '.json')
        original = path.read_bytes()
        proof = read_json(path)
        changed = {**proof, 'expected_git_parent': '0' * 40}
        path.write_bytes(canonical(changed, newline=True))
        with patch.object(reproduction, 'source_bundle', side_effect=AssertionError('Fetched before proof check')):
            with self.assertRaisesRegex(ValueError, 'publication proof is changed or not committed'):
                reproduction.reproduce(self.repository, identity)
        path.write_bytes(original)
        # At the data commit the product exists, but its proof is only a local
        # file. That file must not substitute for an actual committed proof.
        self.git('checkout', '--detach', proof['creation_commit'])
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(original)
        with patch.object(reproduction, 'source_bundle', side_effect=AssertionError('Fetched before committed proof check')):
            with self.assertRaisesRegex(ValueError, 'cat-file'):
                reproduction.reproduce(self.repository, identity)


if __name__ == '__main__':
    unittest.main()
