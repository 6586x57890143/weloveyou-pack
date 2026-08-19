#!/usr/bin/env python3
"""Build the Prism Launcher instance zip for a pack channel.

    scripts/instance-build.py stable [--out dist]

Produces dist/weloveyou-<channel>.zip, ready to publish to Cloudflare Pages. A player adds an
instance from that URL and every launch afterwards syncs the pack.

Three things are checked before anything is zipped, because each has failed
quietly somewhere before:

1. The committed packwiz-installer.jar matches its pinned sha256. This jar runs
   on every player's machine at every launch.
2. mmc-pack.json and pack.toml agree on the Minecraft and Fabric versions. If
   they drift, the launcher runs a loader the pack was not built against, and
   the failure surfaces as confusing mod crashes rather than as a version error.
3. The pack URL placeholder was actually substituted. Shipping a zip that still
   says @PACK_URL@ would give every player an instance that cannot update.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "@PACK_URL@"


def fail(msg: str) -> None:
    print(f"::error::{msg}", file=sys.stderr)
    raise SystemExit(1)


def check_pinned_jar(instance_dir: Path) -> None:
    """The jar is committed, not downloaded. Prove it is the one we pinned."""
    jar = instance_dir / ".minecraft" / "packwiz-installer.jar"
    pin = ROOT / "instance" / "packwiz-installer.jar.sha256"
    if not jar.exists():
        fail(f"{jar} is missing; see instance/README.md")
    if not pin.exists():
        fail(f"{pin} is missing, so the jar cannot be verified")

    want = pin.read_text(encoding="utf-8").split()[0]
    got = hashlib.sha256(jar.read_bytes()).hexdigest()
    if got != want:
        fail(
            f"packwiz-installer.jar does not match its pin\n"
            f"  expected {want}\n"
            f"  got      {got}\n"
            f"If you bumped it deliberately, update instance/packwiz-installer.jar.sha256."
        )
    print(f"  jar pinned and verified ({got[:12]})")


def check_versions(instance_dir: Path, pack_dir: Path) -> None:
    """mmc-pack.json is what the launcher installs; pack.toml is what the pack
    was built against. They must not drift apart."""
    mmc = json.loads((instance_dir / "mmc-pack.json").read_text(encoding="utf-8"))
    with (pack_dir / "pack.toml").open("rb") as fh:
        pack = tomllib.load(fh)

    versions = pack.get("versions", {})
    want = {
        "net.minecraft": versions.get("minecraft"),
        "net.fabricmc.fabric-loader": versions.get("fabric"),
    }
    got = {c["uid"]: c["version"] for c in mmc["components"]}

    for uid, expected in want.items():
        if expected is None:
            fail(f"pack.toml declares no version for {uid}")
        if uid not in got:
            fail(f"mmc-pack.json has no {uid} component")
        if got[uid] != expected:
            fail(
                f"version drift on {uid}: mmc-pack.json says {got[uid]}, "
                f"pack.toml says {expected}"
            )
    print(f"  versions agree (minecraft {want['net.minecraft']}, "
          f"fabric {want['net.fabricmc.fabric-loader']})")


def pack_url(channel: str) -> str:
    """One source of truth on the pack side. The platform repo carries the same
    URL in wly.toml so the daemon can poll it; the builder never reads that."""
    with (ROOT / "channels.toml").open("rb") as fh:
        channels = tomllib.load(fh)
    if channel not in channels:
        fail(f"channels.toml has no [{channel}] section")
    url = channels[channel].get("pack_url")
    if not url:
        fail(f"[{channel}] in channels.toml has no pack_url")
    return url


def build(channel: str, out_dir: Path) -> Path:
    instance_dir = ROOT / "instance" / channel
    pack_dir = ROOT / "pack" / channel
    if not instance_dir.is_dir():
        fail(f"no instance template at {instance_dir}")
    if not pack_dir.is_dir():
        fail(f"no pack at {pack_dir}")

    print(f"=== {channel}")
    check_pinned_jar(instance_dir)
    check_versions(instance_dir, pack_dir)

    url = pack_url(channel)
    print(f"  pack url {url}")

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"weloveyou-{channel}.zip"

    substituted = False
    # Deterministic: sorted paths and a fixed timestamp, so rebuilding the same
    # commit produces the same bytes. Same reasoning as -trimpath on the Go side.
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(instance_dir.rglob("*")):
            if not path.is_file():
                continue
            arc = path.relative_to(instance_dir).as_posix()
            data = path.read_bytes()
            if path.suffix == ".cfg" and PLACEHOLDER.encode() in data:
                data = data.replace(PLACEHOLDER.encode(), url.encode())
                substituted = True
            info = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)

    if not substituted:
        out.unlink(missing_ok=True)
        fail(f"{PLACEHOLDER} was never found in {channel}'s instance.cfg — "
             "the zip would ship without a working pack URL")

    # Read it back. A zip that does not contain what Prism looks for is worse
    # than no zip, and the check costs nothing.
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        for required in ("instance.cfg", "mmc-pack.json", ".minecraft/packwiz-installer.jar"):
            if required not in names:
                fail(f"built zip is missing {required}")
        cfg = z.read("instance.cfg").decode("utf-8")
        if PLACEHOLDER in cfg:
            fail("built zip still contains the URL placeholder")
        if url not in cfg:
            fail("built zip does not contain the pack URL")

    print(f"  wrote {out.relative_to(ROOT).as_posix()} "
          f"({out.stat().st_size // 1024} KiB, {len(names)} entries)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("channels", nargs="*", default=None,
                    help="channels to build (default: every one under instance/)")
    ap.add_argument("--out", default="dist", help="output directory")
    args = ap.parse_args()

    channels = args.channels or sorted(
        p.name for p in (ROOT / "instance").iterdir() if p.is_dir()
    )
    if not channels:
        fail("no channels found under instance/")

    for channel in channels:
        build(channel, ROOT / args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
