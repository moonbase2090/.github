"""Tests for recheck_links.py against a local HTTP server.

Run from the repo root: python3 -m unittest discover -s actions/package-links/tests
"""
import contextlib, http.server, io, json, os, sys, tempfile, threading, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import recheck_links  # noqa: E402


class Handler(http.server.BaseHTTPRequestHandler):
    hits = {}

    def do_GET(self):
        n = Handler.hits[self.path] = Handler.hits.get(self.path, 0) + 1
        if self.path == "/flaky":
            code = 503 if n == 1 else 200
        elif self.path == "/down":
            code = 503
        elif self.path == "/gone-later":
            code = 502 if n == 1 else 404
        elif self.path == "/gone":
            code = 404
        else:
            code = 200
        self.send_response(code)
        self.end_headers()

    def log_message(self, *args):
        pass


class RecheckLinks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Handler.hits.clear()
        self.waits = []

    def run_report(self, errors, timeouts=None, hosts=recheck_links.LENIENT_HOSTS):
        report = {"total": 9, "error_map": {"docs/a.md": errors}, "timeout_map": timeouts or {}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(report, f)
        self.addCleanup(os.unlink, f.name)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = recheck_links.main(["recheck", f.name], delays=(1, 2, 4),
                                      sleep=self.waits.append, hosts=hosts)
        return code, out.getvalue()

    def entry(self, path, code):
        return {"url": self.base + path, "status": {"code": code, "text": f"Rejected status code: {code}"}}

    def test_a_503_that_recovers_passes_after_retries(self):
        code, out = self.run_report([self.entry("/flaky", 503)])
        self.assertEqual(code, 0, out)
        self.assertEqual(Handler.hits["/flaky"], 2)  # one more 503, then 200
        self.assertEqual(self.waits, [1, 2])
        self.assertIn("answered 200 on a later try (first 503)", out)

    def test_a_404_fails_without_being_asked_again(self):
        code, out = self.run_report([self.entry("/gone", 404)])
        self.assertEqual(code, 1, out)
        self.assertNotIn("/gone", Handler.hits)
        self.assertEqual(self.waits, [])
        self.assertIn("1 broken link(s)", out)

    def test_a_5xx_that_turns_into_404_fails(self):
        code, out = self.run_report([self.entry("/gone-later", 502)])
        self.assertEqual(code, 1, out)
        self.assertIn("still failing (404, first 502)", out)

    def test_a_persistent_503_fails_on_a_host_that_is_not_lenient(self):
        code, out = self.run_report([self.entry("/down", 503)])
        self.assertEqual(code, 1, out)
        self.assertEqual(Handler.hits["/down"], 3)
        self.assertEqual(self.waits, [1, 2, 4])
        self.assertIn("still failing (503, first 503)", out)

    def test_a_persistent_503_is_a_warning_on_a_lenient_host(self):
        code, out = self.run_report([self.entry("/down", 503)], hosts={"127.0.0.1"})
        self.assertEqual(code, 0, out)
        self.assertEqual(Handler.hits["/down"], 3)
        self.assertIn("::warning::docs/a.md: " + self.base + "/down still answers 503", out)

    def test_a_404_still_fails_on_a_lenient_host(self):
        code, out = self.run_report([self.entry("/gone", 404)], hosts={"127.0.0.1"})
        self.assertEqual(code, 1, out)

    def test_a_timeout_fails(self):
        timeouts = {"docs/b.md": [{"url": self.base + "/ok", "status": {"text": "Timeout"}}]}
        code, out = self.run_report([], timeouts=timeouts)
        self.assertEqual(code, 1, out)
        self.assertIn("[docs/b.md] " + self.base + "/ok: Timeout", out)

    def test_one_broken_link_fails_the_run_even_when_others_recover(self):
        code, out = self.run_report([self.entry("/flaky", 503), self.entry("/gone", 404)])
        self.assertEqual(code, 1, out)
        self.assertIn("answered 200 on a later try", out)
        self.assertIn("1 broken link(s)", out)

    def test_github_hosts_are_lenient_and_lookalikes_are_not(self):
        self.assertTrue(recheck_links.lenient("https://github.com/o/r/blob/main/x.md"))
        self.assertTrue(recheck_links.lenient("https://www.github.com/o/r"))
        self.assertFalse(recheck_links.lenient("https://github.com.example.org/o/r"))
        self.assertFalse(recheck_links.lenient("https://notgithub.com/o/r"))
        self.assertFalse(recheck_links.lenient("https://raw.githubusercontent.com/o/r/main/x"))

    def test_status_of_reports_no_answer_as_none(self):
        self.assertIsNone(recheck_links.status_of("http://127.0.0.1:1/refused", timeout=5))


if __name__ == "__main__":
    unittest.main()
