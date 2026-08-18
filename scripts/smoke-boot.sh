#!/usr/bin/env bash
# Boot a real server against a channel and require it to reach "Done (".
#
#   scripts/smoke-boot.sh [channel]     # default: stable
#
# deps-check.py catches what mods DECLARE. This catches what they DO. Spark's
# bundled async-profiler segfaulted the JVM on Java 25 / aarch64 with a
# perfectly valid dependency graph, and ten restart loops on the production box
# were the first anyone knew of it.
#
# Java 25, matching the platform's compose file. A smoke test on a different
# runtime than production tests the wrong thing.
set -euo pipefail

cd "$(dirname "$0")/.."
channel="${1:-stable}"
packdir="pack/$channel"
[ -f "$packdir/pack.toml" ] || { echo "::error::no such channel: $channel"; exit 1; }

mc=$(grep -m1 -oE '^minecraft *= *"[^"]+"' "$packdir/pack.toml" | grep -oE '"[^"]+"' | tr -d '"')
loader=$(grep -m1 -oE '^fabric *= *"[^"]+"' "$packdir/pack.toml" | grep -oE '"[^"]+"' | tr -d '"')
name="smoke-$channel-$$"
timeout_s="${SMOKE_TIMEOUT:-900}"

cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  [ -n "${serve_pid:-}" ] && kill "$serve_pid" 2>/dev/null || true
}
trap cleanup EXIT

# Serve the working tree, not the published site: the point is to catch a bad
# pack BEFORE it is published, which means testing what is about to ship.
( cd "$packdir" && packwiz serve --port 8080 >/dev/null 2>&1 ) &
serve_pid=$!
for _ in $(seq 30); do
  curl -sf http://localhost:8080/pack.toml >/dev/null 2>&1 && break
  sleep 1
done
curl -sf http://localhost:8080/pack.toml >/dev/null || { echo "::error::packwiz serve did not come up"; exit 1; }

echo "=== booting $channel (minecraft $mc, fabric $loader) on java25"
docker run -d --name "$name" --network host \
  -e EULA=TRUE -e TYPE=FABRIC -e VERSION="$mc" -e FABRIC_LOADER_VERSION="$loader" \
  -e PACKWIZ_URL="http://localhost:8080/pack.toml" \
  -e MEMORY=3G -e USE_AIKAR_FLAGS=true \
  -e ONLINE_MODE=false -e LEVEL_TYPE=flat \
  -e SERVER_PORT=25599 \
  itzg/minecraft-server:java25 >/dev/null

deadline=$(( $(date +%s) + timeout_s ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  logs=$(docker logs "$name" 2>&1 || true)
  if grep -q 'Done (' <<<"$logs"; then
    echo "=== booted in $(grep -oE 'Done \([0-9.]+s\)' <<<"$logs" | head -1)"
    echo "    mods loaded: $(grep -oE 'Loading [0-9]+ mods' <<<"$logs" | tail -1)"
    exit 0
  fi
  # Fail fast on the three ways this goes wrong, rather than burning the timeout.
  for pattern in 'Incompatible mods found' 'A fatal error has been detected' 'Failed to run packwiz installer'; do
    if grep -q "$pattern" <<<"$logs"; then
      echo "::error::$channel failed to boot: $pattern"
      grep -B2 -A12 "$pattern" <<<"$logs" | grep -vE '^\s+at ' | head -25
      exit 1
    fi
  done
  sleep 5
done

echo "::error::$channel did not reach 'Done (' within ${timeout_s}s"
docker logs --tail 40 "$name" 2>&1 | grep -vE '^\s+at ' || true
exit 1
