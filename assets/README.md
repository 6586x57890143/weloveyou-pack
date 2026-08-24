# assets

Images the published site serves at `/assets/`, copied there by `release.yml`.
They are separate from the mod icons on the channel page, which are fetched from
Modrinth's CDN at build time and never stored here.

`prism-import.png` is Prism Launcher's Add Instance window with Import from zip
selected, and it is the screenshot the Discord get-started card shows. Prism's
own accent is a theme colour that differs per user, so it is recoloured to the
wly palette (`#E39AAE` chrome, warm neutrals) and the URL field is outlined.
Nothing about the layout is altered, because recognising the real window is the
entire point of showing it.

Regenerate it from a fresh screenshot with `scripts/recolour-shot.py`.
