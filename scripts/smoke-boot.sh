#!/usr/bin/env bash
# Boot a real server against a channel.
#
#   scripts/smoke-boot.sh [channel]          # CI gate: require "Done (", then tear down
#   scripts/smoke-boot.sh --play [channel]   # dev server: stay up, joinable on localhost
#
# deps-check.py catches what mods DECLARE. This catches what they DO. Spark's
# bundled async-profiler segfaulted the JVM on Java 25 / aarch64 with a
# perfectly valid dependency graph, and ten restart loops on the production box
# were the first anyone knew of it.
#
# Java 25, matching the platform's compose file. A smoke test on a different
# runtime than production tests the wrong thing.
#
# --play is the pack development loop: same pack, same image, same runtime, but
# the server stays up and you can join it. Edit a .pw.toml, restart, see it in
# game. `packwiz serve` re-reads the working tree on every request, so there is
# nothing to publish and nothing to tag until you are happy.
set -euo pipefail

cd "$(dirname "$0")/.."

play=false
[ "${1:-}" = "--play" ] && { play=true; shift; }
channel="${1:-stable}"
packdir="pack/$channel"
[ -f "$packdir/pack.toml" ] || { echo "::error::no such channel: $channel"; exit 1; }

command -v packwiz >/dev/null || { echo "::error::packwiz is not on PATH"; exit 1; }
docker info >/dev/null 2>&1 || {
  echo "::error::the Docker daemon is not reachable, start Docker Desktop and retry"
  exit 1
}

# Docker Desktop routes --network host to its own Linux VM, whose localhost is
# not this machine's, so a container cannot see `packwiz serve` there. Plain
# Linux daemons (every CI runner) keep the original wiring untouched.
desktop=false
if docker info --format '{{.OperatingSystem}}' 2>/dev/null | grep -qi 'docker desktop'; then
  desktop=true
fi

mc=$(grep -m1 -oE '^minecraft *= *"[^"]+"' "$packdir/pack.toml" | grep -oE '"[^"]+"' | tr -d '"')
loader=$(grep -m1 -oE '^fabric *= *"[^"]+"' "$packdir/pack.toml" | grep -oE '"[^"]+"' | tr -d '"')
serve_port="${SMOKE_SERVE_PORT:-8080}"
timeout_s="${SMOKE_TIMEOUT:-900}"

if $play; then
  # A stable name so you can `docker logs`/`docker exec` it from another
  # terminal, and a named volume so the world outlives the container.
  name="wly-dev-$channel"
  volume="wly-dev-$channel-data"
  port="${PLAY_PORT:-25565}"   # host side
  inner=25565                  # container side, fixed
  # host.docker.internal rather than localhost: `--network host` is a
  # Linux-daemon feature, and on Docker Desktop the container's localhost is
  # its own. packwiz serve binds 0.0.0.0, so the gateway route reaches it.
  net=(-p "$port:$inner" --add-host=host.docker.internal:host-gateway)
  pack_host=host.docker.internal
  docker rm -f "$name" >/dev/null 2>&1 || true
else
  name="smoke-$channel-$$"
  volume=""
  port=25599
  inner=25599
  if $desktop; then
    net=(-p "$port:$inner" --add-host=host.docker.internal:host-gateway)
    pack_host=host.docker.internal
  else
    net=(--network host)   # unchanged: this is the CI gate's wiring
    pack_host=localhost
  fi
fi

cleanup() {
  if $play && docker ps -q --filter "name=^${name}$" | grep -q .; then
    # SIGTERM, not SIGKILL: itzg's entrypoint forwards it as a `stop` and the
    # server saves. `docker rm -f` here would discard whatever you just built.
    echo
    echo "=== stopping $name (saving the world, up to 90s)..."
    docker stop -t 90 "$name" >/dev/null 2>&1 || true
  fi
  docker rm -f "$name" >/dev/null 2>&1 || true
  [ -n "${logs_pid:-}" ] && kill "$logs_pid" 2>/dev/null || true
  [ -n "${serve_pid:-}" ] && kill "$serve_pid" 2>/dev/null || true
}
# EXIT alone is not enough: bash does not run an EXIT trap for an UNCAUGHT
# fatal signal, and Ctrl-C is the documented way to stop --play. Catching INT
# and TERM to call `exit` routes both through the EXIT trap exactly once, so
# the server always gets its graceful stop and the port is always released.
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Serve the working tree, not the published site: the point is to catch a bad
# pack BEFORE it is published, which means testing what is about to ship.
# pushd rather than a ( ... ) subshell: with a subshell, $! is the subshell and
# packwiz survives the trap holding the port, so the NEXT run silently serves a
# stale directory or fails to bind.
pushd "$packdir" >/dev/null
packwiz serve --port "$serve_port" >/dev/null 2>&1 &
serve_pid=$!
popd >/dev/null
for _ in $(seq 30); do
  curl -sf "http://localhost:$serve_port/pack.toml" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf "http://localhost:$serve_port/pack.toml" >/dev/null || { echo "::error::packwiz serve did not come up"; exit 1; }

env=(
  -e EULA=TRUE -e TYPE=FABRIC -e VERSION="$mc" -e FABRIC_LOADER_VERSION="$loader"
  -e PACKWIZ_URL="http://$pack_host:$serve_port/pack.toml"
  -e MEMORY="${MC_MEMORY:-3G}"
  -e ONLINE_MODE=false
  -e SERVER_PORT="$inner"
  # spark ships server-side and starts a BACKGROUND async-profiler by default.
  # Its bundled async-profiler is 2.9 from 2022 and segfaults the JVM on Java 25
  # during startup, so without this the server dies before "Done (" and this
  # script correctly reports the pack as unbootable:
  #
  #   [Server thread/INFO]: Starting background profiler...
  #   SIGSEGV (0xb) ... spark-...-libasyncProfiler.so.tmp+0x270e9
  #
  # NOT an aarch64 problem, whatever it was first blamed on: that trace is from
  # a linux-amd64 CI runner. Java 25 is the variable, not the architecture.
  #
  # Disabling it leaves /spark tps working, because tick timing comes from
  # spark's own hook and never touches the native agent. The same flag is in
  # weloveyou.mc's docker-compose.yml and in its bench harness, deliberately:
  # everything that boots this pack has to boot it the same way, or CI proves a
  # server nobody runs.
  -e JVM_OPTS="-Dspark.backgroundProfiler=false"
)
if $play; then
  # Normal worldgen: `stable` carries Terralith, and a flat world tests none of
  # it. No JVM flags, nothing in jvm-profiles.toml has been benched yet, and a
  # dev server is the wrong place to inherit an unmeasured opinion.
  env+=(-e MOTD="weloveyou $channel (dev)" -e VIEW_DISTANCE="${PLAY_VIEW_DISTANCE:-10}")
  mount=(-v "$volume:/data")
else
  env+=(-e LEVEL_TYPE=flat -e USE_AIKAR_FLAGS=true)
  mount=()
fi

echo "=== booting $channel (minecraft $mc, fabric $loader) on java25"
docker run -d --name "$name" "${net[@]}" "${mount[@]}" "${env[@]}" \
  itzg/minecraft-server:java25 >/dev/null

deadline=$(( $(date +%s) + timeout_s ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  logs=$(docker logs "$name" 2>&1 || true)
  if grep -q 'Done (' <<<"$logs"; then
    echo "=== booted in $(grep -oE 'Done \([0-9.]+s\)' <<<"$logs" | head -1)"
    echo "    mods loaded: $(grep -oE 'Loading [0-9]+ mods' <<<"$logs" | tail -1)"
    if $play; then
      echo
      echo "    join at  localhost:$port   (offline mode, any username)"
      echo "    world    docker volume $volume, survives restarts"
      echo "    edit     pack/$channel/mods/*.pw.toml, then re-run to pick it up"
      echo "    Ctrl-C to stop and save."
      echo
      # Backgrounded + `wait`, not a foreground `docker logs`: bash defers trap
      # handlers until the current foreground command returns, so a signal
      # would not be acted on until the log stream ended on its own. Ctrl-C
      # survives that (it reaches the whole process group) but nothing else
      # does. `wait` is interruptible, so every stop path behaves the same.
      docker logs -f --tail 0 "$name" 2>&1 &
      logs_pid=$!
      wait "$logs_pid" || true
      exit 0
    fi
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
