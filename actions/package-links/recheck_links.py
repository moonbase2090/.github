#!/usr/bin/env python3
"""Re-check the links lychee reported with a transient server error, then decide.

lychee 0.24 reports a 5xx answer from the first request and does not retry it. This
reads lychee's JSON report (`--format json --output FILE`) and asks again for every
URL that answered 500, 502, 503 or 504, in rounds that wait longer each time.

The run fails on any link that is still broken afterwards, with one exception: a
github.com page that keeps answering 5xx is reported as a warning. GitHub answers a
burst of page requests from CI runners with 503 while the page exists; a page that
is gone answers 404, which still fails. Timeouts and every other status still fail.

Usage: recheck_links.py REPORT.json
"""
import json, sys, time, urllib.error, urllib.request
from urllib.parse import urlsplit

TRANSIENT = {500, 502, 503, 504}
ALIVE = set(range(200, 300)) | {403, 429}  # the statuses the lychee step accepts
LENIENT_HOSTS = frozenset({"github.com", "www.github.com"})
DELAYS = (2, 4, 8, 16)
UA = "moonbase2090-package-link-lint (https://github.com/moonbase2090/.github)"


def status_of(url, timeout=30):
    """The HTTP status for a GET of url after redirects, or None when no answer came."""
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        error.close()
        return error.code
    except (urllib.error.URLError, OSError):
        return None


def recheck(statuses, delays, sleep=time.sleep, fetch=status_of):
    """Ask again for every URL whose status is transient, one round per delay.

    `statuses` maps URL to the status lychee saw; the result maps URL to the last
    status seen. A URL leaves the rounds as soon as it gives a non-transient answer.
    """
    result = dict(statuses)
    pending = [url for url, status in result.items() if status in TRANSIENT]
    for delay in delays:
        if not pending:
            break
        sleep(delay)
        for url in pending:
            result[url] = fetch(url)
        pending = [url for url in pending if result[url] in TRANSIENT or result[url] is None]
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


def main(argv, delays=DELAYS, sleep=time.sleep, fetch=status_of, hosts=LENIENT_HOSTS):
    with open(argv[1], encoding="utf-8") as f:
        report = json.load(f)
    failed = list(entries(report))
    print(f"lychee: {report.get('total', 0)} links, {len(failed)} failed")
    transient = {url: code for _, url, code, _ in failed if code in TRANSIENT}
    if transient:
        print(f"re-checking {len(transient)} link(s) that answered 5xx")
    final = recheck(transient, delays, sleep, fetch)

    broken = 0
    for source, url, code, text in failed:
        if url not in final:
            print(f"[{source}] {url}: {text}")
            broken += 1
            continue
        status = final[url]
        if status in ALIVE:
            print(f"[{source}] {url}: answered {status} on a later try (first {code})")
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
