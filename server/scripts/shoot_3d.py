"""Render the app's Three.js 3D Hawk-Eye viewer to a static PNG.

Loads the same ``test3_3d.html`` the Flutter app shows (the WebGL bloom/tube
viewer produced by ``app.three_d_viewer.render_html``), waits for the CDN
Three.js modules to load and the intro fade-in to settle, hides the orbit
hint, then screenshots it. This is the real app 3D view, captured for the
report/PPT figures (replacing the matplotlib plot).

Run: server/.venv/bin/python server/scripts/shoot_3d.py <input.html> <output.png>
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HTML = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
W, H = 1600, 1000


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--use-gl=angle",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--ignore-gpu-blocklist",
                "--enable-webgl",
            ],
        )
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(HTML.as_uri(), wait_until="networkidle", timeout=60000)
        # Let the WebGL scene build, the panels/metrics fade in, and the ball
        # animation reach a representative point on the path.
        page.wait_for_timeout(4500)
        # Hide the interactive hint so the figure reads as a clean broadcast view.
        page.evaluate(
            "() => { const h = document.getElementById('help'); if (h) h.style.display='none'; }"
        )
        page.wait_for_timeout(400)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUT))
        browser.close()
        if errors:
            print("PAGE ERRORS:", errors[:3])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
