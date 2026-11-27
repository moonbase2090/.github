"""Tests for dead_links.sh, the action's dead-link step, run with the real lychee binary.

Run from the repo root with LYCHEE set to a lychee 0.24.2 binary:
    LYCHEE=/path/to/lychee python3 -m unittest discover -s actions/package-links/tests
"""
import http.server, os, subprocess, tempfile, threading, unittest

LYCHEE = os.environ.get("LYCHEE")
STEP = os.path.join(os.path.dirname(__file__), "..", "dead_links.sh")


class Handler(http.server.BaseHTTPRequestHandler):
    hits = []

    def do_GET(self):
        Handler.hits.append(self.path)
        self.send_response(503)
        self.end_headers()

    do_HEAD = do_GET

    def log_message(self, *args):
        pass


@unittest.skipUnless(LYCHEE, "set LYCHEE to a lychee binary")
class DeadLinksStep(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.mkdtemp()
        self.runner_temp = tempfile.mkdtemp()
        Handler.hits.clear()

    def tearDown(self):
        subprocess.run(["rm", "-rf", self.workspace, self.runner_temp], check=True)

    def doc(self, text):
        with open(os.path.join(self.workspace, "doc.md"), "w", encoding="utf-8") as f:
            f.write(text + "\n")

    def step(self, *extra):
        env = dict(os.environ, RUNNER_TEMP=self.runner_temp, GITHUB_WORKSPACE=self.workspace)
        return subprocess.run(["bash", STEP, LYCHEE, *extra, "--", "./doc.md"], cwd=self.workspace,
                              env=env, capture_output=True, text=True)

    def test_a_second_call_with_a_bad_option_fails_after_a_passing_call(self):
        self.doc("[skipped](https://example.com/page)")
        first = self.step()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.step("--no-such-option")
        self.assertNotEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("lychee wrote no report", second.stderr)

    def test_a_bad_option_fails(self):
        self.doc("[skipped](https://example.com/page)")
        result = self.step("--no-such-option")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_lychee_runtime_error_fails(self):
        result = self.step()  # no doc.md: lychee exits 1 for the missing input
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("not found", result.stderr)

    def test_each_call_leaves_no_report_behind(self):
        self.doc("[skipped](https://example.com/page)")
        self.assertEqual(self.step().returncode, 0)
        self.assertEqual(os.listdir(self.runner_temp), [])

    def test_loopback_links_are_never_requested(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.doc(f"[local](http://127.0.0.1:{server.server_port}/page)")
        result = self.step()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(Handler.hits, [])


if __name__ == "__main__":
    unittest.main()
