#!/usr/bin/env bash
# Container entrypoint on the server: one Eve (loopback only) and exactly one worker. If either exits, the container exits
# and Docker restarts both, so the worker never runs without its model.
set -u
# This container is the only worker for its state volume; a lock left by the previous container names a PID that may be
# reused by an unrelated process here, so it is cleared before the single worker starts.
rm -f .local/worker.lock
node start.mjs &
eve=$!
for _ in $(seq 1 90); do
  node -e "fetch(process.env.EVE_URL,{signal:AbortSignal.timeout(2000)}).then(()=>process.exit(0),()=>process.exit(1))" && break
  kill -0 "$eve" 2>/dev/null || exit 1
  sleep 2
done
node worker.mjs &
worker=$!
wait -n "$eve" "$worker"
code=$?
kill "$eve" "$worker" 2>/dev/null
wait
exit "$code"
