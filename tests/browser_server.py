"""Temporary synthetic workspace for real-browser QA; never the personal database."""
import secrets
import sys
from http.server import ThreadingHTTPServer
from src.server import make_handler
from src.store import Store
from tests.transport import DISCOVERY
from tests.test_discovery import CROSSREF

if __name__ == '__main__':
    def fixture(provider, path, params=None, xml=False):
        return {'message': {'items': [CROSSREF], 'total-results': 1}}
    DISCOVERY.request = fixture
    store = Store(sys.argv[1])
    store.create('Browser test review')
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(store, secrets.token_urlsafe(32), discovery=DISCOVERY))
    print(server.server_port, flush=True)
    server.serve_forever()
