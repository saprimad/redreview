"""Original, dependency-free bibliographic parsers. Fail batches atomically."""
import csv
import io
import re
import unicodedata
from difflib import SequenceMatcher

FIELDS = ('title', 'author', 'year', 'abstract', 'doi', 'url')


def doi(value):
    value = re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', value.strip(), flags=re.I)
    return value.lower().strip().rstrip('.')


def title_key(value):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', value).casefold()))


def similarity(a, b):
    if a['doi'] and doi(a['doi']) == doi(b['doi']):
        return 1.0, 'DOI'
    x, y = title_key(a['title']), title_key(b['title'])
    score = SequenceMatcher(None, x, y).ratio()
    return score if len(x) >= 15 and len(y) >= 15 else 0, 'Title similarity'


def _parse(text, fmt, mapping=None):
    text = text.lstrip('\ufeff')
    rows = []
    if fmt == 'csv':
        reader = csv.DictReader(io.StringIO(text), strict=True)
        headers = reader.fieldnames or []
        mapping = mapping or {f: f for f in FIELDS if f in headers}
        if not mapping.get('title') or mapping['title'] not in headers:
            raise ValueError('CSV needs a mapped title column. Select the column containing article titles.')
        if any(v not in headers for v in mapping.values() if v):
            raise ValueError('A mapped CSV column does not exist in the file.')
        for raw in reader:
            if None in raw or any(v is None for v in raw.values()):
                raise ValueError(f'CSV row {reader.line_num} has the wrong number of columns.')
            rows.append(({f: raw.get(mapping.get(f, ''), '') for f in FIELDS}, raw))
    elif fmt == 'ris':
        raw, current = {}, None
        tags = {'TI': 'title', 'T1': 'title', 'AU': 'author', 'A1': 'author', 'PY': 'year', 'Y1': 'year', 'AB': 'abstract', 'N2': 'abstract', 'DO': 'doi', 'UR': 'url'}
        for n, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            m = re.match(r'^([A-Z0-9]{2})\s{2}-\s?(.*)$', line)
            if m:
                tag, value = m.groups()
                if tag == 'TY':
                    if raw:
                        raise ValueError(f'RIS line {n}: previous record is missing ER.')
                    raw = {'TY': [value]}
                elif tag == 'ER':
                    if not raw:
                        raise ValueError(f'RIS line {n}: ER without a record.')
                    data = {f: '' for f in FIELDS}
                    for key, vals in raw.items():
                        if key in tags:
                            data[tags[key]] = '; '.join(vals)
                    rows.append((data, raw))
                    raw, current = {}, None
                    continue
                elif not raw:
                    raise ValueError(f'RIS line {n}: start each record with TY.')
                else:
                    raw.setdefault(tag, []).append(value)
                current = tag
            elif current and raw:
                raw[current][-1] += '\n' + line.strip()
            else:
                raise ValueError(f'RIS line {n}: expected a two-letter tag followed by two spaces and a dash.')
        if raw:
            raise ValueError('RIS record is missing its terminating ER tag.')
    elif fmt == 'bib':
        # Balanced braces/quotes, including nested title braces. No macro expansion.
        pos = 0
        while pos < len(text):
            m = re.search(r'@(\w+)\s*([({])', text[pos:])
            if not m:
                if text[pos:].strip() and not text[pos:].lstrip().startswith('%'):
                    raise ValueError('BibTeX: unexpected text outside an entry.')
                break
            start = pos + m.start()
            pos += m.end()
            opening = m.group(2)
            closing = '}' if opening == '{' else ')'
            depth, quoted, escaped, end = 1, False, False, pos
            while end < len(text) and depth:
                c = text[end]
                if escaped:
                    escaped = False
                elif c == '\\':
                    escaped = True
                elif c == '"':
                    quoted = not quoted
                elif not quoted:
                    if c == opening:
                        depth += 1
                    elif c == closing:
                        depth -= 1
                end += 1
            if depth:
                raise ValueError('BibTeX entry has unbalanced braces or quotes.')
            body = text[pos:end - 1]
            pos = end
            if m.group(1).lower() in ('comment', 'preamble'):
                continue
            if m.group(1).lower() == 'string':
                raise ValueError('BibTeX @string macros are not supported. Export expanded field values.')
            if ',' not in body:
                raise ValueError('BibTeX entry needs a citation key and fields.')
            key, body = body.split(',', 1)
            raw = {'citation_key': key.strip(), 'entry_type': m.group(1), 'original': text[start:end]}
            i = 0
            while i < len(body):
                field = re.match(r'\s*,?\s*(\w+)\s*=\s*', body[i:])
                if not field:
                    if body[i:].strip(' \n\r\t,'):
                        raise ValueError('BibTeX: invalid field syntax.')
                    break
                name = field.group(1).lower()
                i += field.end()
                if i >= len(body):
                    raise ValueError('BibTeX field has no value.')
                if body[i] in '{"':
                    opener = body[i]
                    i += 1
                    j, level, escape = i, 1, False
                    while i < len(body) and level:
                        c = body[i]
                        if escape:
                            escape = False
                        elif c == '\\':
                            escape = True
                        elif opener == '{' and c == '{':
                            level += 1
                        elif c == ('}' if opener == '{' else '"'):
                            level -= 1
                        i += 1
                    if level:
                        raise ValueError('BibTeX field is unterminated.')
                    value = body[j:i - 1]
                else:
                    j = i
                    while i < len(body) and body[i] != ',':
                        i += 1
                    value = body[j:i].strip()
                    if not value.isdigit():
                        raise ValueError('BibTeX bare macros are unsupported. Use quoted or braced values.')
                raw[name] = value
            rows.append(({f: raw.get(f, '') for f in FIELDS}, raw))
    else:
        raise ValueError('Choose RIS, BibTeX (.bib), or CSV.')
    if not rows:
        raise ValueError('No records found. Check the selected file format.')
    for n, (data, raw) in enumerate(rows, 1):
        for f in FIELDS:
            data[f] = str(data.get(f, '')).strip()
        if not data['title']:
            raise ValueError(f'Record {n} has no title. The batch was not imported.')
        data['doi'] = doi(data['doi'])
    return rows


def parse(text, fmt, mapping=None):
    if not isinstance(text, str):
        raise ValueError('Import content must be UTF-8 text.')
    try:
        return _parse(text, fmt, mapping)
    except csv.Error as e:
        raise ValueError(f'Invalid CSV: {e}. Check quotes and separators.') from e
