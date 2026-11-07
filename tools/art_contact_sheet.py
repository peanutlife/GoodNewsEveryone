"""Render every section drawing at every crop the site actually gives it.

The same 480x270 file is shown as a 2/1 card, a 16/9 lead, a 32/9 story band
(object-position 50% 60%) and a 3/2 thumb, so a scene can look fine on the
canvas and still lose its subject in one of the frames. This writes one HTML
page with all of them side by side; screenshot it in headless Chrome before
wiring anything up.

    python tools/art_contact_sheet.py /tmp/contact.html
"""
from __future__ import annotations

import pathlib
import sys

ART = pathlib.Path(__file__).resolve().parent.parent / "src" / "static" / "illustrations"

# name, css width, css height, object-position: the four live frames, measured in
# PEA-14 from src/static/peanut.css.
CROPS = [
    ("card 2/1", 248, 124, "50% 50%"),
    ("lead 16/9", 248, 139, "50% 50%"),
    ("band 32/9", 248, 70, "50% 60%"),
    ("thumb 3/2", 120, 80, "50% 50%"),
]

CSS = """
body { margin: 0; padding: 24px; background: #F4F1EA; font: 13px/1.4 -apple-system, Helvetica, sans-serif; color: #2B2A26; }
h1 { font-size: 18px; margin: 0 0 16px; }
table { border-collapse: collapse; }
th { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: #6B675E; padding: 0 0 6px; }
td { padding: 6px 8px; vertical-align: top; }
td.n { font-weight: 600; white-space: nowrap; }
.f { overflow: hidden; border-radius: 6px; background: #fff; box-shadow: 0 0 0 1px rgba(0,0,0,.08); }
.f img { width: 100%; height: 100%; object-fit: cover; display: block; }
"""


def main(out: str) -> None:
    files = sorted(ART.glob("*.svg"))
    rows = []
    for f in files:
        cells = []
        for _, w, h, pos in CROPS:
            cells.append(
                f'<td><div class="f" style="width:{w}px;height:{h}px">'
                f'<img src="file://{f}" style="object-position:{pos}"></div></td>'
            )
        kb = f.stat().st_size / 1024
        rows.append(f'<tr><td class="n">{f.name}<br><span style="color:#6B675E">{kb:.1f} KB</span></td>' + "".join(cells) + "</tr>")
    head = "".join(f"<th>{name}</th>" for name, *_ in CROPS)
    html = (
        "<!doctype html><meta charset=utf-8><title>Section art contact sheet</title>"
        f"<style>{CSS}</style><h1>Section art, every file at every live crop "
        f"({len(files)} files)</h1><table><tr><th>file</th>{head}</tr>"
        + "".join(rows)
        + "</table>"
    )
    pathlib.Path(out).write_text(html, encoding="utf-8")
    print(f"{out}  ({len(files)} files)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/art_contact_sheet.html")
