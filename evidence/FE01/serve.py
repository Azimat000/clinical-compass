"""Loopback-only, allowlisted read-only preview. No live database or write routes."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
PROTO = ROOT/'docs/design/prototypes/FE01'

class Preview(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = urlsplit(path).path
        aliases = {'/': '/signals.html', '/demo/P201': '/diagnosis.html', '/patients/P201/decisions': '/plan.html'}
        path = aliases.get(path, path)
        base = ROOT/'apps/compass/static' if path.startswith('/static/') else PROTO
        rel = path[len('/static/'):] if path.startswith('/static/') else path.lstrip('/')
        value = (base/rel).resolve()
        return str(value if value.is_relative_to(base.resolve()) else PROTO/'missing')

    def end_headers(self):
        self.send_header('Content-Security-Policy', "default-src 'self'; object-src 'none'; base-uri 'self'; form-action 'none'")
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, *args):
        pass

if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8061), Preview).serve_forever()
