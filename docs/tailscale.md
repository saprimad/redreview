# Private iPhone access and restarting after updates

Your working Tailscale access uses the existing explicit Host/Origin allowlist and Windows/WSL forwarding. This update retains those checks, port 8844 and the database location. Personal addresses are saved in ignored `.data/tailscale-config.json`; no personal IP is included in public source.

## Existing configured installation

After updating, restart the owned backend from an unrestricted WSL terminal:

```bash
cd /path/to/redreview
python3 scripts/start-tailscale.py --restart
```

The helper reads your saved private Tailscale authority, restarts only its owned RedReview process and checks local health plus Tailscale Host/Origin handling. It leaves existing Windows firewall and portproxy configuration intact. If the backend previously required a specific WSL NAT address, keep that bind:

```bash
python3 scripts/start-tailscale.py --restart --bind YOUR_WSL_PRIVATE_IP
```

Then open your existing Tailscale URL on the iPhone with Tailscale connected. Backend health checks cannot establish that Safari PDF viewing and iPhone access actually work; verify those on the phone.

## First setup or changed WSL forwarding

From an unrestricted **Administrator Windows PowerShell** session:

```powershell
& '\\wsl.localhost\YOUR_DISTRO\home\YOUR_USER\redreview\scripts\setup-tailscale.ps1' -Distribution 'YOUR_DISTRO' -ProjectRoot '/home/YOUR_USER/redreview'
```

The script discovers the Windows Tailscale IPv4 address via `tailscale.exe ip -4`. You may pass `-TailscaleIP 'YOUR_TAILSCALE_IP'` explicitly. It confirms a Tailscale adapter and enabled firewall with default inbound blocking; verifies the backend before changing forwarding; and adds only its owned Tailscale-address/port firewall rule. It rejects unrelated wildcard listeners and routes it does not own. It uses loopback when Windows-to-WSL forwarding works, otherwise a specific private WSL NAT address when NAT mode is confirmed. Never replace these checks with a wildcard public bind.

You can configure only the WSL helper, preserving already-working forwarding:

```bash
python3 scripts/start-tailscale.py --allow-host YOUR_TAILSCALE_IP:8844 --restart
```

The configured authority is saved privately for later restarts. Optional API environment variables must be available to the Python process; Windows-triggered WSL launches may not inherit exports from another shell. For configured providers, restart directly from the shell containing those exports.

The setup script verifies HTTP through the Windows Tailscale address, but does not claim an iPhone check. Tailnet policy must allow your phone to reach the host's TCP 8844. Review projects/PDFs remain in the backend SQLite file; no phone copy or public hosting is created. Profiles are not accounts: give access only to trusted members of your private workspace.

The Codex sandbox currently blocks sockets and Windows interoperability. Run the commands above outside it; socket-restricted tests still exercise the same Host/Origin/CSRF handlers through byte streams.
