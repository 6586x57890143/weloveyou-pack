#!/usr/bin/env python3
"""Resolve every mod's declared dependencies, per side, before publishing.

    scripts/deps-check.py [channel ...]

Three of the four bugs that reached players on day one were a wrong `side`, and
pack-check.sh cannot catch any of them: it proves a side is DECLARED, never that
it is CORRECT. Two of the three broke the client, which cannot be booted
headlessly, so a server smoke test would have missed them too.

What actually catches them is reading what each jar declares it needs and
checking the set it ships alongside:

  - Oritech depends on athena, which we shipped client-only  -> server broke
  - Terralith depends on lithostitched, shipped server-only  -> client broke
  - C2ME depends on java >=25; Prism gives clients 21        -> client broke

Presence is checked, not version ranges. Fabric's range syntax is its own
project and presence already catches the failure mode we keep hitting. The java
requirement IS compared, because that one is a plain number and bit us.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Supplied by the loader or the game, never by a mod in the pack.
AMBIENT = {"minecraft", "java", "fabricloader", "fabric", "mixinextras"}

# What each side's launcher actually runs. Clients get whatever Prism selects
# for the Minecraft version, which is 21 for 1.21.1; the server is pinned by the
# image tag in the platform repo's compose file.
JAVA_BY_SIDE = {"client": 21, "server": 25}


def fail(msg: str) -> None:
    print(f"::error::{msg}")


def read_mod_ids(data: bytes) -> list[tuple[str, dict]]:
    """Return (modid, fabric.mod.json) for a jar and every jar nested in it.

    Fabric API is a bundle: its own fabric.mod.json declares a `jars` list, and
    every fabric-*-v1 module a pack depends on lives inside one of those. Miss
    the nesting and every mod appears to be missing its Fabric API modules.
    """
    found: list[tuple[str, dict]] = []
    try:
        z = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        return found
    if "fabric.mod.json" not in z.namelist():
        return found
    meta = json.loads(z.read("fabric.mod.json").decode("utf-8", "replace"))
    found.append((meta.get("id", "?"), meta))
    for entry in meta.get("jars", []):
        path = entry.get("file")
        if path and path in z.namelist():
            found.extend(read_mod_ids(z.read(path)))
    return found


def parse_meta(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    def grab(key: str) -> str | None:
        m = re.search(rf'^{key} *= *"([^"]+)"', text, re.M)
        return m.group(1) if m else None
    return {"name": grab("name"), "side": grab("side"), "url": grab("url"),
            "filename": grab("filename")}


def check(channel: str) -> int:
    pack = ROOT / "pack" / channel / "mods"
    entries = [parse_meta(p) for p in sorted(pack.glob("*.pw.toml"))]
    print(f"=== {channel}: {len(entries)} entries")

    cache: dict[str, list[tuple[str, dict]]] = {}
    problems = 0

    for side in ("client", "server"):
        shipped = [e for e in entries if e["side"] in (side, "both")]
        provided: dict[str, str] = {}
        metas: list[tuple[str, dict]] = []

        for e in shipped:
            if e["url"] not in cache:
                with urllib.request.urlopen(e["url"], timeout=120) as r:
                    cache[e["url"]] = read_mod_ids(r.read())
            for modid, meta in cache[e["url"]]:
                provided[modid] = meta.get("version", "?")
                for pid in meta.get("provides", []):
                    provided[pid] = meta.get("version", "?")
            # Every nested module, not just the outer jar: C2ME declares its
                # java >=25 requirement inside c2me-opts-natives-math, so scanning
                # only the top level misses exactly the bug this exists to catch.
                metas.extend((e["name"], m) for _, m in cache[e["url"]])

        java_here = JAVA_BY_SIDE[side]
        # Deduped: a bundle repeats one constraint across every nested module,
        # and thirty identical lines hide the other problems.
        seen: set[str] = set()
        for name, meta in metas:
            for dep, constraint in (meta.get("depends") or {}).items():
                if dep == "java":
                    want = re.search(r"(\d+)", str(constraint))
                    if want and int(want.group(1)) > java_here:
                        seen.add(f"{channel}/{side}: {name} needs java "
                                 f">={want.group(1)}, but {side}s run java {java_here}")
                    continue
                if dep in AMBIENT or dep in provided:
                    continue
                seen.add(f"{channel}/{side}: {name} depends on '{dep}' "
                         f"({constraint}), which is not shipped to {side}s "
                         f"- check its side field")

        for msg in sorted(seen):
            fail(msg)
        missing = len(seen)
        status = "OK" if not missing else f"{missing} unmet"
        print(f"  {side:6s} {len(shipped):2d} entries, {len(provided):3d} modules provided  {status}")
        problems += missing

    return problems


def main() -> int:
    channels = sys.argv[1:] or sorted(
        p.name for p in (ROOT / "pack").iterdir() if p.is_dir())
    return 1 if sum(check(c) for c in channels) else 0


if __name__ == "__main__":
    raise SystemExit(main())
