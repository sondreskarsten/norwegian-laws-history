import copy
import unittest
from test_operations import evidence, SOURCE
from law_history.operations import extract_act
from law_history.ordered_operations import ordered_evidence

class OrderedEvidenceTests(unittest.TestCase):
    def test_full_body_survives_zero_parsed_operations(self):
        inputs=evidence(operations=False);record=extract_act(**inputs)
        result=ordered_evidence(record,inputs['raw_xml'])
        self.assertEqual(result['operations'],[])
        self.assertEqual(result['coverage']['source_units'],7)
        self.assertEqual(result['coverage']['unmatched_source_units'],7)
        self.assertIn('replacement',str(result['body_tree']))
        self.assertEqual(result,ordered_evidence(record,inputs['raw_xml']))

    def test_empty_repeal_and_ambiguous_instructions_remain_explicit(self):
        inputs=evidence();result=ordered_evidence(extract_act(**inputs),inputs['raw_xml'])
        self.assertEqual(result['operations'][0]['producer_record']['new_text'],'')
        self.assertEqual(len(result['operations'][0]['instruction_candidates']),1)
        self.assertEqual(len(result['operations'][2]['instruction_candidates']),2)
        self.assertFalse(any(r['legal_eligibility'] for r in result['operations']))

    def test_ordered_replacement_subtree_retains_inline_and_tail_text(self):
        raw=SOURCE.replace(b'<article class="defaultP">\xc2\xa7 12 oppheves.</article>',
          b'<article class="defaultP">\xc2\xa7 12 oppheves.</article><article class="futureLegalArticle"><h3>New</h3><article class="legalP">Before <i>inside</i> after</article></article>')
        inputs=evidence(raw=raw);result=ordered_evidence(extract_act(**inputs),raw)
        tree=result['operations'][0]['instruction_candidates'][0]['following_replacement_trees'][0]
        self.assertEqual(tree['children'][1]['children'][0],'Before ')
        self.assertEqual(tree['children'][1]['children'][1]['children'],['inside'])
        self.assertEqual(tree['children'][1]['children'][2],' after')
        with self.assertRaises(ValueError):ordered_evidence(extract_act(**inputs),raw+b' ')


    def test_retained_real_amendment_preserves_complete_replacement(self):
        from pathlib import Path
        import json
        root=Path(__file__).parent/'fixtures/ordered_operations'
        raw=(root/'forskrift-2025-05-28-955.xml').read_bytes()
        record=json.loads((root/'forskrift-2025-05-28-955-v1.json').read_bytes())
        result=ordered_evidence(record,raw)
        candidate=result['operations'][0]['instruction_candidates'][0]
        replacement=candidate['following_replacement_trees'][0]
        self.assertEqual(replacement['attributes']['class'],'futureLegalArticle')
        self.assertIn('218,62',str(replacement))
        self.assertEqual(result['member_sha256'],'4204439d2013a94dda7b5fad474f6e8d270b7a4cca9b713d4827247f3b13cca3')
