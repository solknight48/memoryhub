#!/usr/bin/env python3
"""Rebuild the README's screenshots from a throwaway café project.

Builds /tmp/mh-showcase/cafe-site with a hub (frontend template, five stages,
a second take, three sub-checkpoints, a link, a skipped session) and a live
transcript, all under a temporary HOME so nothing touches the real Claude Code
data; starts `mh ui` on it; captures the map's states into docs/img/ with
playwright driving the system chromium in light mode; stops the server.

    uv run --with playwright --with pillow scripts/showcase.py

Needs `mh` on PATH (uv tool install -e .) and /usr/bin/chromium.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path("/tmp/mh-showcase")
PROJ = BASE / "cafe-site"
HOME = Path("/tmp/mh-showcase-home")
PORT = 7790
OUT = ROOT / "docs" / "img"
ENV = {**os.environ, "HOME": str(HOME)}


def mh(*args: str) -> str:
    p = subprocess.run(["mh", *args], cwd=PROJ, env=ENV, capture_output=True, text=True)
    if p.returncode:
        sys.exit(f"mh {' '.join(args)} failed:\n{p.stderr}")
    return p.stdout.strip()


def records(turns, start, model="claude-opus-5"):
    """A Claude transcript of plain user/assistant turns, a minute apart."""
    t = datetime.fromisoformat(start.replace("Z", "+00:00"))
    out = []
    for q, a in turns:
        out.append(
            {
                "type": "user",
                "cwd": str(PROJ),
                "timestamp": t.isoformat().replace("+00:00", "Z"),
                "message": {"role": "user", "content": q},
            }
        )
        t += timedelta(minutes=1)
        out.append(
            {
                "type": "assistant",
                "cwd": str(PROJ),
                "timestamp": t.isoformat().replace("+00:00", "Z"),
                "message": {
                    "role": "assistant",
                    "model": model,
                    "content": [{"type": "text", "text": a}],
                },
            }
        )
        t += timedelta(minutes=1)
    return out


def dump(path: Path, recs) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return path


_n = 0


def save(turns, start, model="claude-opus-5") -> str:
    global _n
    _n += 1
    sid = f"{_n:08x}-cafe-4000-8000-00000000{_n:04x}"
    path = dump(BASE / "transcripts" / f"{sid}.jsonl", records(turns, start, model))
    return mh("save", "--transcript", str(path))


def build() -> None:
    shutil.rmtree(BASE, ignore_errors=True)
    shutil.rmtree(HOME, ignore_errors=True)
    PROJ.mkdir(parents=True)
    HOME.mkdir(parents=True)
    (PROJ / "index.html").write_text("<!doctype html>\n<title>Brew & Co</title>\n")
    (PROJ / "styles.css").write_text(":root { --cream: #faf6f0; }\n")
    (PROJ / "app.js").write_text('fetch("/api/menu");\n')
    git = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]
    subprocess.run(["git", "init", "-q"], cwd=PROJ, check=True)
    subprocess.run([*git, "add", "-A"], cwd=PROJ, check=True)
    subprocess.run([*git, "commit", "-qm", "scaffold the site"], cwd=PROJ, check=True)
    subprocess.run(["git", "config", "--global", "user.name", "demo"], env=ENV, check=True)
    subprocess.run(
        ["git", "config", "--global", "user.email", "demo@example.com"], env=ENV, check=True
    )
    mh("init", "--template", "frontend")

    mh("checkpoint")
    save(
        [
            (
                "We're building a website for Brew & Co, a small café. What does the launch version need?",
                "Keep launch small and honest about what a café site is for:\n\n- **Menu** with prices and dietary tags — the reason most people visit\n- **Hours and location**, with a map link\n- A short **about** line and a way to contact you\n\nOut of scope for launch: accounts, loyalty, online ordering. Those need a payment provider and staff time you do not have yet.",
            ),
            (
                "Single page then. Which sections, top to bottom?",
                '1. **Header** — logo, two nav links, sticky\n2. **Hero** — one line, one call to action ("See the menu")\n3. **Menu grid** — cards by category, fed by a small JSON API so the staff can edit prices\n4. **Hours & location**\n5. **Footer** — address, Instagram, phone\n\nEverything above the menu must render without JavaScript.',
            ),
        ],
        "2026-08-20T09:12:00Z",
    )

    mh("checkpoint")
    save(
        [
            (
                "Propose a design system: colours, type, spacing. Warm, not corporate.",
                "```css\n:root {\n  --ink: #1f1a17;      /* text */\n  --cream: #faf6f0;    /* page */\n  --accent: #c8553d;   /* buttons, links */\n  --space: 8px;        /* every gap is a multiple */\n}\n```\n\nType: system sans for UI, one display serif for the hero line. Radius 12px on cards, 999px on buttons. No shadows heavier than `0 1px 2px`.",
            ),
        ],
        "2026-08-21T10:05:00Z",
    )
    mh("checkpoint", "header", "--under", "ui-ux-design")
    save(
        [
            (
                "Design the header. Logo left, nav right, must stay usable on a phone.",
                "- Logo as text (`Brew & Co`), no image — it loads instantly and scales\n- Two links only: Menu, Hours. A third item is where nav bars start to sprawl\n- Sticky, with a 1px bottom border that only appears after scrolling\n- Under 480px the two links stay; the logo shrinks to 18px\n\n```css\n.site-header { position: sticky; top: 0; display: flex; justify-content: space-between; }\n```",
            ),
        ],
        "2026-08-22T14:30:00Z",
    )
    mh("checkpoint", "hero", "--under", "ui-ux-design")
    save(
        [
            (
                "Hero section: one line and a button. Give me three headline options.",
                "1. *Slow coffee, fast Wi-Fi.*\n2. *Roasted on Tuesdays. Poured all week.*\n3. *The corner that smells like morning.*\n\nI would take the first: it says who the place is for. The button reads **See the menu** and scrolls, it does not navigate.",
            ),
        ],
        "2026-08-23T11:20:00Z",
        model="claude-sonnet-5",
    )
    mh("checkpoint", "menu", "--under", "ui-ux-design")
    save(
        [
            (
                "The menu grid. Cards? Categories? How do dietary tags show?",
                "Cards in a responsive grid, `minmax(220px, 1fr)`. One card per item: name, price, a one-line note, then tags as small pills (**V**, **GF**, **oat**). Categories are headings between rows, not tabs — a café menu is read, not navigated.\n\nPrices right-aligned with `font-variant-numeric: tabular-nums` so the column lines up.",
            ),
            (
                "What does a card look like when the API is slow?",
                "A skeleton card: grey blocks where the name and price go, no spinner. Six of them. If the request fails, one line in the grid: *Menu is taking a break — try again* with a retry link.",
            ),
        ],
        "2026-08-24T16:45:00Z",
    )

    mh("checkpoint")
    save(
        [
            (
                "Scaffold it: vanilla JS, no framework, Vite for dev. Show the layout.",
                "```\ncafe-site/\n  index.html\n  styles.css\n  app.js\n  api/menu.json      # served by Vite in dev, by the host in prod\n  vite.config.js\n```\n\n```sh\nnpm create vite@latest . -- --template vanilla\nnpm install\nnpm run dev\n```\n\nNo build step is needed for the page itself; Vite is only there for the dev server and the `/api` middleware.",
            ),
        ],
        "2026-08-25T09:40:00Z",
    )
    skipped = save(
        [
            (
                "Unrelated: convert this supplier CSV to JSON for me.\n\n```\nname,city\nRoasters United,Leeds\nBean Barn,York\n```",
                '```json\n[\n  {"name": "Roasters United", "city": "Leeds"},\n  {"name": "Bean Barn", "city": "York"}\n]\n```',
            ),
        ],
        "2026-08-25T15:10:00Z",
    )
    mh("skip", "scaffolding/" + re.search(r"saved (\S+\.md)", skipped).group(1))

    mh("checkpoint")
    save(
        [
            (
                "Implement the header and hero from the design notes.",
                "Done in `index.html` and `styles.css`:\n\n- the header is a flex row, sticky, with the border toggled by a `scrolled` class from a 20-line scroll listener\n- the hero uses the display serif at `clamp(2rem, 6vw, 4rem)` so it never wraps to three lines\n\nBoth render with JavaScript disabled.",
            ),
        ],
        "2026-08-27T13:05:00Z",
    )
    mh("checkpoint", "--at", "component-development")
    save(
        [
            (
                "Second take on the menu grid: CSS grid with container queries instead of media queries.",
                "```css\n.menu-grid { container-type: inline-size; display: grid; gap: calc(var(--space) * 2); }\n@container (min-width: 480px) { .menu-grid { grid-template-columns: repeat(2, 1fr); } }\n@container (min-width: 720px) { .menu-grid { grid-template-columns: repeat(3, 1fr); } }\n```\n\nThe grid now answers to its own width, so it lays out the same inside a modal or a sidebar.",
            ),
        ],
        "2026-08-28T10:15:00Z",
    )

    mh("checkpoint")
    save(
        [
            (
                "Define the menu API. Keep it something a café owner can edit by hand.",
                'One file, `api/menu.json`, served as `GET /api/menu`:\n\n```json\n[\n  {"category": "Coffee", "name": "Flat white", "price": "3.40", "tags": ["oat"]},\n  {"category": "Food",   "name": "Banana bread", "price": "2.80", "tags": ["V"]}\n]\n```\n\nPrices are strings on purpose: no float rounding, and the owner types what the board says.',
            ),
        ],
        "2026-09-01T09:30:00Z",
    )
    mh("link", "api-integration", "ui-ux-design.menu")

    # the live session: the transcript Claude Code would be writing right now
    cwd = str(PROJ)

    def user(text, ts):
        return {
            "type": "user",
            "cwd": cwd,
            "timestamp": ts,
            "message": {"role": "user", "content": text},
        }

    def asst(blocks, ts, mid):
        return {
            "type": "assistant",
            "cwd": cwd,
            "timestamp": ts,
            "message": {
                "role": "assistant",
                "id": mid,
                "model": "claude-opus-5",
                "content": blocks,
            },
        }

    def result(text, ts):
        return {
            "type": "user",
            "cwd": cwd,
            "timestamp": ts,
            "message": {"role": "user", "content": [{"type": "tool_result", "content": text}]},
        }

    recs = [
        user(
            "Wire the menu grid to /api/menu with the skeleton and error states from the design.",
            "2026-09-03T09:00:00Z",
        ),
        asst(
            [
                {
                    "type": "thinking",
                    "thinking": "The design notes ask for six skeleton cards while loading and a one-line error with a retry link. Check what the API returns first, then edit app.js.",
                }
            ],
            "2026-09-03T09:00:10Z",
            "m1",
        ),
        asst(
            [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {
                        "command": "curl -s localhost:5173/api/menu | head -c 300",
                        "description": "Peek at the menu API",
                    },
                }
            ],
            "2026-09-03T09:00:12Z",
            "m1",
        ),
        asst(
            [{"type": "tool_use", "name": "Read", "input": {"file_path": f"{cwd}/app.js"}}],
            "2026-09-03T09:00:12Z",
            "m1",
        ),
        result(
            '[{"category":"Coffee","name":"Flat white","price":"3.40","tags":["oat"]}]',
            "2026-09-03T09:00:14Z",
        ),
        asst(
            [
                {
                    "type": "tool_use",
                    "name": "Edit",
                    "input": {
                        "file_path": f"{cwd}/app.js",
                        "old_string": 'fetch("/api/menu")',
                        "new_string": 'showSkeleton(6);\nfetch("/api/menu")',
                    },
                }
            ],
            "2026-09-03T09:01:00Z",
            "m2",
        ),
        result(f"The file {cwd}/app.js has been updated.", "2026-09-03T09:01:02Z"),
        asst(
            [
                {
                    "type": "text",
                    "text": "Wired up. `app.js` now shows six skeleton cards, replaces them with the grid when `/api/menu` answers, and on a failed request renders one line — *Menu is taking a break — try again* — whose link retries.\n\n```js\nfunction showSkeleton(n) {\n  grid.replaceChildren(...Array.from({ length: n }, () => skeletonCard()));\n}\n```\n\nCategories come from the `category` field, so the JSON order is the menu order.",
                }
            ],
            "2026-09-03T09:02:00Z",
            "m3",
        ),
        user(
            "Add a retry cap: after three failures stop offering the link.", "2026-09-03T09:05:00Z"
        ),
        asst(
            [
                {
                    "type": "thinking",
                    "thinking": "A module-level counter is enough; no need for state management on a café page.",
                }
            ],
            "2026-09-03T09:05:05Z",
            "m4",
        ),
        asst(
            [
                {
                    "type": "tool_use",
                    "name": "Edit",
                    "input": {
                        "file_path": f"{cwd}/app.js",
                        "old_string": "let failures = 0;",
                        "new_string": "let failures = 0;\nconst MAX_RETRIES = 3;",
                    },
                }
            ],
            "2026-09-03T09:05:08Z",
            "m4",
        ),
        result(f"The file {cwd}/app.js has been updated.", "2026-09-03T09:05:09Z"),
        asst(
            [
                {
                    "type": "text",
                    "text": "Capped at three. After the third failure the line loses its link and reads *Menu is taking a break — please ask at the counter*.",
                }
            ],
            "2026-09-03T09:06:00Z",
            "m5",
        ),
    ]
    sys.path.insert(0, str(ROOT / "src"))
    from memoryhub.purify import encode_project_dir

    dump(
        HOME
        / ".claude"
        / "projects"
        / encode_project_dir(PROJ)
        / "c0ffee11-1111-4000-8000-0000000cafe1.jsonl",
        recs,
    )


def capture(url: str) -> None:
    from playwright.sync_api import sync_playwright

    def union(a, b):
        x0, y0 = min(a["x"], b["x"]), min(a["y"], b["y"])
        x1 = max(a["x"] + a["width"], b["x"] + b["width"])
        y1 = max(a["y"] + a["height"], b["y"] + b["height"])
        return {"x": x0 - 8, "y": y0 - 8, "width": x1 - x0 + 16, "height": y1 - y0 + 16}

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        ctx = b.new_context(
            viewport={"width": 1400, "height": 1100}, device_scale_factor=2, color_scheme="light"
        )
        pg = ctx.new_page()
        pg.goto(url)
        pg.wait_for_selector("#map circle", timeout=20000)
        pg.wait_for_selector("#livesec:not([hidden]) .ex", timeout=20000)
        # room for the whole timeline; the header must not float over a capture;
        # one live exchange is enough to show the stream
        pg.add_style_tag(
            content="main{max-width:1400px} .mapwrap{overflow:visible} header{position:static}"
            " #liveex .ex:nth-of-type(n+2){display:none}"
        )
        pg.wait_for_timeout(500)
        pg.locator("#mapsec").screenshot(path=str(OUT / "map.png"))

        pg.evaluate("""() => { const g = [...document.querySelectorAll('#map g')].find(x =>
            [...x.querySelectorAll('text')].some(t => t.textContent === 'ui-ux-design'));
            g.dispatchEvent(new MouseEvent('click', {bubbles: true})); }""")
        pg.wait_for_selector("#menu")
        pg.wait_for_timeout(200)
        pg.screenshot(
            path=str(OUT / "node-menu.png"),
            clip=union(pg.locator("#mapsec").bounding_box(), pg.locator("#menu").bounding_box()),
        )
        pg.evaluate("closeMenu()")

        pg.evaluate("document.getElementById('newckpt').click()")
        pg.wait_for_selector("#menu")
        pg.wait_for_timeout(200)
        pg.screenshot(
            path=str(OUT / "new-checkpoint.png"),
            clip=union(pg.locator("#newckpt").bounding_box(), pg.locator("#menu").bounding_box()),
        )
        pg.evaluate("closeMenu()")

        pg.evaluate("selectCheckpoint('scaffolding', false)")
        pg.wait_for_selector("#ckptsec:not([hidden]) .srow")
        pg.wait_for_timeout(200)
        pg.locator("#ckptsec").screenshot(path=str(OUT / "checkpoint.png"))

        pg.evaluate("""() => { const c = DATA.checkpoints.find(x => x.slug === 'ui-ux-design.menu');
            return openSession(c.slug, c.sessions[0].file); }""")
        pg.wait_for_selector("#sessec:not([hidden]) .ex")
        pg.wait_for_timeout(300)
        pg.locator("#sessec").screenshot(path=str(OUT / "session.png"))

        pg.locator("#livesec").screenshot(path=str(OUT / "live.png"))
        pg.evaluate("""() => { const r = document.querySelector('input[name=savekind][value=summary]');
            r.checked = true; r.dispatchEvent(new Event('change')); }""")
        pg.wait_for_timeout(200)
        pg.locator("#savebox").screenshot(path=str(OUT / "save-box.png"))
        b.close()

    from PIL import Image

    for f in sorted(OUT.glob("*.png")):
        im = Image.open(f)
        if im.width > 1600:
            im = im.resize((1600, round(im.height * 1600 / im.width)), Image.LANCZOS)
        im.save(f, optimize=True)
        print(f"{f.relative_to(ROOT)}  {im.size[0]}x{im.size[1]}  {f.stat().st_size // 1024} KB")


def main() -> None:
    build()
    out = mh("ui", "--detach", "--no-browser", "--port", str(PORT))
    url = re.search(r"http://\S+", out).group(0).split("&sid=")[0]
    try:
        capture(url)
    finally:
        mh("ui", "--stop")
    print("done —", OUT)


if __name__ == "__main__":
    main()
