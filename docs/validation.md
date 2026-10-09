# Validation — version 0.2

Validation date: 2026-10-09. Python 3.14.4 and Node 22.22.1 were available. Tests use temporary SQLite databases and test-only provider fixtures; personal reviews and PDFs are not test inputs.

## Passed

- TypeScript strict typecheck and compilation of `web/app.ts` to checked-in `web/app.js`.
- Python suite: **38 tests, 35 passed, 3 live-socket tests skipped**. Tests cover provider parsing, absent metadata, DOI lookup request construction, filters, pagination, caching, snapshot selection, rate-limit handling, API-key redaction, import reports, DOI/PMID/provider-ID duplicates, uncertain title/year matches and existing review workflows.
- Existing review regressions: independent/blinded decisions, adjudication, immutable history, chart status/version handling, RIS/BibTeX/CSV imports, PDF attachment, merge/undo, exports, backup/restore, archiving and project boundaries.
- Compiled UI interaction suite via jsdom and the actual Python handlers through byte streams, at both loopback and a **synthetic** Tailscale authority. Checks search selection, project import, duplicate reporting, paging/cache, empty results, rate-limit messages, DOI lookup, imported-record screening and the previous review workflow.
- Python bytecode compilation and Git whitespace checks.
- [GitHub CI on Python 3.11 and 3.14](https://github.com/saprimad/redreview/actions/runs/37938077915): **all 38 backend tests passed**, including live socket transport, plus typecheck, reproducible compiled JS and both DOM suites.
- Live backend requests on the GitHub runner: keyword and DOI searches passed for Crossref, OpenAlex and PubMed. Each provider returned real records; imports into temporary storage and duplicate reimports passed. DOI/PMID deduplication also skipped overlapping records across providers.
- Real Chrome at 1440×1000 and an emulated 390×844 mobile viewport passed search, selection/import and screening, with no horizontal overflow and a 44px search button target. Synthetic screenshots are attached to the CI run as `synthetic-browser-qa`. This does not establish Safari-specific PDF support or actual iPhone connectivity.

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

- Live Crossref, OpenAlex and PubMed keyword searches and DOI lookups: **all six local attempts failed because backend outbound networking is restricted**. Subsequent GitHub-runner requests succeeded as described above. Repeat `python3 scripts/check-live-providers.py` outside the sandbox; it imports into a temporary project, reimports to check duplicates, then removes that temporary database.
- Live HTTP tests: creating sockets raises `Operation not permitted`; equivalent handlers passed byte-stream checks.
- Local startup and restart: both `python3 -m src.server --port 8845` and `python3 scripts/start-tailscale.py --restart` were attempted; sockets are prohibited. The saved Tailscale authority and existing PID state are retained. Restart outside Codex as documented in tailscale.md.
- Local browser and native PDF display: no local browser-control tool or installed browser was available. Remote Chrome layout/interaction checks passed; Safari-specific PDF rendering, actual touch ergonomics and iPhone connectivity remain unverified.
- GitHub CLI: configured authentication is invalid and CLI network requests fail. The connected GitHub tool published the complete source and verified the remote commit and matching source tree. Local main was synchronized using verified Git object hashes; origin is configured, without force-pushing. Earlier private history stays on a local private-history branch and must not be pushed with --all.

No public writable backend is deployed. Private-host service configuration is prepared, not installed or verified on a remote host. Authentication and user/project isolation remain prerequisites for public writable hosting.

## Landing page delivery

The Pages workflow was committed and executed. [Its first run](https://github.com/saprimad/redreview/actions/runs/37937456780) failed at configure-pages because repository Pages is not enabled. Select **GitHub Actions** in repository Settings → Pages, then rerun the job. The connected tools cannot change that setting and the CLI is blocked. Until a successful deployment and URL response are checked, `https://saprimad.github.io/redreview/` is an expected URL, not a verified live site.
