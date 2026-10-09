"""Scholarly discovery via fixed HTTPS endpoints; secrets stay in this process."""
import copy
import html
import json
import os
import re
import socket
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote, urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener
from .parsers import doi


class ProviderRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        original, target = urlparse(req.full_url), urlparse(newurl)
        if target.scheme != 'https' or target.netloc != original.netloc:
            raise ProviderError('Provider redirected outside its trusted HTTPS endpoint. Request stopped.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Patchable transport boundary; redirects cannot forward keys to another origin.
urlopen = build_opener(ProviderRedirects()).open


class ProviderError(Exception):
    def __init__(self, message, status=502, retry_after=None):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


def text(value):
    return html.unescape(re.sub(r'<[^>]*>', '', str(value or ''))).strip()


def link(value):
    value = str(value or '')
    u = urlparse(value)
    return value if u.scheme in ('https', 'http') and u.hostname and not u.username else ''


def element(node, path):
    found = node.find(path)
    return ''.join(found.itertext()).strip() if found is not None else ''


def record(provider, identifier, **fields):
    return dict(title='', author='', year='', journal='', abstract='', doi='', pmid='', url='',
                oa_url='', pdf_url='', is_oa=None, provider=provider, provider_id=str(identifier or '')) | fields


def crossref_record(w):
    date = next((w[k].get('date-parts', [[]])[0] for k in ('published', 'published-print', 'published-online', 'issued') if w.get(k)), [])
    return record('crossref', w.get('DOI'), title=text((w.get('title') or [''])[0]),
                  author='; '.join(text(a.get('name') or ' '.join(filter(None, [a.get('given'), a.get('family')]))) for a in w.get('author', [])),
                  year=str(date[0]) if date else '', journal=text((w.get('container-title') or [''])[0]),
                  doi=doi(w.get('DOI') or ''), abstract=text(w.get('abstract')), url=link((w.get('resource', {}).get('primary') or {}).get('URL') or w.get('URL')))


def openalex_record(w):
    index = w.get('abstract_inverted_index') or {}
    positions = sorted((i, word) for word, offsets in index.items() for i in offsets)
    locations = [x for x in [w.get('best_oa_location')] + (w.get('locations') or []) if x and x.get('is_oa') is True]
    primary = w.get('primary_location') or {}
    return record('openalex', w.get('id'), title=text(w.get('display_name')),
                  author='; '.join(text((a.get('author') or {}).get('display_name')) for a in w.get('authorships', [])),
                  year=str(w.get('publication_year') or ''), journal=text((primary.get('source') or {}).get('display_name')),
                  doi=doi(w.get('doi') or ''), pmid=str((w.get('ids') or {}).get('pmid') or '').rstrip('/').split('/')[-1],
                  abstract=' '.join(word for _, word in positions), url=link(primary.get('landing_page_url') or w.get('doi') or w.get('id')),
                  is_oa=(w.get('open_access') or {}).get('is_oa'),
                  oa_url=next((link(x.get('landing_page_url')) for x in locations if link(x.get('landing_page_url'))), ''),
                  pdf_url=next((link(x.get('pdf_url')) for x in locations if link(x.get('pdf_url'))), ''))


def pubmed_records(body):
    root = ET.fromstring(body)
    if root.find('.//ERROR') is not None:
        raise ProviderError('PubMed could not complete this query. Please revise the search.')
    output = []
    for node in root.findall('./PubmedArticle'):
        article = node.find('./MedlineCitation/Article')
        if article is None:
            continue
        ids = {x.get('IdType'): x.text or '' for x in node.findall('./PubmedData/ArticleIdList/ArticleId')}
        pmid = element(node, './MedlineCitation/PMID')
        year = element(article, './Journal/JournalIssue/PubDate/Year')
        if not year:
            match = re.search(r'\b\d{4}\b', element(article, './Journal/JournalIssue/PubDate/MedlineDate'))
            year = match.group() if match else ''
        authors = []
        for a in article.findall('./AuthorList/Author'):
            authors.append(element(a, './CollectiveName') or ' '.join(filter(None, [element(a, './ForeName'), element(a, './LastName')])))
        abstract = '\n'.join((x.get('Label', '') + ': ' if x.get('Label') else '') + ''.join(x.itertext()).strip() for x in article.findall('./Abstract/AbstractText'))
        pmc = ids.get('pmc', '')
        # A PMC article webpage is not proof of an OA licence or a downloadable PDF.
        output.append(record('pubmed', pmid, title=element(article, './ArticleTitle'), author='; '.join(authors),
                             year=year, journal=element(article, './Journal/Title'), abstract=abstract, doi=doi(ids.get('doi', '')),
                             pmid=pmid, url=f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
                             oa_url=f'https://pmc.ncbi.nlm.nih.gov/articles/{pmc}/' if pmc else ''))
    return output


class Discovery:
    TTL = 3600
    def __init__(self):
        self.lock = threading.RLock()
        self.cache = OrderedDict()
        self.snapshots = OrderedDict()
        self.next_request = {}
        self.intervals = {'crossref': 1.0, 'openalex': 1.0, 'pubmed': .4}

    def request(self, provider, path, params=None, xml=False):
        bases = {'crossref': 'https://api.crossref.org/', 'openalex': 'https://api.openalex.org/', 'pubmed': 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'}
        params = dict(params or {})
        headers = {'User-Agent': 'RedReview/0.2 (https://github.com/saprimad/redreview)', 'Accept': 'application/xml' if xml else 'application/json'}
        email = os.environ.get('REDREVIEW_CONTACT_EMAIL', '')
        if provider == 'crossref' and email:
            params['mailto'] = email
        if provider == 'openalex' and os.environ.get('OPENALEX_API_KEY'):
            headers['Authorization'] = 'Bearer ' + os.environ['OPENALEX_API_KEY']
        if provider == 'pubmed':
            params['tool'] = 'redreview'
            if email:
                params['email'] = email
            if os.environ.get('NCBI_API_KEY'):
                params['api_key'] = os.environ['NCBI_API_KEY']
        now = time.monotonic()
        wait = self.next_request.get(provider, 0) - now
        if wait > 3:
            raise ProviderError('Provider rate limit is cooling down. Retry later.', 429, int(wait) + 1)
        if wait > 0:
            time.sleep(wait)
        self.next_request[provider] = time.monotonic() + self.intervals[provider]
        url = bases[provider] + path + ('?' + urlencode(params) if params else '')
        try:
            with urlopen(Request(url, headers=headers), timeout=12) as response:
                limit = response.headers.get('X-Rate-Limit-Limit')
                interval = response.headers.get('X-Rate-Limit-Interval', '')
                if provider == 'crossref' and limit and interval:
                    try:
                        self.intervals[provider] = max(1.0, float(interval.rstrip('s')) / float(limit))
                        self.next_request[provider] = time.monotonic() + self.intervals[provider]
                    except (ValueError, ZeroDivisionError):
                        pass
                if provider == 'openalex' and response.headers.get('X-RateLimit-Remaining') == '0':
                    self.next_request[provider] = time.monotonic() + float(response.headers.get('X-RateLimit-Reset', '60'))
                body = response.read(8 * 1024 * 1024 + 1)
                if len(body) > 8 * 1024 * 1024:
                    raise ProviderError('Provider response exceeded the safe size limit. Narrow the search.')
                return body if xml else json.loads(body)
        except HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429:
                retry = e.headers.get('Retry-After', '60')
                try:
                    seconds = float(retry)
                except ValueError:
                    try:
                        seconds = (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError):
                        seconds = 60
                seconds = max(1, min(seconds, 86400))
                self.next_request[provider] = time.monotonic() + seconds
                raise ProviderError('Provider rate limit or daily allowance reached. Retry after the cooldown; a free API key may increase your allowance.', 429, int(seconds)) from None
            if e.code in (401, 403):
                raise ProviderError('Provider rejected authentication. Check the backend API key and provider account permissions.', 503) from None
            raise ProviderError(f'Provider returned HTTP {e.code}. Retry later or revise your query.') from None
        except (URLError, OSError, socket.timeout):
            raise ProviderError('Cannot reach the scholarly provider. Check backend internet access and retry.') from None
        except (ValueError, ET.ParseError):
            raise ProviderError('Provider returned an unreadable response. Retry later.') from None

    def search(self, data):
        provider = data.get('provider', 'crossref')
        mode = data.get('mode', 'keyword')
        query = data.get('query', '')
        journal = data.get('journal', '')
        if provider not in self.intervals or mode not in ('keyword', 'title', 'doi'):
            raise ValueError('Choose Crossref, OpenAlex or PubMed and a valid search mode.')
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500 or not isinstance(journal, str) or len(journal) > 200:
            raise ValueError('Provide a search of 1–500 characters and journal of at most 200 characters.')
        page = int(data.get('page', 1))
        if not 1 <= page <= 500:
            raise ValueError('Page must be between 1 and 500; refine large searches.')
        start, end = str(data.get('year_from') or ''), str(data.get('year_to') or '')
        for year in (start, end):
            if year and (not re.fullmatch(r'\d{4}', year) or not 1000 <= int(year) <= 2100):
                raise ValueError('Years must be between 1000 and 2100.')
        if start and end and start > end:
            raise ValueError('Start year must not exceed end year.')
        oa = data.get('oa', False)
        if not isinstance(oa, bool):
            raise ValueError('Open access filter must be true or false.')
        if provider == 'crossref' and oa:
            raise ValueError('Crossref has no reliable open-access filter. Choose OpenAlex or PubMed.')
        if mode == 'doi':
            query = doi(query)
            if not re.fullmatch(r'10\.\d{4,9}/\S+', query):
                raise ValueError('Enter a valid DOI or https://doi.org/ link.')
            if start or end or journal or oa:
                raise ValueError('Clear filters for DOI lookup.')
            page = 1
        criteria = dict(provider=provider, mode=mode, query=query.strip(), journal=journal.strip(), year_from=start, year_to=end, oa=oa, page=page)
        key = json.dumps(criteria, sort_keys=True)
        with self.lock:
            # Serialise requests across providers to enforce per-process limits and coalesce cache misses.
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < self.TTL:
                self.cache.move_to_end(key)
                result = copy.deepcopy(cached[1])
                result['cached'] = True
                return result
            try:
                records, total, notes = self._search(criteria)
            except (KeyError, TypeError, ET.ParseError) as e:
                raise ProviderError('Provider returned unexpected metadata. Try again later.') from e
            timestamp = datetime.now(timezone.utc).isoformat()
            for item in records:
                item['retrieved_at'] = timestamp
                item['search_query'] = criteria
                item['result_id'] = str(uuid.uuid4())
            sid = str(uuid.uuid4())
            result = dict(records=records, total=total, page=page, page_size=20, has_more=mode != 'doi' and page * 20 < min(total, 10000),
                          cached=False, retrieved_at=timestamp, search_id=sid, criteria=criteria, notes=notes)
            self.cache[key] = (time.monotonic(), copy.deepcopy(result))
            self.snapshots[sid] = (time.monotonic(), copy.deepcopy(result))
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
            while len(self.snapshots) > 256:
                self.snapshots.popitem(last=False)
            return result

    def selected(self, sid, ids):
        with self.lock:
            snapshot = self.snapshots.get(sid)
            if not snapshot or time.monotonic() - snapshot[0] > 86400:
                raise ValueError('Search selection expired. Repeat the search before importing.')
            if not isinstance(ids, list) or not ids or len(ids) > 20 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
                raise ValueError('Select 1–20 distinct results from this page.')
            rows = {r['result_id']: r for r in snapshot[1]['records']}
            if any(i not in rows for i in ids):
                raise ValueError('Selection does not belong to this search.')
            return copy.deepcopy([rows[i] for i in ids])

    def _search(self, c):
        p, q, mode, page = c['provider'], c['query'], c['mode'], c['page']
        notes = []
        if p == 'crossref':
            if mode == 'doi':
                result = self.request(p, 'works/' + quote(q, safe=''))
                return ([crossref_record(result['message'])] if result else []), int(bool(result)), ['Crossref open-access status is unknown; deposited PDF links are not evidence of lawful free access.']
            params = {'query.title' if mode == 'title' else 'query.bibliographic': q, 'rows': 20, 'offset': (page - 1) * 20}
            filters = []
            if c['year_from']:
                filters.append('from-pub-date:' + c['year_from'] + '-01-01')
            if c['year_to']:
                filters.append('until-pub-date:' + c['year_to'] + '-12-31')
            if c['journal']:
                if not re.fullmatch(r'\d{4}-\d{3}[\dXx]', c['journal']):
                    raise ValueError('Crossref journal filtering requires an ISSN, for example 0028-0836.')
                filters.append('issn:' + c['journal'])
            if filters:
                params['filter'] = ','.join(filters)
            result = self.request(p, 'works', params)['message']
            return [crossref_record(w) for w in result['items']], int(result['total-results']), ['Crossref relevance search is ranked, not exact title matching. Journal filter uses ISSN; OA status is unknown.']
        if p == 'openalex':
            if mode == 'doi':
                result = self.request(p, 'works/https://doi.org/' + quote(q, safe=''))
                return ([openalex_record(result)] if result else []), int(bool(result)), []
            params = {'search.title' if mode == 'title' else 'search': q, 'per_page': 20, 'page': page}
            filters = []
            if c['year_from'] or c['year_to']:
                filters.append('publication_year:' + (c['year_from'] or '1000') + '-' + (c['year_to'] or '2100'))
            if c['oa']:
                filters.append('open_access.is_oa:true')
            if c['journal']:
                journal = c['journal']
                if re.fullmatch(r'S\d+', journal, re.I):
                    filters.append('primary_location.source.id:' + journal)
                elif re.fullmatch(r'\d{4}-\d{3}[\dXx]', journal):
                    filters.append('primary_location.source.issn:' + journal)
                else:
                    raise ValueError('OpenAlex journal filtering requires an ISSN or source ID such as S137773608.')
            if filters:
                params['filter'] = ','.join(filters)
            result = self.request(p, 'works', params)
            return [openalex_record(w) for w in result['results']], int(result['meta']['count']), ['OA links are provider-reported; availability and licences can change.']
        if mode == 'title':
            # NLM's documented proximity syntax avoids the phrase-index and
            # stopword failures of tagging a complete pasted title as one phrase.
            words = re.findall(r'\w+', q)
            if not words:
                raise ValueError('Title search needs a word. Use keyword mode for advanced PubMed syntax.')
            term = '"' + ' '.join(words) + '"[Title:~1000]' if len(words) > 1 else words[0] + '[Title]'
            notes.append('PubMed title mode matches supplied words in the title in any order (proximity window 1000); punctuation is ignored. Use keyword mode for advanced field/Boolean syntax.')
        else:
            term = f'"{q}"[AID]' if mode == 'doi' else f'({q})'
        if c['year_from'] or c['year_to']:
            term += f" AND ({c['year_from'] or '1000'}:{c['year_to'] or '2100'}[dp])"
        if c['journal']:
            term += ' AND "' + c['journal'].replace('"', '') + '"[Journal]'
        if c['oa']:
            term += ' AND "free full text"[Filter]'
            notes.append('PubMed free-full-text filtering indicates free access, not necessarily an open reuse licence.')
        result = self.request(p, 'esearch.fcgi', dict(db='pubmed', term=term, retmode='json', retmax=20, retstart=(page - 1) * 20))
        if result.get('error'):
            raise ProviderError('PubMed rejected this query. Revise the terms and try again.')
        found = result['esearchresult']
        if found.get('errorlist'):
            raise ValueError('PubMed could not interpret part of the query. Check field syntax.')
        ids = found['idlist']
        notes.append('PubMed translation: ' + str(found.get('querytranslation', term)))
        if not ids:
            return [], int(found['count']), notes
        body = self.request(p, 'efetch.fcgi', dict(db='pubmed', id=','.join(ids), retmode='xml'), xml=True)
        return pubmed_records(body), int(found['count']), notes
