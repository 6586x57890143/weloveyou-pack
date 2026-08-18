# Prism instance templates

One directory per pack channel. CI zips these and publishes them to R2; a player
adds an instance from the resulting URL and never touches a file we built.

## What is pinned, and why

`.minecraft/packwiz-installer.jar` is committed, at v0.5.14, with its sha256 in
`packwiz-installer.jar.sha256`. `scripts/instance-build.sh` refuses to build if
they disagree.

The documented way to run packwiz-installer is through
`packwiz-installer-bootstrap`, which downloads the real jar from GitHub Releases
on every launch. We do not use it. Fetching and executing code at every launch is
the pattern worth avoiding regardless of who publishes it, the bootstrap's last
release was July 2020, and packwiz-installer itself last shipped in April 2024 —
so committing known bytes also means the client path survives that repository
disappearing.

The cost is bumping the jar by hand. Given one release in two years, that is not
a cost.

## Bumping the jar

```bash
curl -sSLo instance/stable/.minecraft/packwiz-installer.jar \
  https://github.com/packwiz/packwiz-installer/releases/download/vX.Y.Z/packwiz-installer.jar
sha256sum instance/stable/.minecraft/packwiz-installer.jar \
  | sed 's| .*| packwiz-installer.jar|' > instance/packwiz-installer.jar.sha256
```

Then launch it once against a scratch instance before committing. This jar runs
on every player's machine.
