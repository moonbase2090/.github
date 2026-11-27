#!/usr/bin/env python3
"""Re-check the links lychee reported with a transient server error, then decide.

lychee 0.24 reports a 5xx answer from the first request and does not retry it. This
reads lychee's JSON report (`--format json --output FILE`) and asks again for every
link whose entry answered 500, 502, 503 or 504, in rounds that wait longer each time.
Each retry runs the same lychee command as the first check, one link at a time, so
the same accepted statuses, exclusions (private, loopback, link-local) and redirect
handling apply.

The run fails on any entry that is still broken afterwards, with one exception: a
github.com page that keeps answering 5xx is reported as a warning. GitHub answers a
burst of page requests from CI runners with 503 while the page exists; a page that
is gone answers 404, which still fails. Timeouts and every other status still fail,
each judged by its own entry in the report.

Usage: recheck_links.py REPORT.json LYCHEE [LYCHEE OPTIONS...]
The lychee options are the first check's options without its inputs.
"""
import json, os, subprocess, sys, tempfile, time
from urllib.parse import urlsplit

TRANSIENT = {500, 502, 503, 504}
PASSED = "passed"
LENIENT_HOSTS = frozenset({"github.com", "www.github.com"})
DELAYS = (2, 4, 8, 16)


def lychee_check(command, url):
    """Check one URL with the lychee command: PASSED, its failing HTTP status, or None.

    None means no answer (network error or timeout) or that the command did not check
    the URL, for example because it is excluded.
    """
    with tempfile.TemporaryDirectory() as work:
        page = os.path.join(work, "recheck.md")
        out = os.path.join(work, "recheck.json")
        with open(page, "w", encoding="utf-8") as f:
            f.write(f"<{url}>\n")
        proc = subprocess.run([*command, "--format", "json", "--output", out, "--", page],
                              capture_output=True, text=True)
        # lychee exits 2 for failed links and also for a usage error, which writes no report.
        if proc.returncode not in (0, 2) or not os.path.exists(out):
            raise RuntimeError(f"lychee exited {proc.returncode}: {proc.stderr.strip()}")
        with open(out, encoding="utf-8") as f:
            report = json.load(f)
    for _, _, code, _ in entries(report):
        return code
    if proc.returncode == 0 and report.get("total") == 1 and not report.get("excludes"):
        return PASSED
    return None


def recheck(urls, delays, check, sleep=time.sleep):
    """Ask again for every URL, one round per delay; map each URL to its last result.

    A URL leaves the rounds once it passes or gives a status that is not transient.
    """
    result = {url: None for url in urls}
    pending = list(urls)
    for delay in delays:
        if not pending:
            break
        sleep(delay)
        for url in pending:
            result[url] = check(url)
        pending = [url for url in pending if result[url] is None or result[url] in TRANSIENT]
    return result


def lenient(url, hosts=LENIENT_HOSTS):
    return (urlsplit(url).hostname or "") in hosts


def entries(report):
    """(source, url, status code or None, text) for every failed link in the report."""
    for key in ("error_map", "timeout_map"):
        for source, items in (report.get(key) or {}).items():
            for item in items:
                status = item.get("status") or {}
                yield source, item["url"], status.get("code"), status.get("text", "")


def main(argv, delays=DELAYS, sleep=time.sleep, hosts=LENIENT_HOSTS):
    if len(argv) < 3:
        print("usage: recheck_links.py REPORT.json LYCHEE [LYCHEE OPTIONS...]", file=sys.stderr)
        return 2
    report_path, command = argv[1], argv[2:]
    if not os.path.exists(report_path):
        print(f"lychee wrote no report at {report_path}; see its error above", file=sys.stderr)
        return 1
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    failed = list(entries(report))
    print(f"lychee: {report.get('total', 0)} links, {len(failed)} failed")
    transient = sorted({url for _, url, code, _ in failed if code in TRANSIENT})
    if transient:
        print(f"re-checking {len(transient)} link(s) that answered 5xx")
    final = recheck(transient, delays, lambda url: lychee_check(command, url), sleep)

    broken = 0
    for source, url, code, text in failed:
        if code not in TRANSIENT:
            print(f"[{source}] {url}: {text}")
            broken += 1
            continue
        status = final[url]
        if status == PASSED:
            print(f"[{source}] {url}: passed on a later try (first {code})")
        elif status in TRANSIENT and lenient(url, hosts):
            print(f"::warning::{source}: {url} still answers {status} from GitHub; counted as alive")
        else:
            print(f"[{source}] {url}: still failing ({status or 'no answer'}, first {code})")
            broken += 1
    if broken:
        print(f"{broken} broken link(s)")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
