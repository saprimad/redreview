#!/usr/bin/env python3
"""Opt-in live smoke checks, with temporary storage; no personal project changes."""
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.discovery import Discovery, ProviderError
from src.store import Store

def main():
    failed = 0
    discovery = Discovery()
    with tempfile.TemporaryDirectory(prefix='redreview-live-') as directory:
        store = Store(Path(directory) / 'review.sqlite3')
        pid = store.create('Live smoke test')['id']
        for provider in ('crossref', 'openalex', 'pubmed'):
            for mode, query in [('keyword', 'community gardening wellbeing'), ('doi', '10.1371/journal.pone.0266781')]:
                try:
                    page = discovery.search(dict(provider=provider, mode=mode, query=query))
                    if not page['records']:
                        raise RuntimeError('No records returned for the reference query.')
                    records = discovery.selected(page['search_id'], [page['records'][0]['result_id']])
                    report = store.import_discovery(pid, records, True)
                    duplicate = store.import_discovery(pid, records)
                    if len(duplicate['duplicates']) != 1:
                        raise RuntimeError('Reimport did not detect an exact duplicate.')
                    print(f"PASS {provider} {mode}: {len(page['records'])} results; imported {len(report['imported'])}; reimport skipped duplicate.")
                except (ProviderError, ValueError, RuntimeError) as error:
                    print(f'FAIL {provider} {mode}: {error}')
                    failed += 1
    return bool(failed)

if __name__ == '__main__':
    sys.exit(main())
