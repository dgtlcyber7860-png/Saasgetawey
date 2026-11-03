
# api/index.py — Vercel wrapper for existing handler
import sys
import os

# Add parent dir to path so we can import app.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import handler, CONFIG

# Vercel Python runtime expects a WSGI-compatible callable
def app(environ, start_response):
    """
    WSGI wrapper around BaseHTTPRequestHandler.
    Isse tumhara existing handler Vercel pe kaam karega.
    """
    # Build a fake request object from WSGI environ
    class FakeRequest:
        def __init__(self, environ):
            self.environ = environ
            self.command = environ.get('REQUEST_METHOD', 'GET')
            self.path = environ.get('PATH_INFO', '/')
            if environ.get('QUERY_STRING'):
                self.path += '?' + environ['QUERY_STRING']
            self.headers = environ
            self.rfile = environ.get('wsgi.input')
            self.wfile = None  # We'll capture response
            self.client_address = (environ.get('REMOTE_ADDR', '0.0.0.0'), 0)
            self.server = None
            self.request_version = 'HTTP/1.1'

        def send_response(self, code, message=None):
            self._status = code
            self._message = message or ''

        def send_header(self, keyword, value):
            if not hasattr(self, '_headers'):
                self._headers = []
            self._headers.append((keyword, value))

        def end_headers(self):
            pass

        def log_message(self, *args):
            pass

    # Create handler instance manually
    req = FakeRequest(environ)
    
    # Capture response by subclassing
    class CaptureHandler(handler):
        def __init__(self, request):
            self.request = request
            self.rfile = request.rfile
            self.wfile = None
            self.client_address = request.client_address
            self.server = request.server
            self.request_version = request.request_version
            self.command = request.command
            self.path = request.path
            self.headers = request.headers
            self._response_body = b''
            self._status_code = 200
            self._response_headers = []

        def send_response(self, code, message=None):
            self._status_code = code

        def send_header(self, keyword, value):
            self._response_headers.append((keyword, value))

        def end_headers(self):
            pass

        def wfile_write(self, data):
            self._response_body += data

        # Override _json to capture instead of write
        def _json(self, payload, status=200):
            import json
            b = json.dumps(payload, ensure_ascii=False, default=str).encode()
            self._status_code = status
            self._response_headers = [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Access-Control-Allow-Origin", "*"),
                ("Content-Length", str(len(b))),
            ]
            self._response_body = b

        def do_OPTIONS(self):
            self._status_code = 204
            self._response_headers = [
                ("Access-Control-Allow-Origin", "*"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Authorization"),
            ]
            self._response_body = b''

    try:
        h = CaptureHandler(req)
        if req.command == 'OPTIONS':
            h.do_OPTIONS()
        elif req.command == 'GET':
            h.do_GET()
        elif req.command == 'POST':
            h.do_POST()
        else:
            h._json({"status": "error", "message": "Method not allowed"}, 405)

        status = f"{h._status_code} OK"
        headers = h._response_headers + [("Content-Length", str(len(h._response_body)))]
        start_response(status, headers)
        return [h._response_body]
    except Exception as e:
        import json
        error_body = json.dumps({"status": "error", "message": str(e)}).encode()
        start_response("500 Internal Server Error", [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(error_body))),
        ])
        return [error_body]
