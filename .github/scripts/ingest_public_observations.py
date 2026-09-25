"""Catch up every published producer observation without cross-repository writes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import urllib.request

from law_history.ledger import ingest, load_receipt
from law_history.materialize import materialize_all
from law_history.operation_products import extract_all


def releases(repository: str):
    page = 1
    while True:
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'norwegian-laws-history'}
        if os.environ.get('GH_TOKEN'):
            headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
        request = urllib.request.Request(
            f'https://api.github.com/repos/{repository}/releases?per_page=100&page={page}', headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError('Invalid producer release listing')
        yield from batch
        if len(batch) < 100:
            return
        page += 1


def synchronize(repository: Path, producer: str) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', producer):
        raise ValueError('Expected a public GitHub owner/repository')
    candidates = [release for release in releases(producer)
                  if not release['draft'] and re.fullmatch(r'observation-[0-9a-f]{64}', release['tag_name'])]
    accepted = []
    # Oldest release first makes catch-up progress easy to inspect. The ledger
    # itself orders by observed source time, never by publication/Git date.
    for release in sorted(candidates, key=lambda item: (item['published_at'], item['tag_name'])):
        tag = release['tag_name']
        names = [asset['name'] for asset in release['assets']]
        if sorted(names) != ['evidence.json', 'snapshot.tar.gz']:
            raise ValueError(f'Unexpected assets in producer observation: {tag}')
        url = f'https://github.com/{producer}/releases/download/{tag}/evidence.json'
        receipt = load_receipt(url)
        if (receipt['repository'] != producer or receipt['release_tag'] != tag
                or receipt['source_sha'] != release['target_commitish']):
            raise ValueError(f'Producer release/receipt identity mismatch: {tag}')
        result = ingest(url, repository)
        accepted.append({'observation_id': result['observation_id'], 'status': result['status'],
                         'knowledge_cutoff': result['knowledge_cutoff'],
                         'member_count': result['member_count']})
        print(json.dumps(accepted[-1]), flush=True)
    projections = []
    for result in materialize_all(repository):
        projections.append({key: result[key] for key in ('status', 'observation_id', 'materialization_id',
                                                       'parent_materialization_id', 'refids', 'documents')})
        print(json.dumps({'materialization_id': result['materialization_id'], 'status': result['status'],
                          'qualified_documents': sum(d['status'] == 'passed' for d in result['documents'])}), flush=True)
    operations = []
    for result in extract_all(repository, os.environ.get('GITHUB_REPOSITORY', 'sondreskarsten/norwegian-laws-history')):
        summary = {key: result[key] for key in ('status', 'observation_id', 'operation_product_id',
                                               'parent_operation_product_id', 'counts', 'diagnostics')}
        operations.append(summary)
        print(json.dumps(summary), flush=True)
    return {'version': 3, 'producer': producer, 'observations': accepted, 'materializations': projections,
            'operation_products': operations,
            'canonical_status': 'not_verified', 'legal_valid_time_status': 'unresolved'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=Path('.'))
    parser.add_argument('--producer', default='sondreskarsten/norwegian-laws')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = synchronize(args.repository, args.producer)
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
