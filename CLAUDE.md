# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

## What this is

`weloveyou-pack` — the modpack itself, plus the Prism Launcher instance templates that
deliver it. Fabric, packwiz-managed, published to Cloudflare R2.

The platform that runs the server and the Discord bot lives in a separate repository,
`weloveyou.mc`. This one ships content; that one ships code. They are split because the
cadences differ — a pack release is weekly and touches no Go.

**Status: phase 3 (client distribution).** `stable` is a representative skeleton, not the
finished pack. Nothing published yet.

## Layout

```
pack/stable/          packwiz pack — MC 1.21.1 Fabric
pack/edge/            MC 26.2 Fabric + Create Fly (later)
instance/stable/      Prism instance template, zipped by CI
  instance.cfg        OverrideCommands + PreLaunchCommand + memory
  mmc-pack.json       net.minecraft + net.fabricmc.fabric-loader components
  .minecraft/packwiz-installer.jar   pinned, hash-checked before every build
channels.toml         where each channel publishes to
scripts/              CI helpers that must also run by hand
```

## Commands

```bash
scripts/pack-check.sh              # side invariant + reachability
scripts/pack-check.sh --full       # also downloads and hashes everything (slow)
python scripts/instance-build.py   # build every channel's instance zip into dist/
python scripts/instance-build.py stable

cd pack/stable && packwiz refresh              # after ANY pack edit
cd pack/stable && packwiz modrinth add <slug>  # add a mod
cd pack/stable && packwiz modrinth export -o ../../dist/weloveyou-stable.mrpack
```

`packwiz` must be on PATH. CI pins it to an exact pseudo-version because the project
publishes no tags.

## Releasing

`git tag stable-v1.4.2 && git push origin stable-v1.4.2`. That validates the channel with
full hash verification, builds the instance zip and `.mrpack`, and syncs three things to R2:
the immutable `pack/stable/v1.4.2/` prefix, the rolling `pack/stable/` prefix, and the
launcher artifacts.

Immutable is written first on purpose. If the rolling prefix were updated first and the run
then failed, players would be pointed at a version with no permanent copy to roll back to.

**Rollback** is repointing the rolling prefix at a previous `v{version}`. That only works
because every release also lands somewhere immutable.

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
- **Write files with bash heredocs.** Python read_text/write_text use the Windows locale
  codec by default and will silently mangle every em-dash into a byte no UTF-8 parser
  accepts. If Python is unavoidable, pass `encoding="utf-8", newline="\n"`.
- **CI uses no third-party actions** outside `actions/*`.
- Run `packwiz refresh` after every pack edit, or CI will reject the stale index.
