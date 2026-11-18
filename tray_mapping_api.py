"""接收跑合电脑推送的托盘坑位与 SN 映射。"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


class TrayMappingApiServer:
    def __init__(self, store, host="0.0.0.0", port=8765, token=""):
        self.store = store
        self.host = str(host)
        self.port = int(port)
        self.token = str(token)
        self.server = None
        self.thread = None

    def start(self):
        if self.server is not None:
            return
        store = self.store
        expected_token = self.token

        class Handler(BaseHTTPRequestHandler):
            def _write_json(self, status, payload):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/health":
                    self._write_json(200, {"status": "ok"})
                    return
                self._write_json(404, {"error": "not_found"})

            def do_POST(self):
                if self.path != "/api/v1/tray-mappings":
                    self._write_json(404, {"error": "not_found"})
                    return
                if expected_token and self.headers.get("X-Line-Token", "") != expected_token:
                    self._write_json(401, {"error": "unauthorized"})
                    return
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                    if content_length <= 0 or content_length > 128 * 1024:
                        raise ValueError("请求数据长度无效")
                    payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    batch = store.save_mapping_batch(payload)
                except Exception as error:
                    self._write_json(400, {"error": str(error)})
                    return
                self._write_json(
                    200,
                    {
                        "status": "saved",
                        "tray_cycle_id": batch["tray_cycle_id"],
                        "tray_id": batch["tray_id"],
                    },
                )

            def log_message(self, format_text, *args):
                return

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server is None:
            return
        self.server.shutdown()
        self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)
        self.server = None
        self.thread = None
