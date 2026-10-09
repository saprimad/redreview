#!/usr/bin/env python3
"""Start the owned WSL process and verify HTTP locally, without opening a browser."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / '.data'
PORT = 8844
CONFIG = DATA / 'tailscale-config.json'
PUBLIC = ''


def healthy(bind):
    opener = build_opener(ProxyHandler({}))
    try:
        for authority in (f'{bind}:{PORT}', PUBLIC):
            req = Request(f'http://{bind}:{PORT}/api/health', headers={'Host': authority, 'Origin': f'http://{authority}'})
            with opener.open(req, timeout=1) as response:
                if response.status != 200 or json.load(response).get('app') != 'redreview':
                    return False
        with opener.open(Request(f'http://{bind}:{PORT}/', headers={'Host': PUBLIC}), timeout=1) as response:
            return response.status == 200 and b'<title>redreview' in response.read()
    except (OSError, ValueError):
        return False


def owned(pid):
    try:
        cmd = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        return b'src.server' in cmd and Path(f'/proc/{pid}/cwd').resolve() == ROOT
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--allow-host', help='Your Tailscale IPv4:8844; saved only in ignored local configuration.')
    parser.add_argument('--restart', action='store_true', help='Restart the owned server after code updates.')
    args = parser.parse_args()
    global PUBLIC
    sys.path.insert(0, str(ROOT))
    from src.server import validate_authority
    saved = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    PUBLIC = args.allow_host or saved.get('authority', '')
    if not PUBLIC:
        parser.error('Pass --allow-host YOUR_TAILSCALE_IP:8844 on first setup.')
    PUBLIC = validate_authority(PUBLIC)
    if PUBLIC.rsplit(':', 1)[1] != str(PORT):
        parser.error('The Tailscale helper uses port 8844.')
    if args.allow_host:
        DATA.mkdir(exist_ok=True)
        CONFIG.write_text(json.dumps({'authority': PUBLIC}))
    try:
        address = ipaddress.IPv4Address(args.bind)
        if address.is_unspecified or address.is_multicast:
            raise ValueError('A specific IPv4 bind address is required.')
    except ValueError as error:
        parser.error(str(error))
    DATA.mkdir(exist_ok=True)
    pidfile = DATA / 'server.pid.json'
    previous = {}
    if pidfile.exists():
        try:
            previous = json.loads(pidfile.read_text())
        except (ValueError, OSError):
            pass
    pid = previous.get('pid')
    if isinstance(pid, int) and owned(pid):
        if not args.restart and previous.get('bind') == args.bind and healthy(args.bind):
            print(f'Already running; local HTTP and Tailscale Host/Origin checks passed (PID {pid}).')
            return
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            if not owned(pid):
                break
            time.sleep(.1)
        else:
            raise SystemExit('Existing RedReview process did not stop; no replacement was started.')
    if healthy(args.bind):
        print('Existing RedReview listener verified locally, including Tailscale Host/Origin support.')
        return
    with (DATA / 'server.log').open('ab') as log:
        process = subprocess.Popen([sys.executable, '-m', 'src.server', '--port', str(PORT), '--bind', args.bind, '--allow-host', PUBLIC], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    for _ in range(50):
        if process.poll() is not None:
            raise SystemExit('RedReview did not start. Inspect .data/server.log (socket permissions or a port conflict may be responsible).')
        if healthy(args.bind):
            temp = pidfile.with_suffix('.tmp')
            temp.write_text(json.dumps({'pid': process.pid, 'bind': args.bind}))
            temp.replace(pidfile)
            print(f'Started RedReview PID {process.pid}; local HTTP and Tailscale Host/Origin checks passed.')
            return
        time.sleep(.2)
    os.kill(process.pid, signal.SIGTERM)
    raise SystemExit('Local HTTP verification failed; the newly started process was stopped. Inspect .data/server.log.')


if __name__ == '__main__':
    main()
