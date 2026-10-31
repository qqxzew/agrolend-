#!/usr/bin/env bash
# Runs every offline test: web syntax, gateway (starts real geo services as subprocesses), original geo suites, Node agent. No accounts, keys or payments needed.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"; [ -x "$PY" ] || PY=.venv-dev/bin/python
echo "== web syntax"; for f in web/js/*.js; do node --check "$f"; done
echo "== assistant conversations"; node --test web/tests/*.test.mjs
echo "== gateway"; "$PY" -m pytest gateway/tests -q
echo "== original geo suites"; (cd services/geo && for t in tests/test_*.py; do "../../$PY" "$t" >/dev/null && echo "ok $t"; done)
echo "== node agent"; (cd agent && npm test --silent 2>&1 | grep -E "^ℹ (tests|pass|fail)")
echo "ALL OFFLINE TESTS PASSED"
