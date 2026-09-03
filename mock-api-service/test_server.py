import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server


class MockApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.request("POST", "/admin/reset")

    def request(self, method, path):
        req = Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        try:
            with urlopen(req, timeout=3) as resp:
                return resp.status, dict(resp.headers), json.loads(resp.read())
        except HTTPError as exc:
            return exc.code, dict(exc.headers), json.loads(exc.read())

    def test_health(self):
        status, _, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_source_a_page_pagination(self):
        status, _, body = self.request("GET", "/source-a/products?page=2")
        self.assertEqual(status, 200)
        self.assertEqual(body["page"], 2)
        self.assertEqual(body["total_pages"], 3)
        self.assertEqual(len(body["products"]), 2)

    def test_source_b_transient_failure_then_success(self):
        status, headers, _ = self.request("GET", "/source-b/products?cursor=cursor-2")
        self.assertEqual(status, 503)
        self.assertIn("Retry-After", headers)

        status, _, body = self.request("GET", "/source-b/products?cursor=cursor-2")
        self.assertEqual(status, 200)
        self.assertEqual(body["next_cursor"], "cursor-3")

    def test_reset_rearms_source_b_failure(self):
        self.request("GET", "/source-b/products?cursor=cursor-2")
        self.request("GET", "/source-b/products?cursor=cursor-2")
        self.request("POST", "/admin/reset")
        status, _, _ = self.request("GET", "/source-b/products?cursor=cursor-2")
        self.assertEqual(status, 503)

    def test_source_c_rate_limit(self):
        self.assertEqual(self.request("GET", "/source-c/products?offset=0&limit=2")[0], 200)
        self.assertEqual(self.request("GET", "/source-c/products?offset=2&limit=2")[0], 200)
        status, headers, body = self.request("GET", "/source-c/products?offset=4&limit=2")
        self.assertEqual(status, 429)
        self.assertIn("Retry-After", headers)
        self.assertEqual(body["error"], "rate_limited")

    def test_source_c_limit_validation(self):
        status, _, body = self.request("GET", "/source-c/products?offset=0&limit=50")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "bad_request")


if __name__ == "__main__":
    unittest.main()
