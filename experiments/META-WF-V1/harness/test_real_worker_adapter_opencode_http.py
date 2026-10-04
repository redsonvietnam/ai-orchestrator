import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ADAPTER_PATH = Path(__file__).with_name("real_worker_adapter.py")
SPEC = spec_from_file_location("real_worker_adapter", ADAPTER_PATH)
adapter = module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


class Handler(BaseHTTPRequestHandler):
    session_posts = 0
    message_posts = 0
    last_message = None

    def log_message(self, *_args):
        pass

    def send_json(self, value):
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/global/health":
            self.send_json({"healthy": True})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        body = json.loads(raw_body or b"{}")
        if self.path == "/session":
            type(self).session_posts += 1
            self.send_json({"id": "mock-session-1"})
            return
        if self.path == "/session/mock-session-1/message":
            type(self).message_posts += 1
            type(self).last_message = body
            self.send_json({"parts": [{"type": "text", "text": "MOCK_RESPONSE"}]})
            return
        self.send_response(404)
        self.end_headers()


class HTTPTransportTests(unittest.TestCase):
    def setUp(self):
        Handler.session_posts = 0
        Handler.message_posts = 0
        Handler.last_message = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.transport = adapter.OpenCodeHTTPTransport(
            executable="fixture-only", port=self.server.server_port, timeout=1
        )
        self.transport.process = object()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_session_message_text_model_agent_and_no_retry(self):
        text, _ = self.transport.execute(
            "PROMPT_FIXTURE", "fixture-provider", "fixture-model", "explore"
        )
        self.assertEqual(text, "MOCK_RESPONSE")
        self.assertEqual(Handler.session_posts, 1)
        self.assertEqual(Handler.message_posts, 1)
        self.assertEqual(self.transport.message_posts, 1)
        self.assertEqual(Handler.last_message["model"], {
            "providerID": "fixture-provider", "modelID": "fixture-model"
        })
        self.assertEqual(Handler.last_message["agent"], "explore")
        self.assertEqual(Handler.last_message["parts"], [
            {"type": "text", "text": "PROMPT_FIXTURE"}
        ])
        self.assertNotIn("noReply", Handler.last_message)

    def test_missing_session_id_fails_without_message_retry(self):
        original = self.transport._request
        calls = []

        def broken(method, path, body=None):
            calls.append((method, path))
            if path == "/session":
                return {}
            return original(method, path, body)

        self.transport._request = broken
        with self.assertRaises(adapter.ContractError):
            self.transport.execute("PROMPT", "p", "m", "explore")
        self.assertEqual(calls, [("POST", "/session")])
        self.assertEqual(Handler.message_posts, 0)


class ExtractionTests(unittest.TestCase):
    def test_parts_text_preserves_multiline(self):
        value = {
            "parts": [
                {
                    "type": "text",
                    "text": "A\nB",
                }
            ]
        }
        self.assertEqual(adapter.extract_response_text(value), "A\nB")


if __name__ == "__main__":
    unittest.main()
