# RedReview

A local-first, MIT-licensed workspace for scoping and systematic reviews. Search real scholarly providers, bring records into projects, screen independently, read attached PDFs, chart data and export the history behind each decision.

The application uses the existing **Python backend, SQLite database and TypeScript interface**. Your current projects, PDFs, decisions, audit history, exports and version-1 backups remain compatible. The interface uses soft sage, warm off-white and charcoal, with responsive controls for desktop and iPhone.

## Run locally

Requirements: **Python 3.11+** and a modern browser. No third-party Python packages or npm installation are needed to run the app. Compiled JavaScript is included. Article discovery requires backend internet access; all existing local review features work offline.

```bash
git clone https://github.com/saprimad/redreview.git
cd redreview
python3 -m src.server
```

Open **http://127.0.0.1:8844/**. Stop with Ctrl+C. On Windows you can use `py -m src.server`, or use WSL. Use `127.0.0.1` because the app checks the Host header.

Optional port and data location:

```bash
python3 -m src.server --port 8845 --data ./private-data/review.sqlite3
```

Default storage is `.data/redreview.sqlite3`, ignored by Git. PDF bytes are stored in that same database. Project backups include PDFs and are unencrypted; keep them private. Stop the app before copying its database for a whole-workspace backup. No existing database is committed or modified by tests.

## Discover and import articles

1. Create or open a non-demo review project and select **Article search**.
2. Choose Crossref, OpenAlex or PubMed; search by keywords, title or DOI.
3. Optionally filter by publication years and journal. Use ISSN for Crossref, ISSN or an OpenAlex source ID for OpenAlex, and a journal name or ISSN for PubMed. Free/open-access filtering is available for OpenAlex and PubMed. Clear filters for DOI lookup.
4. Inspect title, authors, year, journal, identifiers, available abstract and article links. Missing metadata is labelled. No synthetic data is inserted into discovery results.
5. Select results on the current page and choose a destination project. Import records; read the counts and details for imports, identifier duplicates, failures and uncertain matches.
6. Exact normalised DOI, PMID or provider-ID matches are skipped; retrieval provenance is appended to the existing citation. Close title matches with compatible years and no conflicting known identifiers require review before importing as separate records. You may later merge or undo merges in **Duplicates**.
7. Open **Screening** to work with imported records. **Exports & counts** includes a records CSV with search provenance and the existing decision, charting, audit and count exports.

Provider identifiers, source, full query/filter parameters and UTC retrieval timestamps are retained with records and audit events. Cached responses keep their original retrieval timestamp. Search pages contain up to 20 records; selections are per page. Results and selection snapshots are in memory (cache: one hour, 128 queries; snapshots: up to 24 hours / 256 pages), cleared when the server restarts. Expired selections require a new search. This interactive discovery tool is bounded to the first 10,000 results; narrow larger searches or use database exports.

### Providers and configuration

| Provider | Discovery / filters | Authentication and limits |
| --- | --- | --- |
| Crossref | Keywords, ranked title search, DOI; years and journal ISSN. OA status is unknown. | No key required. Optional contact email selects the polite pool. Backend obeys published rate headers and limits requests to at most one/second by default. |
| OpenAlex | Keywords, scoped title search, DOI; years, journal ISSN/source ID and OA filter; provider-reported OA webpages/PDF URLs. | Current documentation allows casual keyless use; a free key increases allowance. Optional `OPENALEX_API_KEY` is sent in a backend Authorization header. Rate/daily allowance errors are displayed. |
| PubMed | ESearch + batch EFetch for keywords, title or DOI; years, journal name/ISSN and free-full-text filter. Structured abstracts and PMID when supplied. | Optional `NCBI_API_KEY`; a key is not required at the app's conservative limit (one request every 0.4 seconds, below NCBI's unkeyed 3/second limit). |

Set optional keys/contact details **in the backend environment**, never the frontend:

```bash
export REDREVIEW_CONTACT_EMAIL='your-contact@example.org'
export OPENALEX_API_KEY='your-free-key'
export NCBI_API_KEY='your-key'
python3 -m src.server
```

Only set variables you need. `.env.example` documents names; Python does not automatically read `.env`. Restart the backend after configuration changes. No paid plan, subscription or hosting resource is created. Your search terms, DOI and configured contact details go to the chosen provider; saved review decisions and uploaded PDFs do not. Secrets are not returned to the browser or stored in project provenance.

Requests have a 12-second network timeout per provider call, bounded response sizes, conservative per-process throttling, caching and cooldowns for HTTP 429. PubMed normally makes two batched requests per page. Loading, empty results, authentication errors, network failures and rate limits have visible messages. Limits also apply across other apps sharing your IP/key; avoid running multiple RedReview processes with the same provider credentials for bulk harvesting.

Official documentation reviewed 2026-10-09: [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/), [Crossref API reference and rate headers](https://github.com/Crossref/rest-api-doc), [OpenAlex authentication and limits](https://help.openalex.org/api/authentication/), [OpenAlex scoped search](https://help.openalex.org/api/searching/), [OpenAlex filtering](https://help.openalex.org/api/filtering/), [NLM E-utilities](https://www.nlm.nih.gov/dataguide/eutilities/utilities.html).

## Review workflows

- Project questions, eligibility criteria, stages, renaming, archiving and reactivation.
- RIS/BibTeX/CSV imports with CSV mapping, original files and source rows retained.
- Independent local reviewer profiles; blinded views, reasons, notes, labels, adjudication and immutable decision history.
- Keys **1 / 2 / 3** save Include / Exclude / Maybe; **J / K** move between records. Shortcuts pause while typing or using a dialog.
- Lawful manual PDF upload and native browser PDF viewer, DOI and publisher/article links.
- Custom chart fields with distinct Value recorded, Missing / not reported and Not applicable states.
- UTF-8 CSV exports with spreadsheet formula protection, audit history and defined review counts.
- Versioned JSON backup/restore with PDFs; restore creates a separate project.
- Clearly labelled fictional demo projects; real discovery imports into demo projects are blocked.

Profiles are **local labels, not secure accounts**. Blinding is a presentation feature; it does not isolate users with access to the workspace. Existing private Tailscale access remains supported; see [setup and restart commands](docs/tailscale.md).

## Article and PDF access

Metadata, available abstracts, article webpages and downloadable PDFs are distinct. Crossref deposit links do not establish OA permissions and are not labelled free PDFs. OpenAlex reports OA locations and PDF links when supplied. PubMed can link to a PMC article webpage; the presence of a PMC record or free access is not proof of an open reuse licence. External links open in your browser; no automatic PDF downloading, paywall bypass or promise of universal access is made. Attach only lawful local copies.

Article discovery **does not replace a documented comprehensive database search** for a review. Record your protocol, search strategy, database coverage, dates and original exports. Provider results and metadata change. Abstracts and PDFs may carry separate copyright restrictions; see [NCBI's disclaimer and copyright notice](https://www.ncbi.nlm.nih.gov/About/disclaimer.html) and [third-party notices](THIRD_PARTY_NOTICES.md).

No JBI, PRISMA or PRISMA-ScR compliance is claimed. Study/report grouping is not modelled; review counts may need reconciliation. Existing per-project storage limit is 85 MiB and PDFs are limited to 25 MiB each. This version is intended for small reviews (around 1,000 active citations); local candidate matching is quadratic. See [limitations and definitions](docs/limitations.md).

## Website and private hosting

`site/` contains the GitHub Pages landing page: features, installation and source downloads. **GitHub Pages cannot run the Python/SQLite app.** The landing page deploy workflow uploads only that static directory. Enable GitHub Actions in Settings → Pages. Expected URL after a verified deployment: `https://saprimad.github.io/redreview/`.

A private Linux service configuration, persistent database/PDF storage, environment variables, health check and recovery guidance are in [hosting documentation](docs/hosting.md) and `deploy/redreview.service`. No public writable app is deployed. Authentication and verified user/project isolation are required before public hosting. No paid resources are provisioned.

## Development and verification

Node.js 22+ is recommended for development:

```bash
npm ci
npm run typecheck
npm run build
npm test
npm run test:ui
python3 -m compileall -q src tests scripts
```

Commit both `web/app.ts` and generated `web/app.js`. Runtime code has no third-party packages. Original code is MIT licensed; development dependency obligations are inventoried in [third-party notices](THIRD_PARTY_NOTICES.md).

Tests use isolated temporary databases. Backend regression tests cover imports, screening, history, charting, merge/undo, PDFs, exports, backup/restore, archive and Host/Origin/CSRF boundaries. Provider fixtures explicitly remain inside tests. DOM tests use jsdom, compiled UI and real backend handlers with test-only provider fixtures; they do not verify browser layout or PDF rendering. Live HTTP checks skip when sockets are forbidden.

Opt-in live provider smoke check (internet access required, temporary database only):

```bash
python3 scripts/check-live-providers.py
```

See [actual validation results and blocked checks](docs/validation.md). GitHub CI passed on Python 3.11 and 3.14, including all 38 backend tests and both DOM suites. Live keyword/DOI provider searches, temporary imports and duplicate checks passed on the GitHub runner. Real Chrome passed desktop and emulated iPhone-viewport search/import/screening checks. Local startup remains socket-blocked in Codex; restart outside it and verify actual iPhone Safari/PDF access. The Pages workflow requires repository Pages to be enabled before its landing page can be reported live.
