import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from law_history.primary_sources import verify_primary_sources, CONTRACT, _encoded

class PrimarySourceTests(unittest.TestCase):
    def fixture(self, root):
        source=b'original primary source bytes'
        manifest=[{'url':'https://example.org/original','retrieved_at':'2026-09-26T09:00:00+00:00','status':200,'path':'source.bin','sha256':hashlib.sha256(source).hexdigest(),'bytes':len(source)}]
        data=_encoded(manifest);bundle=root/'snapshot.tar.gz'
        with tarfile.open(bundle,'w:gz') as t:
            for name,content in [('manifest.json',data),('source.bin',source)]:
                info=tarfile.TarInfo(name);info.size=len(content);t.addfile(info,io.BytesIO(content))
        receipt={'version':1,'contract':CONTRACT,'repository':'example/evidence','source_sha':'a'*40,'snapshot_manifest_sha256':hashlib.sha256(data).hexdigest(),'member_count':2,'acquired_sources':1,'failed_attempts':0,'bundle':{'name':'snapshot.tar.gz','sha256':hashlib.sha256(bundle.read_bytes()).hexdigest(),'bytes':bundle.stat().st_size}}
        identity=hashlib.sha256(_encoded(receipt)).hexdigest();receipt.update(observation_id=identity,release_tag='primary-source-'+identity);base=f'https://github.com/example/evidence/releases/download/primary-source-{identity}/';receipt['receipt_url']=base+'evidence.json';receipt['bundle']['url']=base+'snapshot.tar.gz'
        return receipt,bundle

    def test_independent_member_and_receipt_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt,bundle=self.fixture(Path(tmp));result=verify_primary_sources(receipt,bundle)
            self.assertEqual(result['status'],'verified_acquisition');self.assertEqual(result['legal_state'],'not_assessed')
            changed=copy.deepcopy(receipt);changed['source_sha']='b'*40
            with self.assertRaises(ValueError):verify_primary_sources(changed,bundle)
            bundle.write_bytes(bundle.read_bytes()+b'tamper')
            with self.assertRaises(ValueError):verify_primary_sources(receipt,bundle)
