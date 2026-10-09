# Validation — version 0.2

Validation date: 2026-10-09. Python 3.14.4 and Node 22.22.1 were available. Tests use temporary SQLite databases and test-only provider fixtures; personal reviews and PDFs are not test inputs.

## Passed

- TypeScript strict typecheck and compilation of `web/app.ts` to checked-in `web/app.js`.
- Python suite: **38 tests, 35 passed, 3 live-socket tests skipped**. Tests cover provider parsing, absent metadata, DOI lookup request construction, filters, pagination, caching, snapshot selection, rate-limit handling, API-key redaction, import reports, DOI/PMID/provider-ID duplicates, uncertain title/year matches and existing review workflows.
- Existing review regressions: independent/blinded decisions, adjudication, immutable history, chart status/version handling, RIS/BibTeX/CSV imports, PDF attachment, merge/undo, exports, backup/restore, archiving and project boundaries.
- Compiled UI interaction suite via jsdom and the actual Python handlers through byte streams, at both loopback and a **synthetic** Tailscale authority. Checks search selection, project import, duplicate reporting, paging/cache, empty results, rate-limit messages, DOI lookup, imported-record screening and the previous review workflow.
- Python bytecode compilation and Git whitespace checks.

Developer commands for a normal installation:

```bash
npm ci
npm run typecheck
npm run build
npm test
npm run test:ui
REDREVIEW_UI_ORIGIN=http://100.64.0.10:8844 npm run test:ui
python3 -m compileall -q src tests scripts
```

The sandbox lacked registry access; installed TypeScript 5.9.3 and jsdom 26.1.0 tools from another workspace were used without copying their source into this project. UI tests support `REDREVIEW_JSDOM=/absolute/path/to/jsdom/lib/api.js` for that fallback.

## Blocked / unverified

- Live Crossref, OpenAlex and PubMed keyword searches and DOI lookups: **all six attempted requests failed because backend outbound networking is restricted**. No live provider/import success is claimed. Repeat `python3 scripts/check-live-providers.py` outside the sandbox; it imports into a temporary project, reimports to check duplicates, then removes that temporary database.
- Live HTTP tests: creating sockets raises `Operation not permitted`; equivalent handlers passed byte-stream checks.
- Local startup and restart: both `python3 -m src.server --port 8845` and `python3 scripts/start-tailscale.py --restart` were attempted; sockets are prohibited. The saved Tailscale authority and existing PID state are retained. Restart outside Codex as documented in tailscale.md.
- Browser rendering and native PDF display: no browser-control tool or installed browser was available. jsdom tests verify DOM interactions, not visual layout, touch ergonomics or PDF rendering. Check desktop and iPhone directly.
- GitHub CLI: configured authentication is invalid and CLI network requests fail. The connected GitHub tool can inspect/write the repository; remote publication must be checked through that connection. See delivery status in the final handoff rather than inferring success from prepared workflows.

No public writable backend is deployed. Private-host service configuration is prepared, not installed or verified on a remote host. Authentication and user/project isolation remain prerequisites for public writable hosting.
