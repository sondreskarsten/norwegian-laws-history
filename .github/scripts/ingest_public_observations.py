"""Catch up every published producer observation without cross-repository writes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import urllib.request

from law_history.ledger import ingest, load_receipt
from law_history.materialize import materialize_all
from law_history.operation_products import extract_all
from law_history.source_body_products import qualify_all


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


def synchronize(repository: Path, producer: str, *, report_path: Path | None = None) -> dict:
    report = {'version': 4, 'producer': producer, 'status': 'running',
              'observations': [], 'materializations': [], 'operation_products': [], 'body_products': [],
              'publication_status': 'not_attempted', 'canonical_status': 'not_verified',
              'legal_valid_time_status': 'unresolved'}

    def checkpoint(phase: str, **progress):
        report['phase'] = phase
        report['progress'] = progress
        report['updated_at'] = datetime.now(timezone.utc).isoformat()
        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = report_path.with_name(report_path.name + '.tmp')
            temporary.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
            temporary.replace(report_path)
        print(json.dumps({'phase': phase, 'run_status': report['status'], **progress}), flush=True)

    checkpoint('release_discovery')
    try:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', producer):
            raise ValueError('Expected a public GitHub owner/repository')
        candidates = [release for release in releases(producer)
                      if not release['draft'] and re.fullmatch(r'observation-[0-9a-f]{64}', release['tag_name'])]
        # Oldest release first makes catch-up progress easy to inspect. The ledger
        # itself orders by observed source time, never by publication/Git date.
        for ordinal, release in enumerate(sorted(candidates, key=lambda item: (item['published_at'], item['tag_name'])), 1):
            tag = release['tag_name']
            checkpoint('observation_intake', release=tag, ordinal=ordinal, total=len(candidates), status='started')
            names = [asset['name'] for asset in release['assets']]
            if sorted(names) != ['evidence.json', 'snapshot.tar.gz']:
                raise ValueError(f'Unexpected assets in producer observation: {tag}')
            url = f'https://github.com/{producer}/releases/download/{tag}/evidence.json'
            receipt = load_receipt(url)
            if (receipt['repository'] != producer or receipt['release_tag'] != tag
                    or receipt['source_sha'] != release['target_commitish']):
                raise ValueError(f'Producer release/receipt identity mismatch: {tag}')
            result = ingest(url, repository)
            summary = {key: result[key] for key in ('observation_id', 'status', 'knowledge_cutoff', 'member_count')}
            summary['snapshot_version'] = receipt['snapshot_version']
            report['observations'].append(summary)
            checkpoint('observation_intake', ordinal=ordinal, total=len(candidates), **summary)
        checkpoint('pilot_materialization', status='started')
        for result in materialize_all(repository):
            report['materializations'].append({key: result[key] for key in ('status', 'observation_id', 'materialization_id',
                                                                          'parent_materialization_id', 'refids', 'documents')})
            checkpoint('pilot_materialization', observation_id=result['observation_id'],
                       materialization_id=result['materialization_id'], status=result['status'],
                       qualified_documents=sum(d['status'] == 'passed' for d in result['documents']))
        history_repository = os.environ.get('GITHUB_REPOSITORY', 'sondreskarsten/norwegian-laws-history')
        checkpoint('operation_extraction', status='started')
        for result in extract_all(repository, history_repository):
            summary = {key: result[key] for key in ('status', 'observation_id', 'operation_product_id',
                                                   'parent_operation_product_id', 'counts', 'diagnostics')}
            report['operation_products'].append(summary)
            checkpoint('operation_extraction', **summary)
        # qualify_all filters the accepted ledger to v5 and preserves existing
        # observation products. Do not copy per-document inventories into logs.
        checkpoint('body_qualification', status='started', scope='accepted_v5_observations')
        for result in qualify_all(repository, history_repository):
            summary = {key: result[key] for key in ('status', 'observation_id', 'body_product_id',
                                                   'parent_body_product_id', 'gate_version', 'counts')}
            report['body_products'].append(summary)
            checkpoint('body_qualification', **summary)
        report['status'] = 'completed'
        checkpoint('intake_complete')
        return report
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)[:2000]}
        checkpoint(report['phase'], **{**report['progress'], 'status': 'failed'})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=Path('.'))
    parser.add_argument('--producer', default='sondreskarsten/norwegian-laws')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    synchronize(args.repository, args.producer, report_path=args.report)
