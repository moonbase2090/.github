#!/usr/bin/env python3
"""Fail when a tracked file links to a package page for a package that is not published.

Checks docs.rs/<crate>, crates.io/crates/<crate>, npmjs.com/package/<pkg> and
pypi.org/project/<pkg> links against the live registries. Packages defined in this
repo with publish = false (Cargo) or "private": true (npm) fail without a network call.

Suppress one line with the marker `package-links: ignore`.
"""
import json, os, re, subprocess, sys, time, tomllib, urllib.error, urllib.request

EXTS = (".md", ".mdx", ".html", ".htm", ".astro", ".rs", ".ts", ".tsx", ".js", ".jsx",
        ".svelte", ".vue", ".txt", ".rst", ".toml", ".json", ".yml", ".yaml", ".py")
SKIP_DIRS = ("node_modules/", "vendor/", "target/", "dist/", ".git/")
NAME = r"[A-Za-z0-9][A-Za-z0-9_.\-]*"
PATTERNS = [
    ("crates", re.compile(r"https?://docs\.rs/(?:crate/)?(" + NAME + r")")),
    ("crates", re.compile(r"https?://(?:www\.)?crates\.io/crates/(" + NAME + r")")),
    ("npm", re.compile(r"https?://(?:www\.)?npmjs\.com/package/((?:@" + NAME + r"/)?" + NAME + r")")),
    ("pypi", re.compile(r"https?://pypi\.org/project/(" + NAME + r")")),
]
IGNORE = "package-links: ignore"
UA = "moonbase2090-package-link-lint (https://github.com/moonbase2090/.github)"


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    for p in out.decode().split("\0"):
        if p and p.endswith(EXTS) and not any(d in p for d in SKIP_DIRS):
            yield p


def lines_to_scan(path, text):
    # In Rust sources only doc comments carry user-facing links.
    for n, line in enumerate(text.splitlines(), 1):
        if path.endswith(".rs") and not line.lstrip().startswith(("///", "//!")):
            continue
        if IGNORE in line:
            continue
        yield n, line


def local_unpublished():
    """Packages defined here that are marked never-publish."""
    bad = {}
    for p in tracked_files():
        base = os.path.basename(p)
        try:
            if base == "Cargo.toml":
                pkg = tomllib.load(open(p, "rb")).get("package", {})
                if pkg.get("name") and pkg.get("publish") in (False, []):
                    bad[("crates", pkg["name"])] = f"{p} sets publish = false"
            elif base == "package.json":
                d = json.load(open(p))
                if d.get("name") and d.get("private") is True:
                    bad[("npm", d["name"])] = f'{p} sets "private": true'
        except Exception:
            continue
    return bad


def registry_url(kind, name):
    if kind == "crates":
        return f"https://crates.io/api/v1/crates/{name}"
    if kind == "npm":
        return "https://registry.npmjs.org/" + name.replace("/", "%2F")
    return f"https://pypi.org/pypi/{name}/json"


def published(kind, name):
    """True, False, or None when the registry could not be reached."""
    url = registry_url(kind, name)
    for attempt in range(4):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if kind == "crates":
                    body = json.load(r)
                    return bool(body.get("versions") or body.get("crate", {}).get("max_version"))
                return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            if e.code not in (403, 429) and e.code < 500:
                return None
        except Exception:
            pass
        time.sleep(2 ** attempt)
    return None


def main():
    local = local_unpublished()
    hits = {}
    for path in tracked_files():
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in lines_to_scan(path, text):
            for kind, rx in PATTERNS:
                for m in rx.finditer(line):
                    name = m.group(1).rstrip(".")
                    if kind == "crates" and name in ("crate", "releases", "search", "about"):
                        continue
                    hits.setdefault((kind, name), []).append(f"{path}:{n}: {m.group(0)}")
    failures, unknown = [], []
    for key in sorted(hits):
        kind, name = key
        if key in local:
            reason = local[key]
        else:
            ok = published(kind, name)
            if ok is None:
                unknown.append(key)
                continue
            if ok:
                continue
            reason = f"{name} is not published on {kind}"
        for where in hits[key]:
            failures.append(f"{where}\n    -> {reason}")
    for kind, name in unknown:
        print(f"warning: could not reach the {kind} registry for {name}; skipped", file=sys.stderr)
    print(f"package-links: checked {len(hits)} package link target(s)")
    if failures:
        print("error: links to unpublished packages (publish the package, or link the repo/README instead):")
        print("\n".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
