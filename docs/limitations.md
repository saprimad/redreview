# v0.2 limitations and count definitions

## Scope
Local browser application, not a packaged Tauri desktop app. Python/SQLite backend, framework-free TypeScript interface. No React or Rust dependency. Existing local review features work offline; scholarly discovery requires internet access; PDFs require a browser with native PDF support. No real-browser visual or PDF rendering verification was possible in the implementation sandbox.

Profiles and roles are local labels. They are not secure accounts, authenticated adjudicators, or online collaboration. Blinding hides other decisions, notes, labels, charting, consensus, audit, exports and screening counts in the current view; it is not a security boundary against a local file owner or someone deliberately turning it off.

Stages are manually selected. Full-text screening and charting can be applied to any active record; the app does not enforce eligibility from a previous stage. No dual-reviewer completion policy is inferred. A single current reviewer decision produces an outcome; disagreement produces conflict. A later independent change invalidates an earlier adjudication. `Maybe` is distinct from Include and Exclude.

Each PDF attachment belongs to one record. Full-text decisions are record-level, not independent decisions for each attached report. Multiple reports may represent one study, but study grouping is not modelled. Never describe record counts as study counts.

## Counts exported for a PRISMA flow diagram
These are defined building blocks, not a publication-ready PRISMA diagram. Validate your study/report relationships and screening policy before transcribing them.

| Metric | Definition |
| --- | --- |
| imported_records | All original citations across all import batches, including those subsequently merged. |
| duplicate_records_removed | Citations currently linked to a canonical record by a confirmed merge. Undo decreases this count. |
| active_records | Imported records minus duplicate records removed. |
| abstract_pending/include/exclude/maybe/conflict | Active citations by current title/abstract outcome. Categories partition active records. |
| fulltext_pending/include/exclude/maybe/conflict | Active citations by current full-text outcome. Categories partition active records independently of abstract outcomes. |
| attached_reports | Number of attached PDF files across all original citations. Duplicate files are not content-deduplicated. |
| reports_assessed | Attached files on active citations having a full-text outcome other than pending. This is inferred from record-level decisions, not individual PDF assessments; conflict and maybe count as assessed. |
| studies | Not modelled; exported explicitly as `not modelled`, never guessed. |

Pending full-text outcomes do not distinguish retrieval attempted, not retrieved, and not yet assessed. Abstract Include does not prove full-text retrieval. The app does not generate invented reports-sought/not-retrieved counts.

## Imports and deduplication
UTF-8 only; comma-delimited CSV with quoted/multiline cells, mapped title required. RIS requires TY/ER boundaries. BibTeX supports balanced braced/quoted fields and numeric bare fields; does not expand @string macros, concatenation, LaTeX markup or arbitrary encodings. Export expanded values if rejected. Raw entries/file contents remain available in backups; original RIS rows preserve unrecognised tags.

Matching DOI or ≥0.90 normalised title similarity proposes a candidate, not a guaranteed duplicate. Authors/year are displayed for inspection. No cross-project merges, automatic merges, or nested merges. A merge keeps the first record active and links source provenance. Original metadata is not overwritten. Secondary decisions/charting/PDFs remain on their original record and reappear on undo; they are retained in exports and backup while merged. Inspect before merging already-screened citations.

All records and candidate pairs load in memory; candidate detection is quadratic. Recommended for small reviews (about 1,000 active citations), not large bibliographic corpora. Provider discovery is paginated; local candidate matching still needs indexing for larger reviews.

## Files, backups and protection
PDFs are copied into SQLite (25 MiB per file). Project entity storage is limited to 85 MiB, including base64 PDFs and audit versions, so generated JSON backups fit the restore request limit (95 MiB in UI, 100 MiB at transport). Actions crossing the project limit roll back. An exported backup creates a separate project on restore with remapped internal IDs and preserved source data. Arbitrary or future-version backups are rejected. Whole-workspace SQLite copies made with the application stopped are an additional recovery option.

Data and backups are unencrypted. OS permissions and backup storage are your responsibility. No deletion UI; archiving is reversible. State changes and audit events are atomic, connections are closed, and reads/writes are serialised with SQLite transactions. Schema version 1 is created at startup; future versions need explicit migrations.

CSV decision/chart exports contain all versions, not just latest values. Use record, reviewer, stage and timestamp when selecting a current result. Chart statuses are exported alongside values. Columns from removed chart fields remain in historical exports. Spreadsheet formula-leading cells receive an apostrophe; remove it only after assessing the value.

## Discovery and full-text access

Crossref, OpenAlex and PubMed searches run through the Python backend. Result pagination is limited to the first 10,000 matches; broad comprehensive searches should use appropriate databases and original exports. Search modes differ by provider and ranking is not exact bibliographic matching. Missing metadata is explicitly labelled. Journal filtering requires provider-specific identifiers; see README.

Exact DOI/PMID/provider-ID matches are skipped during discovery import; retrieval provenance is recorded. Potential title matches (at least 94% normalised similarity, at least 25 characters, compatible or missing years, no conflicting known DOI/PMID) require review. This differs from the older file-import Duplicates tab, which proposes 90% title candidates for manual inspection. No uncertain discovery match is silently merged. Exact skipped discovery results are not new imported citations and therefore do not increase the existing imported_records/duplicate_records_removed counts. Their import reports and retrievals remain in audit evidence.

Provider-reported free article webpages are distinct from downloadable OA PDFs. OpenAlex OA locations supply direct PDF links only when reported as OA. PubMed links to PMC article pages when a PMCID is present, but does not assume a reuse licence or manufacture PDF URLs. Crossref deposit PDF links are not treated as proof of free access. PDFs are never fetched automatically; attach only lawful local copies. External links and licences can change, and discovery does not grant full-text access to every article.

Live requests were attempted but blocked by backend network restrictions in the implementation sandbox. Parsing, HTTP contracts, imports and UI interactions were checked using explicit test fixtures. No synthetic fixture is used by production search. Browser rendering, real provider responses and a local restart still need unrestricted verification; see validation.md.

## Remaining work

- Verify live searches and DOI lookups, including provider filters and OA links, on an unrestricted backend.
- Verify responsive browser rendering and inline PDF viewing on iPhone and desktop.
- Scale local duplicate matching; support study/report grouping and explicit reviewer completion policies.
- Implement authentication and verify user/project isolation before any public writable deployment.
- Optional ranking assistance must preserve human decision history; no AI inclusion/exclusion is implemented.
