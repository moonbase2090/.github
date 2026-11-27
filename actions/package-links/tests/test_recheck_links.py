"""Tests for recheck_links.py: the real lychee binary against a local HTTP server.

Run from the repo root with LYCHEE set to a lychee 0.24.2 binary:
    LYCHEE=/path/to/lychee python3 -m unittest discover -s actions/package-links/tests
Without LYCHEE the tests that run lychee are skipped.
"""
import contextlib, http.server, io, json, os, sys, tempfile, threading, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import recheck_links  # noqa: E402

LYCHEE = os.environ.get("LYCHEE")
needs_lychee = unittest.skipUnless(LYCHEE, "set LYCHEE to a lychee binary")


class Handler(http.server.BaseHTTPRequestHandler):
    hits = {}

    def do_GET(self):
        n = Handler.hits[self.path] = Handler.hits.get(self.path, 0) + 1
        code = {
            "/flaky": 503 if n == 1 else 200,
            "/down": 503,
            "/gone-later": 502 if n == 1 else 404,
            "/gone": 404,
            "/forbidden": 403,
        }.get(self.path, 200)
        self.send_response(code)
        self.end_headers()

    do_HEAD = do_GET

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

    def command(self, *extra):
        return [LYCHEE, "--no-progress", "--scheme", "http", "--timeout", "5",
                "--accept", "200..=299,403,429", *extra]

    def run_report(self, errors, timeouts=None, hosts=recheck_links.LENIENT_HOSTS, extra=()):
        report = {"total": 9, "error_map": errors, "timeout_map": timeouts or {}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(report, f)
        self.addCleanup(os.unlink, f.name)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = recheck_links.main(["recheck", f.name, *self.command(*extra)],
                                      delays=(1, 2, 4), sleep=self.waits.append, hosts=hosts)
        return code, out.getvalue()

    def entry(self, path, code):
        return {"url": self.base + path, "status": {"code": code, "text": f"Rejected status code: {code}"}}

    @needs_lychee
    def test_a_503_that_recovers_passes_after_retries(self):
        code, out = self.run_report({"docs/a.md": [self.entry("/flaky", 503)]})
        self.assertEqual(code, 0, out)
        self.assertEqual(Handler.hits["/flaky"], 2)  # one more 503, then 200
        self.assertEqual(self.waits, [1, 2])
        self.assertIn("passed on a later try (first 503)", out)

    @needs_lychee
    def test_a_404_fails_without_being_asked_again(self):
        code, out = self.run_report({"docs/a.md": [self.entry("/gone", 404)]})
        self.assertEqual(code, 1, out)
        self.assertNotIn("/gone", Handler.hits)
        self.assertEqual(self.waits, [])
        self.assertIn("1 broken link(s)", out)

    @needs_lychee
    def test_a_404_entry_fails_even_when_the_same_url_recovers_from_a_503_elsewhere(self):
        errors = {"docs/a.md": [self.entry("/flaky", 503)], "docs/b.md": [self.entry("/flaky", 404)]}
        code, out = self.run_report(errors)
        self.assertEqual(code, 1, out)
        self.assertIn(f"[docs/a.md] {self.base}/flaky: passed on a later try (first 503)", out)
        self.assertIn(f"[docs/b.md] {self.base}/flaky: Rejected status code: 404", out)
        self.assertIn("1 broken link(s)", out)

    @needs_lychee
    def test_a_5xx_that_turns_into_404_fails(self):
        code, out = self.run_report({"docs/a.md": [self.entry("/gone-later", 502)]})
        self.assertEqual(code, 1, out)
        self.assertIn("still failing (404, first 502)", out)

    @needs_lychee
    def test_a_persistent_503_fails_on_a_host_that_is_not_lenient(self):
        code, out = self.run_report({"docs/a.md": [self.entry("/down", 503)]})
        self.assertEqual(code, 1, out)
        self.assertEqual(Handler.hits["/down"], 3)
        self.assertEqual(self.waits, [1, 2, 4])
        self.assertIn("still failing (503, first 503)", out)

    @needs_lychee
    def test_a_persistent_503_is_a_warning_on_a_lenient_host(self):
        code, out = self.run_report({"docs/a.md": [self.entry("/down", 503)]}, hosts={"127.0.0.1"})
        self.assertEqual(code, 0, out)
        self.assertEqual(Handler.hits["/down"], 3)
        self.assertIn(f"::warning::docs/a.md: {self.base}/down still answers 503", out)

    @needs_lychee
    def test_a_404_still_fails_on_a_lenient_host(self):
        code, out = self.run_report({"docs/a.md": [self.entry("/gone", 404)]}, hosts={"127.0.0.1"})
        self.assertEqual(code, 1, out)

    @needs_lychee
    def test_retries_keep_the_checkers_exclusions(self):
        code, out = self.run_report({"docs/a.md": [self.entry("/flaky", 503)]},
                                    hosts={"127.0.0.1"}, extra=("--exclude-loopback",))
        self.assertEqual(Handler.hits, {})  # the excluded host is never asked again
        self.assertEqual(code, 1, out)
        self.assertIn("still failing (no answer, first 503)", out)

    @needs_lychee
    def test_a_status_the_checker_accepts_passes(self):
        self.assertEqual(recheck_links.lychee_check(self.command(), self.base + "/forbidden"),
                         recheck_links.PASSED)

    @needs_lychee
    def test_no_answer_is_none(self):
        self.assertIsNone(recheck_links.lychee_check(self.command(), "http://127.0.0.1:1/refused"))

    @needs_lychee
    def test_a_lychee_error_stops_the_check(self):
        with self.assertRaises(RuntimeError):
            recheck_links.lychee_check(self.command("--no-such-option"), self.base + "/ok")

    @needs_lychee
    def test_a_timeout_fails(self):
        timeouts = {"docs/b.md": [{"url": self.base + "/ok", "status": {"text": "Timeout"}}]}
        code, out = self.run_report({}, timeouts=timeouts)
        self.assertEqual(code, 1, out)
        self.assertIn(f"[docs/b.md] {self.base}/ok: Timeout", out)

    @needs_lychee
    def test_one_broken_link_fails_the_run_even_when_others_recover(self):
        code, out = self.run_report({"docs/a.md": [self.entry("/flaky", 503), self.entry("/gone", 404)]})
        self.assertEqual(code, 1, out)
        self.assertIn("passed on a later try", out)
        self.assertIn("1 broken link(s)", out)

    def test_a_missing_report_fails(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = recheck_links.main(["recheck", "/nonexistent/report.json", "lychee"])
        self.assertEqual(code, 1)
        self.assertIn("lychee wrote no report", err.getvalue())

    def test_github_hosts_are_lenient_and_lookalikes_are_not(self):
        self.assertTrue(recheck_links.lenient("https://github.com/o/r/blob/main/x.md"))
        self.assertTrue(recheck_links.lenient("https://www.github.com/o/r"))
        self.assertFalse(recheck_links.lenient("https://github.com.example.org/o/r"))
        self.assertFalse(recheck_links.lenient("https://notgithub.com/o/r"))
        self.assertFalse(recheck_links.lenient("https://raw.githubusercontent.com/o/r/main/x"))


if __name__ == "__main__":
    unittest.main()
