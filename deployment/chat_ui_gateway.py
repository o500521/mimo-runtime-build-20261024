"""Updated local UI; reuses the running backend and its RAM-only credential."""
import http.server
import urllib.request
import urllib.error
from chat_local import HTML


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body, kind):
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path not in ('/', '/index.html'):
            return self.reply(404, b'Not found', 'text/plain')
        page = HTML.replace(
            '已選小米官方 API。請貼入完整 API Key 後檢查連線；尚未呼叫模型。',
            '沿用本機服務中的官方金鑰；可只選圖片送出，文字不必填寫。')
        self.reply(200, page.encode(), 'text/html; charset=utf-8')

    def do_POST(self):
        if self.path not in ('/chat', '/models'):
            return self.reply(404, b'Not found', 'text/plain')
        if self.headers.get('Origin') not in (None, 'http://127.0.0.1:8766', 'http://localhost:8766'):
            return self.reply(403, b'Origin not allowed', 'text/plain')
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(415, b'JSON required', 'text/plain')
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 12_000_000:
                raise ValueError('Invalid size')
            request = urllib.request.Request(
                'http://127.0.0.1:8765' + self.path,
                data=self.rfile.read(size),
                headers={'Content-Type': 'application/json', 'Origin': 'http://127.0.0.1:8765'})
            with urllib.request.urlopen(request, timeout=620) as response:
                self.reply(response.status, response.read(), 'application/json; charset=utf-8')
        except urllib.error.HTTPError as error:
            self.reply(error.code, error.read(), 'application/json; charset=utf-8')
        except ValueError:
            self.reply(400, b'{"error":"Invalid request size"}', 'application/json')
        except (urllib.error.URLError, TimeoutError):
            self.reply(502, '{"error":"本機模型連線服務未啟動。"}'.encode(), 'application/json; charset=utf-8')


if __name__ == '__main__':
    http.server.ThreadingHTTPServer(('127.0.0.1', 8766), Handler).serve_forever()
