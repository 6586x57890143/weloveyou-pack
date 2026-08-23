# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

## What this is 💖

`weloveyou-pack` is the modpack itself, plus the Prism Launcher instance templates that
deliver it. Fabric, packwiz-managed, published to Cloudflare Pages.

The platform that runs the server and the Discord bot lives in a separate repository,
`weloveyou.mc`. This one ships content; that one ships code. They are split because the
cadences differ. A pack release goes out most weeks and never touches Go.

**Status: phase 3 (client distribution) verified end to end.** `stable` is a representative
skeleton, not the finished pack. Five releases are live (`v0.1.0` through `v0.1.4`) on Cloudflare
Pages; the immutable `v*` prefixes are retained on the `gh-pages` accumulator branch.

Verified on 2026-08-18 against a real Prism install and a local `packwiz serve`:
the zip imports, `OverrideCommands`/`PreLaunchCommand`/memory survive the import,
`mmc-pack.json` components stay intact, packwiz-installer downloads 17 client mods with the
exact shipped command, **skips Lithostitched as wrong-side**, deletes a mod removed from the
pack, and a re-sync restores exactly the client-side file set: no missing files, no extras.
The only unverified step is a full Minecraft launch, which needs a real account.

## Layout

```
pack/stable/          packwiz pack, MC 1.21.1 Fabric
pack/edge/            MC 26.2 Fabric + Create Fly (later)
instance/stable/      Prism instance template, zipped by CI
  instance.cfg        OverrideCommands + PreLaunchCommand + memory
  mmc-pack.json       net.minecraft + net.fabricmc.fabric-loader components
  .minecraft/packwiz-installer.jar   pinned, hash-checked before every build
channels.toml         where each channel publishes to
scripts/              CI helpers that must also run by hand
  pack-site.py        the endpoint's landing page, rendered into the rolling prefix
```

## Commands

The pack development loop, change mods, then join a real server running them. On Windows
run these from **Git Bash**, not WSL or PowerShell (see Conventions):

```bash
scripts/pack-dev.sh add sodium --side client   # --side is REQUIRED, see below
scripts/pack-dev.sh check                      # structure + per-side dependencies
scripts/pack-dev.sh play                       # boots a server; join localhost:25565
scripts/pack-dev.sh rm sodium
scripts/pack-dev.sh list
```

`play` serves the **working tree** over `packwiz serve` and boots the same
`itzg/minecraft-server:java25` image CI and production use, so what you join is what would
ship. The world lives in a `wly-dev-<channel>-data` docker volume and survives restarts;
Ctrl-C stops the server with SIGTERM so it saves. Nothing is published until you tag.

Add `--channel edge` to any of them. `PLAY_PORT`, `PLAY_VIEW_DISTANCE` and `MC_MEMORY`
override the defaults.

The underlying tools, if you need them directly:

```bash
scripts/pack-check.sh              # side invariant + reachability
scripts/pack-check.sh --full       # also downloads and hashes everything (slow)
python scripts/deps-check.py stable   # per-side dependency + java constraint resolution
scripts/smoke-boot.sh stable          # the CI gate: boot, require "Done (", tear down
python scripts/instance-build.py   # build every channel's instance zip into dist/
python scripts/instance-build.py stable
python scripts/pack-site.py stable --out /tmp/site   # the landing page, hits Modrinth
python scripts/pack-site.py stable --out /tmp/site --offline   # what CI runs

cd pack/stable && packwiz refresh              # after ANY pack edit
cd pack/stable && packwiz modrinth export -o ../../dist/weloveyou-stable.mrpack
```

To test the **client** path instead, point `channels.toml` at your `packwiz serve`, build the
zip, and `prismlauncher --import dist/weloveyou-stable.zip`.

`packwiz` must be on PATH. CI pins it to an exact pseudo-version because the project
publishes no tags.

## Releasing

`git tag stable-v1.4.2 && git push origin stable-v1.4.2`. That validates the channel with
full hash verification, builds the instance zip and `.mrpack`, and publishes three things to
Cloudflare Pages: the immutable `pack/stable/v1.4.2/` prefix, the rolling `pack/stable/`
prefix, and the launcher artifacts.

Pages Direct Upload replaces the whole deployment every time, so the `gh-pages` branch is the
accumulator that durably retains past `v*` prefixes, that branch is what makes rollback
possible, not the deployment.

Immutable is written first on purpose. If the rolling prefix were updated first and the run
then failed, players would be pointed at a version with no permanent copy to roll back to.

**Rollback** is repointing the rolling prefix at a previous `v{version}`. That only works
because every release also lands somewhere immutable.

## The endpoint has a page

`pack/stable/` on Pages is a directory of `.toml` files: correct, and unreadable to
whoever was handed the link. `scripts/pack-site.py` renders an `index.html` into the
rolling prefix at release time with the download buttons and the mod list.

- **It matches the benchmark site's design identity** (see `weloveyou.mc`
  `scripts/bench-site.py`, which writes the palette down for exactly this reason):
  monospace, dark, Minecraft's chat palette desaturated. Copied rather than shared,
  because a stylesheet common to two repos on two cadences is a third thing to publish.
- **Modrinth is called at BUILD time**, so the page has no runtime dependency on their
  API, no CORS question, and one request for everyone rather than one per visitor. A
  failed lookup warns and falls back to the pack's own name, filename and side.
  **Their outage must never fail a release.**
- **The buttons are driven by the files on disk**, so a missing artifact drops its button
  instead of publishing a link to a 404. The pinned `packwiz-installer.jar` is copied out
  beside the zip: it is the one thing here that executes on a player's machine, so it
  should be downloadable and checkable on its own.
- **Rolling prefix only.** The immutable `v{version}` prefixes carry no artifacts, so a
  page there would be three buttons pointing at nothing.
- **The site root is generated too** (`pack-site.py --root`), from the channels
  actually present under `pack/`. It used to be a hand-written placeholder saying
  nothing had been published yet, and it was still saying that two releases later.
- `ci.yml` renders both `--offline` on every PR. The platform repo learned that one the
  expensive way: nothing ran its generator until the publish did, so a crash in it
  surfaced as a red deploy after the merge meant to publish the numbers.

## The two invariants

**Every entry declares an explicit `side`.** An unset side defaults to both, which quietly
ships Sodium to the server and costs real TPS. `scripts/pack-check.sh` enforces it, verified
to fire on a missing side, an invalid side, and a stale index.

**`mmc-pack.json` and `pack.toml` agree on versions.** If they drift, the launcher installs a
loader the pack was not built against, and it surfaces as confusing mod crashes rather than a
version error. `scripts/instance-build.py` refuses to build on a mismatch.

## Decisions worth not relitigating

- **The pinned jar, not the bootstrap.** `packwiz-installer-bootstrap` downloads and executes
  a jar from GitHub on every launch, and last shipped in July 2020. We commit
  `packwiz-installer.jar` v0.5.14 with its sha256 instead. Known bytes, works offline, and
  the client path survives that repository going away.
- **`Main` is invoked directly**, not via `java -jar`. The jar's `Main-Class` is
  `RequiresBootstrap`, which exists only to refuse and point at the bootstrap. Hence
  `-cp packwiz-installer.jar link.infra.packwiz.installer.Main`.
- **Channels are separate instances**, not a switch inside one. Different Minecraft versions
  mean different `mmc-pack.json` components, and Prism cannot swap that underneath a running
  instance.
- **Importing an instance runs its pre-launch command, with no warning from Prism.**
  `InstanceImportTask::processMultiMC` does no sanitizing. That is how auto-update works, and
  it means this zip executes code on players' machines. Say so in the onboarding card; keep
  the jar pinned; never put anything in that command line a reader cannot verify.

## Conventions

- **Line endings are LF**, enforced by `.gitattributes`.
- **Windows checkouts drop the executable bit.** A new script committed from here lands as
  100644 and CI fails with `Permission denied` (exit 126). Fix with
  `git update-index --chmod=+x scripts/<name>`, and check `git ls-files -s scripts/` before
  pushing a new one.
- **On Windows, run the scripts from Git Bash, not WSL, not PowerShell.** `bash` on the
  PATH in PowerShell is the WSL launcher at `C:\WINDOWS\system32\bash.exe`, which fails
  outright without a real distro installed (`execvpe(/bin/bash) failed`); the
  `docker-desktop` entry in `wsl -l` is Docker's own utility VM, not one you can use. Git
  Bash is also where `packwiz` is on the PATH. To launch it from PowerShell, call it by
  full path:
  `& "C:\Program Files\Git\bin\bash.exe" -lc "cd /c/files/sdb/weloveyou-pack && scripts/pack-dev.sh play"`
  A real WSL distro would still need packwiz installed *inside* it: `packwiz serve` would
  bind WSL's network while the container resolves `host.docker.internal` to the Windows
  host, and the two would never meet.
- **Write files with bash heredocs.** Python read_text/write_text use the Windows locale
  codec by default and will silently mangle every em-dash into a byte no UTF-8 parser
  accepts. If Python is unavoidable, pass `encoding="utf-8", newline="\n"`.
- **CI uses no third-party actions** outside `actions/*`.
- Run `packwiz refresh` after every pack edit, or CI will reject the stale index.
