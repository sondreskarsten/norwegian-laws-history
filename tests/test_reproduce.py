"""A real local Git publication is regenerated without copying its output."""
import unittest

import test_publication as support
from law_history.reproduce import reproduce


class ReproductionTests(unittest.TestCase):
    def test_published_product_is_regenerated_offline_and_original_is_preserved(self):
        project = support.PublicationTests()
        project.setUp()
        try:
            _, product = project.accepted()
            project.publish()
            head = project.git("rev-parse", "HEAD").strip()
            result = reproduce(project.repository, product["materialization_id"])
            self.assertEqual(result["status"], "reproduced")
            self.assertFalse(result["target_product_copied"])
            self.assertEqual(result["network_during_regeneration"], "denied")
            self.assertEqual(result["checked_checkout"], head)
            self.assertEqual(set(result["artifact_hashes"]), {*product["artifact_hashes"], "receipt.json"})
            self.assertEqual(project.git("rev-parse", "HEAD").strip(), head)
        finally:
            project.tearDown()
