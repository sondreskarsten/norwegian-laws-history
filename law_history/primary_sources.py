"""Independent verification of supplemental primary-source acquisition bundles."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import tarfile
import tempfile
import urllib.request
from .validation import canonical, digest, timestamp, require

CONTRACT='primary-source-acquisition-release-v1'
MAX_BUNDLE=256*1024*1024
MAX_MEMBER=64*1024*1024


def _encoded(value):
    return canonical(value,newline=True)


def verify_primary_sources(receipt, bundle):
    require(receipt.get('contract')==CONTRACT and receipt.get('version')==1,'Unsupported primary source receipt')
    repository=receipt.get('repository','');identity=receipt.get('observation_id')
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository) and digest(identity),'Invalid acquisition identity')
    core={k:v for k,v in receipt.items() if k not in {'observation_id','release_tag','receipt_url'}}
    core['bundle']={k:v for k,v in receipt['bundle'].items() if k!='url'}
    require(hashlib.sha256(_encoded(core)).hexdigest()==identity,'Acquisition receipt identity mismatch')
    require(re.fullmatch(r'[0-9a-f]{40}',receipt.get('source_sha','')),'Invalid producer commit')
    tag='primary-source-'+identity;base=f'https://github.com/{repository}/releases/download/{tag}/'
    require(receipt['release_tag']==tag and receipt['receipt_url']==base+'evidence.json'
            and receipt['bundle']['url']==base+'snapshot.tar.gz' and receipt['bundle']['name']=='snapshot.tar.gz','Acquisition transport identity mismatch')
    bundle=Path(bundle)
    require(0<bundle.stat().st_size<=MAX_BUNDLE and bundle.stat().st_size==receipt['bundle']['bytes'],'Acquisition bundle size mismatch')
    with bundle.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
    require(actual==receipt['bundle']['sha256'],'Acquisition bundle digest mismatch')
    found={};total=0;manifest=None
    with tarfile.open(bundle,'r:gz') as archive:
        for member in archive:
            require(member.isfile() and not member.name.startswith('/') and '..' not in member.name.split('/')
                    and '\\' not in member.name and ':' not in member.name and member.name not in found,'Unsafe or duplicate primary source member')
            total+=member.size
            require(0<=member.size<=MAX_MEMBER and total<=MAX_BUNDLE and len(found)<10000,'Primary source resource limit')
            data=archive.extractfile(member).read(MAX_MEMBER+1)
            require(len(data)==member.size,'Primary source member size mismatch')
            found[member.name]=(hashlib.sha256(data).hexdigest(),len(data))
            if member.name=='manifest.json':manifest=json.loads(data)
    require(found.get('manifest.json',(None,))[0]==receipt['snapshot_manifest_sha256'],'Acquisition manifest digest mismatch')
    require(isinstance(manifest,list) and bool(manifest),'Invalid acquisition manifest')
    expected={'manifest.json'};successes=0;failures=0
    for row in manifest:
        require(isinstance(row,dict) and isinstance(row.get('url'),str) and row['url'].startswith('https://'),'Invalid acquisition source URL')
        timestamp(row['retrieved_at'])
        if 'path' not in row:
            require(bool(row.get('error')),'Missing acquisition outcome');failures+=1;continue
        path=row['path'];require(path not in expected and row.get('status')==200,'Duplicate or unsuccessful acquisition')
        expected.add(path)
        require(found.get(path)==(row['sha256'],row['bytes']),'Acquired source differs from manifest');successes+=1
    require(set(found)==expected and receipt['member_count']==len(found)
            and receipt['acquired_sources']==successes and receipt['failed_attempts']==failures,'Acquisition inventory mismatch')
    return {'contract':CONTRACT,'observation_id':identity,'status':'verified_acquisition',
            'legal_state':'not_assessed','source_receipt':receipt['receipt_url'],'sources':manifest}


def _download(url,path):
    with urllib.request.urlopen(url,timeout=60) as source,path.open('xb') as output:
        total=0
        while data:=source.read(1024*1024):
            total+=len(data);require(total<=MAX_BUNDLE,'Primary source download limit');output.write(data)


def read_primary_sources(location, bundle=None):
    with tempfile.TemporaryDirectory(prefix='primary-source-') as temporary:
        root=Path(temporary)
        if location.startswith('https://'):
            require(re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases/download/primary-source-[0-9a-f]{64}/evidence\.json',location),'Expected public acquisition receipt URL')
            receipt_path=root/'evidence.json';_download(location,receipt_path)
        else:receipt_path=Path(location)
        receipt=json.loads(receipt_path.read_bytes())
        if location.startswith('https://'):require(receipt['receipt_url']==location,'Receipt URL binding differs')
        if bundle is None:
            identity=receipt.get('observation_id','');repository=receipt.get('repository','')
            require(digest(identity) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository),'Invalid primary source identity')
            expected=f'https://github.com/{repository}/releases/download/primary-source-{identity}/snapshot.tar.gz'
            require(receipt['bundle']['url']==expected,'Invalid acquisition bundle URL')
            bundle=root/'snapshot.tar.gz';_download(expected,bundle)
        return verify_primary_sources(receipt,bundle)
