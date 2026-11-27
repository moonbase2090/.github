#!/usr/bin/env bash
# Dead-link check: run lychee once over the inputs, then re-check 5xx answers.
#
# usage: dead_links.sh LYCHEE [EXTRA LYCHEE OPTIONS...] -- INPUTS...
#
# The first pass and every retry in recheck_links.py run the same lychee command, so
# the same exclusions, accepted statuses and redirect handling apply to each request.
# Each call writes its report into a fresh directory, so a second call in the same job
# never reads an earlier call's report.
set -euo pipefail

lychee=$1
shift
extra=()
while [ $# -gt 0 ] && [ "$1" != "--" ]; do
  extra+=("$1")
  shift
done
[ "${1:-}" = "--" ] && shift

checker=("$lychee" --no-progress
  --scheme https --scheme http
  --root-dir "${GITHUB_WORKSPACE:-$PWD}"
  --max-retries 4 --retry-wait-time 5 --timeout 30 --max-concurrency 8
  --accept '200..=299,403,429'
  --exclude-loopback --exclude-private --exclude-link-local
  --exclude '^https?://(www\.)?example\.(com|org)'
  --exclude '^https?://github\.com/.*/(edit|compare|new)/'
  --exclude-path node_modules --exclude-path target --exclude-path third_party
  --exclude-path CHANGELOG.md
  ${extra[@]+"${extra[@]}"})

work=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/dead-links.XXXXXX")
trap 'rm -rf "$work"' EXIT
report="$work/report.json"

# lychee does not retry a 5xx answer; recheck_links.py asks again with backoff.
status=0
"${checker[@]}" --format json --output "$report" "$@" || status=$?
# 2 means some links failed (or a usage error, which writes no report); any other
# non-zero status is a lychee error.
case "$status" in
  0|2) python3 "$(dirname "$0")/recheck_links.py" "$report" "${checker[@]}" ;;
  *) exit "$status" ;;
esac
