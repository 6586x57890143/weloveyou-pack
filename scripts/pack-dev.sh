#!/usr/bin/env bash
# The pack development loop: change mods locally, see them on a real server.
#
#   scripts/pack-dev.sh add <slug> --side client|server|both [--channel stable]
#   scripts/pack-dev.sh rm  <slug>                           [--channel stable]
#   scripts/pack-dev.sh check                                [--channel stable]
#   scripts/pack-dev.sh play                                 [--channel stable]
#   scripts/pack-dev.sh list                                 [--channel stable]
#
# Nothing here resolves mods or downloads jars — packwiz does that, and the
# three validation scripts do the checking. This exists for one reason: to make
# `side` a required decision at the moment a mod is added.
#
# packwiz fills `side` in from Modrinth metadata, which describes what a mod
# DOES, not what depends on it. That distinction has caused every pack bug
# shipped so far: Oritech hard-depends on athena (Modrinth: client) and the
# server died; Terralith depends on lithostitched, shipped server-only, and the
# client died. So --side is mandatory and is written after packwiz has had its
# say. If you are unsure, `both` is the safe wrong answer — it costs TPS, not a
# crash.
#
# Publishing is unchanged and is not here: commit, then tag stable-v* and let
# CI publish. This loop is what you do BEFORE that.
set -euo pipefail

cd "$(dirname "$0")/.."

usage() { sed -n '2,8p' "$0" | sed 's/^# \?//'; exit "${1:-1}"; }

set_side() {
  local meta="$1" want="$2" was
  if grep -qE '^side *=' "$meta"; then
    was=$(grep -m1 -oE '^side *= *"[^"]+"' "$meta" | grep -oE '"[^"]+"' | tr -d '"')
    awk -v s="$want" '/^side *=/ { print "side = \"" s "\""; next } { print }' "$meta" > "$meta.tmp"
  else
    was="unset"
    awk -v s="$want" '/^filename *=/ && !d { print; print "side = \"" s "\""; d=1; next } { print }' "$meta" > "$meta.tmp"
  fi
  mv "$meta.tmp" "$meta"
  grep -qE '^side *= *"'"$want"'"' "$meta" || { echo "::error::failed to set side in $meta"; return 1; }
  if [ "$was" = "$want" ]; then
    echo "    ${meta#pack/*/} side=$want"
  else
    echo "    ${meta#pack/*/} side=$want (modrinth said $was)"
  fi
}

python_bin() {
  # `python` first: on Windows `python3` is often the App Execution Alias stub,
  # which opens the Microsoft Store instead of running anything.
  command -v python >/dev/null && { echo python; return; }
  command -v python3 >/dev/null && { echo python3; return; }
  echo "::error::python is not on PATH" >&2
  exit 1
}

cmd="${1:-}"
[ -z "$cmd" ] && usage 1
shift || true

channel=stable
side=""
slug=""
extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    --channel) channel="${2:?--channel needs a value}"; shift 2 ;;
    --side)    side="${2:?--side needs a value}"; shift 2 ;;
    -h|--help) usage 0 ;;
    -*)        extra+=("$1"); shift ;;
    *)         if [ -z "$slug" ]; then slug="$1"; else extra+=("$1"); fi; shift ;;
  esac
done

packdir="pack/$channel"
[ -f "$packdir/pack.toml" ] || { echo "::error::no such channel: $channel"; exit 1; }

case "$cmd" in

  add)
    [ -n "$slug" ] || { echo "::error::add needs a modrinth slug"; exit 1; }
    case "$side" in
      client|server|both) ;;
      "") echo "::error::add requires --side client|server|both"
          echo "   packwiz would take Modrinth's word for it, and Modrinth describes"
          echo "   what the mod does, not what depends on it. That is the bug that"
          echo "   killed the server twice. Decide, then pass --side."
          exit 1 ;;
      *)  echo "::error::--side must be client, server or both (got \"$side\")"; exit 1 ;;
    esac

    # Snapshot, so we can find whatever packwiz decided to call the metafiles
    # rather than guessing that they match the slug.
    before=$(find "$packdir" -name '*.pw.toml' | sort)
    ( cd "$packdir" && packwiz modrinth add "$slug" "${extra[@]+"${extra[@]}"}" )
    after=$(find "$packdir" -name '*.pw.toml' | sort)

    mapfile -t new < <(comm -13 <(echo "$before") <(echo "$after"))
    [ ${#new[@]} -eq 0 ] && { echo "::error::packwiz added no new metafile — is $slug already in the pack?"; exit 1; }

    # packwiz pulls dependencies in alongside the mod you asked for, and they
    # get the same side deliberately: a dependency has to ship wherever its
    # dependent ships. Oritech hard-depends on athena, Modrinth marks athena
    # client-only, and shipping it client-only is what killed the server.
    # Widen a dependency by hand afterwards if it genuinely needs both sides.
    for meta in "${new[@]}"; do
      set_side "$meta" "$side"
    done

    ( cd "$packdir" && packwiz refresh )
    echo "=== added ${#new[@]} file(s) to $channel, all side=$side"
    echo "    next: scripts/pack-dev.sh check --channel $channel"
    ;;

  rm|remove)
    [ -n "$slug" ] || { echo "::error::rm needs a mod name"; exit 1; }
    # packwiz remove deletes the metafile and refreshes the index itself.
    ( cd "$packdir" && packwiz remove "$slug" )
    echo "=== removed $slug from $channel"
    ;;

  check)
    # The fast gates only. pack-check.sh --full downloads every jar; that is a
    # release concern, and CI already does it.
    scripts/pack-check.sh
    "$(python_bin)" scripts/deps-check.py "$channel"
    echo "=== $channel passes structure and dependency checks"
    echo "    next: scripts/pack-dev.sh play --channel $channel"
    ;;

  play)
    # ponytail: on MSYS/Git Bash `exec` spawns a new pid instead of replacing
    # this one, so killing THIS pid orphans the server. Ctrl-C is unaffected —
    # it signals the whole process group — and that is the documented way to
    # stop it. Drop the exec and forward signals by hand if that stops being true.
    exec scripts/smoke-boot.sh --play "$channel"
    ;;

  list)
    ( cd "$packdir" && packwiz list )
    ;;

  -h|--help|help)
    usage 0
    ;;

  *)
    echo "::error::unknown command: $cmd"
    usage 1
    ;;
esac
