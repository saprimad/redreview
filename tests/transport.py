"""Exercise the real HTTP handler through byte streams, without opening sockets."""
import base64
import io
import json
import sys
from types import SimpleNamespace
from src.server import make_handler
from src.store import Store
from src.discovery import Discovery, ProviderError

DISCOVERY = Discovery()


class MemorySocket:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = bytearray()

    def makefile(self, *args, **kwargs):
        return self.input

    def sendall(self, data):
        self.output.extend(data)


def dispatch(store, token, path, data=None, headers=None, allowed_hosts=()):
    body = json.dumps(data).encode('utf-8') if data is not None else b''
    h = {'Host':'127.0.0.1:8844','Connection':'close','X-Redreview-Token':token, 'Content-Length':str(len(body)), 'Content-Type':'application/json'}
    h.update(headers or {})
    method = 'POST' if data is not None else 'GET'
    raw = (f'{method} {path} HTTP/1.1\r\n'+''.join(f'{k}: {v}\r\n' for k,v in h.items())+'\r\n').encode()+body
    socket = MemorySocket(raw)
    make_handler(store, token, allowed_hosts, DISCOVERY)(socket, ('127.0.0.1', 10000), SimpleNamespace(server_port=8844))
    head, payload = bytes(socket.output).split(b'\r\n\r\n', 1)
    lines = head.decode().split('\r\n')
    return int(lines[0].split()[1]), payload, dict(line.split(': ', 1) for line in lines[1:])


if __name__ == '__main__':
    import os
    if os.environ.get('REDREVIEW_TEST_DISCOVERY') == '1':
        # Explicit fixture only in the test pipe; never installed in the runtime server.
        from tests.test_discovery import CROSSREF
        def fixture_request(provider, path, params=None, xml=False):
            params = params or {}
            if params.get('query.bibliographic') == 'rate-limit-test':
                raise ProviderError('Fixture provider rate limit reached', 429, 60)
            if params.get('query.bibliographic') == 'empty-test':
                return {'message': {'items': [], 'total-results': 0}}
            if path.startswith('works/'):
                return {'message': CROSSREF}
            offset = params.get('offset', 0)
            items = [CROSSREF, dict(CROSSREF, DOI='10.1000/distinct', title=['A second supplied study title'], abstract=None)] if offset == 0 else [dict(CROSSREF, DOI='10.1000/next', title=['Next page article'])]
            return {'message': {'items': items, 'total-results': 21}}
        DISCOVERY.request = fixture_request
    store = Store(sys.argv[1])
    token = 'test-session-only'
    allowed_hosts = sys.argv[2:]
    for line in sys.stdin:
        try:
            request = json.loads(line)
            status, body, headers = dispatch(store, token, request['path'], request.get('data'), request.get('headers'), allowed_hosts)
            print(json.dumps({'status':status, 'body':base64.b64encode(body).decode(), 'headers':headers}), flush=True)
        except Exception as error:
            print(json.dumps({'error':str(error)}), flush=True)
