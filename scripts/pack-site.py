#!/usr/bin/env python3
"""Render a channel's packwiz endpoint into a landing page.

    scripts/pack-site.py stable --out site/pack/stable

The published prefix is a directory of .toml files and two archives: correct,
and unreadable to a player who was handed the link. This puts an index.html
beside them with the download buttons and what is actually in the pack.

The page matches the benchmark site's design identity on purpose (see
weloveyou.mc scripts/bench-site.py, which writes the palette down for exactly
this reason): minimal, monospace, dark, Minecraft's chat palette desaturated.

Mod metadata comes from the Modrinth API at BUILD time, not from the browser.
Baking it means the page has no runtime dependency on an API being up, no CORS
question, and one HTTP request for everyone instead of one per visitor. A
Modrinth outage must never fail a release, so a failed lookup degrades to the
pack's own name, filename and side rather than raising.

Stdlib only, one file out, no external assets except the mod icons, which are
Modrinth CDN URLs and lazy-loaded.
"""
import argparse
import html
import json
import pathlib
import sys
import tomllib
import urllib.parse
import urllib.request

UA = "6586x57890143/weloveyou-pack (pack-site.py)"
API = "https://api.modrinth.com/v2/projects?ids="

# Same tokens as the benchmark site. Copied rather than imported: the two pages
# live in different repositories on different release cadences, and a shared
# stylesheet between them would be a third thing to publish.
CSS = """
/* SOURCE OF TRUTH: weloveyou.mc scripts/brand.py. This block is a copy across
   a repo boundary, the same deliberate duplication as the pack URL, because a
   shared config repo is more machinery than a palette is worth. If you change a
   token here, change it there, and vice versa. */
:root{
 --bg:#211F1B; --panel:#282621; --rule:#3B372F; --rule-hi:#564E42;
 --fg:#D5CEC1; --fg-hi:#EFE9DC; --dim:#8E8677;
 --win:#8FA860; --lose:#C4705C; --base:#D8A657; --info:#84A69C;
 --heart:#E39AAE;
 --mono:ui-monospace,"Cascadia Code","JetBrains Mono",Menlo,Consolas,"DejaVu Sans Mono",monospace;
}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;padding:2.5rem 1.5rem 4rem;background:var(--bg);color:var(--fg);
 font:15px/1.6 var(--mono);font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
main{max-width:76rem;margin:0 auto}
a{color:var(--info);text-decoration:none;border-bottom:1px solid transparent}
a:hover{border-bottom-color:var(--info)}
code{font-family:var(--mono);color:var(--fg-hi)}
.dim{color:var(--dim)}
.bar-row{display:flex;align-items:baseline;gap:1ch;padding-bottom:.5rem;flex-wrap:wrap}
.bar-row .t{flex:1 1 auto;display:flex;align-items:baseline;gap:.9ch;flex-wrap:wrap}
.bar-row .d{color:var(--dim);letter-spacing:.04em}
.brand{color:var(--heart);font-size:19px;font-weight:600;letter-spacing:.02em}
.brand .hb{font-size:16px}
.wordmark{color:var(--dim);letter-spacing:.14em;text-transform:uppercase;font-size:13px}
.hrule{border-top:1px solid var(--rule-hi)}
h2{font-size:15px;font-weight:600;margin:2.25rem 0 .4rem;color:var(--fg-hi);
 letter-spacing:.1em;text-transform:uppercase}
.note{color:var(--dim);margin:.5rem 0 1rem}
.note strong{color:var(--fg)}

/* Dotted leaders, same as the benchmark page: the dots are clipped by
   overflow, so any width fits exactly. */
.leads{margin:1.25rem 0 0;columns:2;column-gap:3rem}
.lead{break-inside:avoid;display:flex;align-items:baseline;gap:.75ch;min-width:0}
.lead .k{white-space:nowrap;color:var(--dim);letter-spacing:.06em;flex:0 0 auto}
.lead .d{flex:1 1 auto;min-width:1.5ch;border-bottom:1px dotted var(--rule);transform:translateY(-.3em)}
.lead .v{flex:0 1 auto;min-width:0;color:var(--fg-hi);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* Downloads. The first is what almost everyone wants, so it is the only one
   that is filled in; the rest are outlines. */
.gets{display:flex;flex-wrap:wrap;gap:.6rem;margin:.9rem 0 0}
.get{display:flex;flex-direction:column;gap:.1rem;border:1px solid var(--rule-hi);
 background:var(--panel);padding:.6rem .95rem;min-width:15rem;color:var(--fg-hi)}
.get:hover{border-color:var(--info);border-bottom-color:var(--info)}
.get.primary{border-color:var(--heart);background:#2F2822}
.get .n{font-weight:600;letter-spacing:.02em}
.get .s{color:var(--dim);font-size:12px;letter-spacing:.04em}
.url{display:flex;align-items:baseline;gap:1ch;border:1px solid var(--rule);background:var(--panel);
 padding:.5rem .8rem;margin:.6rem 0 0;overflow-x:auto;white-space:nowrap;font-size:13px}
.url .k{color:var(--dim);letter-spacing:.06em;flex:0 0 auto}

.filters{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:.6rem 0 1rem}
input[type=search]{flex:1 1 18rem;min-width:12rem;background:var(--panel);border:1px solid var(--rule);
 color:var(--fg-hi);font:14px var(--mono);padding:.45rem .7rem}
input[type=search]:focus{outline:0;border-color:var(--info)}
.chip{border:1px solid var(--rule);background:var(--panel);color:var(--dim);font:12px var(--mono);
 letter-spacing:.08em;text-transform:uppercase;padding:.45rem .8rem;cursor:pointer}
.chip[aria-pressed=true]{color:var(--fg-hi);border-color:var(--rule-hi);background:#2F2C25}
.count{border-color:transparent;background:transparent;cursor:default}

/* One card per mod. auto-fill so the number of columns follows the width
   rather than a stack of breakpoints. */
.mods{display:grid;grid-template-columns:repeat(auto-fill,minmax(19rem,1fr));gap:.4rem}
.mod{display:flex;gap:.75rem;border:1px solid var(--rule);background:var(--panel);padding:.6rem .75rem}
.mod[hidden]{display:none}
.mod img,.mod .noicon{width:40px;height:40px;flex:0 0 auto;image-rendering:pixelated;
 border:1px solid var(--rule);background:var(--bg)}
.mod .noicon{display:flex;align-items:center;justify-content:center;color:var(--rule-hi)}
.mod .b{min-width:0;flex:1 1 auto}
.mod .t{display:flex;align-items:baseline;gap:.7ch;flex-wrap:wrap}
.mod .t a,.mod .t .n{color:var(--fg-hi);font-weight:600}
.mod .d{color:var(--dim);font-size:13px;line-height:1.45;margin:.1rem 0 0;
 display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.mod .f{color:var(--rule-hi);font-size:11px;letter-spacing:.04em;margin:.25rem 0 0;
 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.side{font-size:11px;letter-spacing:.08em;text-transform:uppercase;flex:0 0 auto}
.side.both{color:var(--win)}
.side.client{color:var(--info)}
.side.server{color:var(--base)}
.empty{color:var(--dim);padding:1rem 0}
footer{margin-top:2.5rem;padding-top:1rem;border-top:1px solid var(--rule);color:var(--dim);text-align:center}
footer .hb{color:var(--heart)}
@media(max-width:760px){.leads{columns:1}}
"""

# Filtering 71 cards is a loop over the DOM, so it is a loop over the DOM.
JS = """
const q=document.getElementById('q'),
 chips=[...document.querySelectorAll('.chip[data-side]')],
 cards=[...document.querySelectorAll('.mod')],
 out=document.getElementById('count'),none=document.getElementById('none');
let side='all';
function apply(){
 const t=q.value.trim().toLowerCase();let n=0;
 for(const c of cards){
  const ok=(side==='all'||c.dataset.side===side)&&(!t||c.dataset.search.includes(t));
  c.hidden=!ok;if(ok)n++;}
 out.textContent=n+' shown';none.hidden=n>0;}
q.addEventListener('input',apply);
for(const c of chips)c.addEventListener('click',()=>{
 side=c.dataset.side;
 for(const o of chips)o.setAttribute('aria-pressed',o===c?'true':'false');
 apply();});
apply();
"""


def read_pack(channel_dir):
    """pack.toml plus every mods/*.pw.toml, exactly as the pack declares them."""
    pack = tomllib.loads((channel_dir / "pack.toml").read_text(encoding="utf-8"))
    mods = []
    for f in sorted((channel_dir / "mods").glob("*.pw.toml")):
        m = tomllib.loads(f.read_text(encoding="utf-8"))
        mods.append({
            "name": m.get("name", f.stem),
            "filename": m.get("filename", ""),
            "side": m.get("side", "both"),
            "id": (m.get("update", {}).get("modrinth", {}) or {}).get("mod-id", ""),
        })
    return pack, mods


def modrinth(ids):
    """Titles, blurbs and icons, in batches of 100. Any failure returns what it
    has: a page listing filenames is worse than one listing names, and both are
    better than a release that fell over because someone else's API was down."""
    out = {}
    for i in range(0, len(ids), 100):
        url = API + urllib.parse.quote(json.dumps(ids[i:i + 100]))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                for p in json.load(r):
                    out[p["id"]] = p
        except Exception as e:  # noqa: BLE001 - every failure is the same failure
            print(f"::warning::Modrinth lookup failed ({e}); using pack metadata only")
            return out
    return out


def lead(k, v):
    return ('<div class="lead">'
            f'<span class="k">{html.escape(k)}</span><span class="d"></span>'
            f'<span class="v">{v}</span></div>')


def button(href, name, sub, primary=False):
    cls = "get primary" if primary else "get"
    return (f'<a class="{cls}" href="{html.escape(href)}" download>'
            f'<span class="n">{html.escape(name)}</span>'
            f'<span class="s">{html.escape(sub)}</span></a>')


def downloads(outdir, channel):
    """Whatever the release actually put in this directory, in the order a
    player wants it. Driven by the files on disk, so a missing artifact drops
    its button instead of publishing a link to a 404."""
    specs = [
        (f"weloveyou-{channel}.zip", "Prism instance", "import this, it auto-updates", True),
        (f"weloveyou-{channel}.mrpack", "Modrinth pack", "for other launchers", False),
        ("packwiz-installer.jar", "packwiz-installer.jar", "pinned, what the instance runs", False),
    ]
    gets = [button(f, n, s, p) for f, n, s, p in specs if (outdir / f).exists()]
    return f'<div class="gets">{"".join(gets)}</div>' if gets else ""


def card(mod, meta):
    p = meta.get(mod["id"]) or {}
    title = p.get("title") or mod["name"]
    desc = p.get("description") or ""
    slug, icon, side = p.get("slug"), p.get("icon_url"), mod["side"]
    name = (f'<a href="https://modrinth.com/mod/{html.escape(slug)}">{html.escape(title)}</a>'
            if slug else f'<span class="n">{html.escape(title)}</span>')
    img = (f'<img src="{html.escape(icon)}" alt="" width="40" height="40" loading="lazy">'
           if icon else '<div class="noicon">?</div>')
    search = html.escape(" ".join([title, desc, mod["filename"], side]).lower())
    return (f'<div class="mod" data-side="{html.escape(side)}" data-search="{search}">'
            f'{img}<div class="b"><div class="t">{name}'
            f'<span class="side {html.escape(side)}">{html.escape(side)}</span></div>'
            f'<p class="d">{html.escape(desc)}</p>'
            f'<p class="f">{html.escape(mod["filename"])}</p></div></div>')


def render(pack, mods, meta, channel, outdir, base_url):
    v = pack.get("versions", {})
    n = {s: sum(m["side"] == s for m in mods) for s in ("both", "client", "server")}
    pack_url = f"{base_url.rstrip('/')}/pack.toml" if base_url else "pack.toml"
    chips = "".join(
        f'<button class="chip" data-side="{s}" aria-pressed="{"true" if s == "all" else "false"}">'
        f"{s}</button>" for s in ("all", "both", "client", "server"))

    p = [
        "<main>",
        '<div class="bar-row"><span class="t">'
        '<span class="brand">wly <span class="hb">&#128150;</span></span>'
        f'<span class="wordmark">modpack &#183; {html.escape(channel)}</span></span>'
        f'<span class="d">v{html.escape(str(pack.get("version", "?")))}</span></div>'
        '<div class="hrule"></div>',

        '<div class="leads">',
        lead("minecraft", html.escape(v.get("minecraft", "?"))),
        lead("fabric loader", html.escape(v.get("fabric", "?"))),
        lead("mods", f'{len(mods)} <span class="dim">({n["both"]} both &#183; '
                     f'{n["client"]} client &#183; {n["server"]} server)</span>'),
        lead("index hash",
             f'<code>{html.escape(str(pack.get("index", {}).get("hash", "?"))[:16])}</code>'),
        "</div>",

        "<h2>Get it</h2>",
        '<p class="note">The instance re-syncs from this URL on every launch, so a pack '
        'release needs nothing from you. <strong>Importing it runs the pinned '
        'packwiz-installer on your machine</strong>, which is how that works and is worth '
        'knowing before you click.</p>',
        downloads(outdir, channel),
        f'<div class="url"><span class="k">packwiz</span><code>{html.escape(pack_url)}</code></div>',

        "<h2>What is in it</h2>",
        '<div class="filters"><input type="search" id="q" placeholder="filter mods" '
        f'autocomplete="off">{chips}<span class="chip count" id="count"></span></div>',
        '<div class="mods">' + "".join(card(m, meta) for m in mods) + "</div>",
        '<p class="empty" id="none" hidden>nothing matches that.</p>',

        '<footer>Built by <code>packwiz</code>, published to Cloudflare Pages, with '
        '<span class="hb">&#128150;</span>, from '
        '<a href="https://github.com/6586x57890143/weloveyou-pack">weloveyou-pack</a>.<br>'
        "Names, blurbs and icons are Modrinth's, fetched when this page was built.</footer>",
        "</main>",
    ]
    return ("<!doctype html>\n"
            '<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="color-scheme" content="dark">'
            f"<title>wly \U0001f496 {html.escape(channel)} modpack</title>"
            f"<style>{CSS}</style></head><body>\n" + "\n".join(p)
            + f"\n<script>{JS}</script>\n</body></html>\n")


def root(site):
    """The site root, which was a hand-written placeholder saying nothing had
    been published yet - still saying it two releases later. Generated from the
    channels actually present, so it cannot go stale that way again."""
    rows = []
    for d in sorted((site / "pack").glob("*")):
        if not (d / "pack.toml").exists():
            continue
        pk = tomllib.loads((d / "pack.toml").read_text(encoding="utf-8"))
        v = pk.get("versions", {})
        rows.append(
            f'<a class="get primary" href="pack/{html.escape(d.name)}/">'
            f'<span class="n">{html.escape(d.name)} v{html.escape(str(pk.get("version", "?")))}</span>'
            f'<span class="s">minecraft {html.escape(v.get("minecraft", "?"))} '
            f'&#183; fabric {html.escape(v.get("fabric", "?"))}</span></a>')
    body = (
        '<main><div class="bar-row"><span class="t">'
        '<span class="brand">wly <span class="hb">&#128150;</span></span>'
        '<span class="wordmark">modpack distribution</span></span></div>'
        '<div class="hrule"></div>'
        '<h2>Channels</h2>'
        '<p class="note">One directory per channel, each its own packwiz endpoint. '
        'The instance re-syncs from the rolling prefix; every release also keeps an '
        'immutable <code>v{version}</code> copy beside it, which is what makes a '
        'rollback possible.</p>'
        + (f'<div class="gets">{"".join(rows)}</div>' if rows
           else '<p class="empty">No channel has been published yet.</p>')
        + '<footer>Published by the release workflow, with '
        '<span class="hb">&#128150;</span>, from '
        '<a href="https://github.com/6586x57890143/weloveyou-pack">weloveyou-pack</a>.'
        '</footer></main>')
    out = site / "index.html"
    out.write_text(
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="dark">'
        "<title>wly \U0001f496 modpack</title>"
        f"<style>{CSS}</style></head><body>\n{body}\n</body></html>\n",
        encoding="utf-8", newline="\n")
    print(f"wrote {out}: {len(rows)} channel(s)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("channel", nargs="?", default="stable")
    ap.add_argument("--pack", default=None, help="channel dir, default pack/<channel>")
    ap.add_argument("--out", default=None, help="where index.html goes, default --pack")
    ap.add_argument("--base-url", default="", help="published URL of this prefix")
    ap.add_argument("--offline", action="store_true", help="skip Modrinth, for tests")
    ap.add_argument("--root", default=None,
                    help="write the site root index for this directory and stop")
    a = ap.parse_args()

    if a.root:
        return root(pathlib.Path(a.root))

    packdir = pathlib.Path(a.pack or f"pack/{a.channel}")
    outdir = pathlib.Path(a.out or packdir)
    outdir.mkdir(parents=True, exist_ok=True)

    pack, mods = read_pack(packdir)
    meta = {} if a.offline else modrinth([m["id"] for m in mods if m["id"]])

    out = outdir / "index.html"
    out.write_text(render(pack, mods, meta, a.channel, outdir, a.base_url),
                   encoding="utf-8", newline="\n")
    print(f"wrote {out}: {len(mods)} mods, {len(meta)} from Modrinth")
    return 0


if __name__ == "__main__":
    sys.exit(main())
