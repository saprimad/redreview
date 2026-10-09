# Website and private backend delivery

## GitHub Pages landing page

Only `site/` is uploaded by `.github/workflows/pages.yml`; no database, PDFs, fixtures or application endpoints are deployed. In repository Settings → Pages, select **GitHub Actions**, then run **Landing page** or push a change to `site/` on `main`. The expected URL is `https://saprimad.github.io/redreview/`. Check the workflow's successful deploy output and request that URL before reporting it live. The ZIP download links to GitHub's source archive, not an installer.

Pages cannot execute Python or provide SQLite persistence. The full app must run on a computer or backend-capable private host. This repository does not provision hosting or paid resources.

## Backend-capable host: private Linux VM / existing server

Prepared configuration: `deploy/redreview.service`. This runs one private workspace on loopback; reach it using an SSH tunnel or existing private network access. It is **not a public multi-user application**. Do not add a public port mapping or publish a writable endpoint. Local profiles, CSRF and Host/Origin guards are not user authentication. Authentication, authorisation and user/project isolation require implementation and verified cross-user access tests before public deployment. The standard-library HTTP transport also needs a production server/reverse-proxy assessment before that future deployment.

1. Install Python 3.11+ and Git; create a dedicated `redreview` system user with no login.
2. Clone the repository to `/opt/redreview`; let that user read the code. Keep it outside personal home folders because the service protects them.
3. Copy `deploy/redreview.service` to `/etc/systemd/system/redreview.service`.
4. Optionally create `/etc/redreview.env` (root-owned, mode 0600) with the variables below. Never store it in Git.
5. Run `sudo systemctl daemon-reload` and `sudo systemctl enable --now redreview`.
6. Verify on the host: `curl --fail http://127.0.0.1:8844/api/health`. Expect JSON containing `"app": "redreview"` and version `0.2.0`.
7. From your computer: `ssh -N -L 8844:127.0.0.1:8844 YOUR_PRIVATE_HOST`, then open `http://127.0.0.1:8844/`. Restrict SSH to authorised keys/users.

### Environment

| Variable | Purpose |
| --- | --- |
| REDREVIEW_CONTACT_EMAIL | Optional real contact for Crossref polite pool and NCBI tool identification. Queries/contact details go to the chosen provider. |
| OPENALEX_API_KEY | Optional free OpenAlex key, sent only by the backend in an Authorization header. No paid plan is configured. |
| NCBI_API_KEY | Optional NCBI key; requests remain below unkeyed limits by default. |

Python does not load `.env` automatically. For local use, export environment variables in the terminal that launches the backend. Tailscale helper children inherit them. Restart after changing keys. If using systemd, set them in its EnvironmentFile instead.

### Persistence and recovery

`/var/lib/redreview/redreview.sqlite3` is persistent storage; **PDF bytes also live inside SQLite**, not in a separate upload directory. Keep the entire `/var/lib/redreview` directory on a persistent host disk/volume across code deployments. Do not use an ephemeral container filesystem. The service runs as the dedicated user, requests a private 0700 state directory and 0077 umask. Preserve file ownership on restores.

Back up projects in the UI or stop the service and copy the SQLite file to private backup storage. Verify a restore to separate temporary storage. Restart with `sudo systemctl restart redreview` after updates, then check health. Keep personal data, API keys and backups out of container images, source archives and CI artifacts. Each workspace still has the existing 85 MiB per-project limit and 25 MiB per-PDF limit.

### Tailscale

The existing WSL/Windows setup is kept in `scripts/setup-tailscale.ps1` and `scripts/start-tailscale.py`. Personal addresses are stored only in ignored `.data/tailscale-config.json`. See [Tailscale instructions](tailscale.md). No public writable backend deployment has been performed or claimed.
