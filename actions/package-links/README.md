# Package and dead-link lint

A composite action used by every moonbase2090 repo.

1. **Package links** (`package_links.py`, stdlib Python 3.11+): every `docs.rs/<crate>`,
   `crates.io/crates/<crate>`, `npmjs.com/package/<pkg>` and `pypi.org/project/<pkg>` link in a
   tracked file (Rust: doc comments only) must point at a package that is published. The
   registries are queried at CI time, with retries; a registry that can't be reached is a warning,
   not a failure. Packages in the repo with `publish = false` or `"private": true` fail without a
   network call. Silence one line with `package-links: ignore`.
2. **Dead links** (lychee 0.24.2, downloaded and checksum-verified, so no third-party action is needed): external `http(s)` URLs in Markdown and `site/` must resolve.
   403 and 429 count as alive and loopback/private hosts are skipped. lychee does not retry a
   5xx answer, so the step (`dead_links.sh`) writes lychee's JSON report into a fresh directory
   for each call and `recheck_links.py` reads it and asks again for every link whose
   entry answered 500, 502, 503 or 504, in rounds 2, 4, 8 and 16 seconds apart. Each retry runs
   the same lychee command as the first pass, so the same exclusions and accepted statuses apply.
   A github.com page that still answers 5xx after that is a warning, because GitHub answers
   bursts of page requests from CI with 503; a 404, a timeout, or a 5xx from any other host fails
   the check. Tests: `LYCHEE=/path/to/lychee python3 -m unittest discover -s actions/package-links/tests`.

```yaml
- uses: actions/checkout@<sha>
- uses: moonbase2090/.github/actions/package-links@<sha>
```

Run the first check locally with `python3 actions/package-links/package_links.py` from a repo root.
