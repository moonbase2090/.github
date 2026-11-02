# Package and dead-link lint

A composite action used by every moonbase2090 repo.

1. **Package links** (`package_links.py`, stdlib Python 3.11+): every `docs.rs/<crate>`,
   `crates.io/crates/<crate>`, `npmjs.com/package/<pkg>` and `pypi.org/project/<pkg>` link in a
   tracked file (Rust: doc comments only) must point at a package that is published. The
   registries are queried at CI time, with retries; a registry that can't be reached is a warning,
   not a failure. Packages in the repo with `publish = false` or `"private": true` fail without a
   network call. Silence one line with `package-links: ignore`.
2. **Dead links** (lychee 0.24.2, downloaded and checksum-verified, so no third-party action is needed): external `http(s)` URLs in Markdown and `site/` must resolve.
   403 and 429 count as alive, loopback/private hosts are skipped, and requests are retried.

```yaml
- uses: actions/checkout@<sha>
- uses: moonbase2090/.github/actions/package-links@<sha>
```

Run the first check locally with `python3 actions/package-links/package_links.py` from a repo root.
