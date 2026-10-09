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
            cases = [('keyword', dict(mode='keyword', query='community gardening wellbeing')),
                     ('doi', dict(mode='doi', query='10.1371/journal.pone.0266781')),
                     ('filtered', dict(mode='keyword', query='cancer', year_from='2020', year_to='2025',
                                       journal='0028-0836' if provider == 'crossref' else '1932-6203', oa=provider != 'crossref'))]
            reference_title = ''
            for label, criteria in cases:
                try:
                    page = discovery.search(dict(provider=provider, **criteria))
                    if not page['records']:
                        raise RuntimeError('No records returned for the reference query.')
                    if label == 'doi':
                        reference_title = page['records'][0]['title']
                    if label == 'filtered':
                        if any(not r['year'].isdigit() or not 2020 <= int(r['year']) <= 2025 for r in page['records']):
                            raise RuntimeError('Provider year-filter response is outside the requested range.')
                        if provider == 'openalex' and any(r['is_oa'] is not True for r in page['records']):
                            raise RuntimeError('OpenAlex OA filter did not yield reported OA records.')
                    records = discovery.selected(page['search_id'], [page['records'][0]['result_id']])
                    report = store.import_discovery(pid, records, True)
                    duplicate = store.import_discovery(pid, records)
                    if len(duplicate['duplicates']) != 1:
                        raise RuntimeError('Reimport did not detect an exact duplicate.')
                    print(f"PASS {provider} {label}: {len(page['records'])} results; imported {len(report['imported'])}; reimport skipped duplicate.")
                    if label == 'keyword' and page['has_more']:
                        second = discovery.search(dict(provider=provider, **criteria, page=2))
                        if not second['records'] or second['page'] != 2:
                            raise RuntimeError('Second provider page was unavailable.')
                        cached = discovery.search(dict(provider=provider, **criteria, page=2))
                        if not cached['cached']:
                            raise RuntimeError('Repeated page was not cached.')
                        print(f'PASS {provider} pagination/cache')
                except (ProviderError, ValueError, RuntimeError) as error:
                    print(f'FAIL {provider} {label}: {error}')
                    failed += 1
            if reference_title:
                try:
                    title_page = discovery.search(dict(provider=provider, mode='title', query=reference_title[:500]))
                    if not title_page['records']:
                        raise RuntimeError('Scoped title search returned no records.')
                    print(f'PASS {provider} title: {len(title_page["records"])} results')
                except (ProviderError, ValueError, RuntimeError) as error:
                    if provider == 'pubmed':
                        import json
                        for candidate in [f'({reference_title})[Title]', ' AND '.join(w+'[Title]' for w in reference_title.split() if '-' not in w and len(w)>2), '"'+reference_title.replace('-', ' ')+'"[Title:~1000]', 'serologic[Title] AND vaccine[Title]']:
                            response = discovery.request('pubmed','esearch.fcgi',dict(db='pubmed',term=candidate,retmode='json',retmax=1))
                            found=response.get('esearchresult',{})
                            print('TITLE DIAGNOSTIC',json.dumps(dict(query=candidate,count=found.get('count'),errors=found.get('errorlist'),translation=found.get('querytranslation'))))
                    print(f'FAIL {provider} title: {error}')
                    failed += 1
    return bool(failed)

if __name__ == '__main__':
    sys.exit(main())
