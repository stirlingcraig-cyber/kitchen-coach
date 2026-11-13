"""End-to-end browser test (dev tool). Needs:  pip install playwright && playwright install chromium

Checks, in a real Chromium:
  * every sample recipe reads the same in Windows mode (local Python engine) and iPhone/offline
    mode (in-browser JavaScript engine)
  * the cooking flow: start/pause timers, timers finishing, background timers, +1 min, finish
  * saves screenshots to docs/screens/ for the user guide
Run:  python tests/e2e_browser.py
"""
import functools
import http.server
import sys
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app  # noqa: E402

SAMPLES = ROOT / "tests" / "samples"
SHOTS = ROOT / "docs" / "screens"
SHOTS.mkdir(parents=True, exist_ok=True)


def serve_flask(port):
    srv = make_server("127.0.0.1", port, create_app())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def serve_static(port):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "web"))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def read_review(page):
    expect(page.locator("#reviewView")).to_be_visible(timeout=20000)
    title = page.locator("#titleInput").input_value()
    steps = []
    for item in page.locator(".step-item").all():
        text = item.locator("textarea").input_value()
        mins = int(item.locator('[data-field="min"]').input_value())
        secs = int(item.locator('[data-field="sec"]').input_value())
        steps.append((text, mins * 60 + secs))
    return title, steps


def upload(page, base, path):
    page.goto(base)
    page.wait_for_selector("html[data-ready='1']")
    page.set_input_files("#fileInput", str(path))
    return read_review(page)


def main():
    errors = []
    serve_flask(8765)
    serve_static(8766)
    server_url, client_url = "http://127.0.0.1:8765/", "http://127.0.0.1:8766/"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1180, "height": 860}, device_scale_factor=1)
        page = ctx.new_page()
        page.on("pageerror", lambda e: (errors.append(f"JS error: {e}"), print("PAGEERROR", e)))
        page.on("console", lambda m: m.type == "error" and "404" not in m.text  # api/health 404 = offline mode
                and errors.append(f"console: {m.text}"))

        # ---- parity: Windows engine vs in-browser engine
        for f in sorted(SAMPLES.iterdir()):
            a = upload(page, server_url, f)
            b = upload(page, client_url, f)
            status = "same" if a == b else "DIFFERENT"
            print(f"{f.name:22} {status:9} {a[0]!r} {len(a[1])} steps")
            if a != b:
                for x, y in zip(a[1], b[1]):
                    if x != y:
                        print("   server:", x, "\n   client:", y)
                errors.append(f"parity mismatch for {f.name}")

        # ---- error handling
        page.goto(client_url)
        page.wait_for_selector("html[data-ready='1']")
        page.set_input_files("#fileInput", files=[{"name": "old.doc", "mimeType": "application/msword", "buffer": b"x"}])
        expect(page.locator("#homeError")).to_contain_text("Save As")

        # ---- full cooking flow with a fake clock (Windows mode)
        page.clock.install()
        page.goto(server_url)
        page.wait_for_selector("html[data-ready='1']")
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_selector("html[data-ready='1']")
        page.screenshot(path=str(SHOTS / "01_home.png"))
        page.click("#sampleBtn")
        expect(page.locator("#reviewView")).to_be_visible(timeout=20000)
        page.screenshot(path=str(SHOTS / "02_review.png"))
        page.locator("#ingredientsBox summary").click()
        page.screenshot(path=str(SHOTS / "03_review_ingredients.png"), full_page=True)

        page.click("#startCooking")
        expect(page.locator("#cookView")).to_be_visible()
        expect(page.locator("#clock")).to_have_text("05:00")
        expect(page.locator("#primaryBtn")).to_have_text("Start timer")
        page.screenshot(path=str(SHOTS / "04_cook_ready.png"))
        page.click("#primaryBtn")
        page.clock.run_for(65_000)
        expect(page.locator("#clock")).to_have_text("03:55")
        expect(page.locator("#primaryBtn")).to_have_text("Pause")
        page.screenshot(path=str(SHOTS / "05_cook_running.png"))
        page.keyboard.press("Space")                      # pause via keyboard
        expect(page.locator("#primaryBtn")).to_have_text("Resume")
        page.clock.run_for(30_000)
        expect(page.locator("#clock")).to_have_text("03:55")
        page.keyboard.press("Space")
        page.clock.run_for(236_000)
        expect(page.locator("#primaryBtn")).to_have_text("Stop alarm")
        expect(page.locator("#timerState")).to_have_text("Time's up!")
        page.screenshot(path=str(SHOTS / "06_cook_done.png"))
        page.click("#primaryBtn", force=True)           # button pulses while ringing
        expect(page.locator("#primaryBtn")).to_have_text("Next step")

        # step 2 timer runs in the background while we move on
        page.click("#nextBtn")
        expect(page.locator("#cookPosition")).to_have_text("Step 2 of 7")
        page.click("#primaryBtn")
        page.click("#nextBtn")
        expect(page.locator("#cookPosition")).to_have_text("Step 3 of 7")
        expect(page.locator(".pill")).to_have_count(1)
        page.click("#primaryBtn")                         # step 3: 1 minute
        page.click("#plusBtn")                            # now 2 minutes
        page.clock.run_for(20_000)
        page.wait_for_timeout(500)   # let the ticker repaint
        page.screenshot(path=str(SHOTS / "07_cook_background_timer.png"))
        page.clock.run_for(590_000)
        expect(page.locator(".pill.done")).to_have_count(1)
        page.click(".pill.done", force=True)
        expect(page.locator(".pill")).to_have_count(0)

        # reload mid-cook -> resume banner
        page.reload()
        page.wait_for_selector("html[data-ready='1']")
        expect(page.locator("#resumeBanner")).to_be_visible()
        page.screenshot(path=str(SHOTS / "08_resume.png"))
        page.click("#resumeSession")
        expect(page.locator("#cookPosition")).to_have_text("Step 3 of 7")
        for _ in range(5):
            page.keyboard.press("ArrowRight")
        expect(page.locator("#stepText")).to_contain_text("Recipe complete")
        page.screenshot(path=str(SHOTS / "09_complete.png"))
        page.click("#primaryBtn")
        expect(page.locator("#homeView")).to_be_visible()
        expect(page.locator("#library li")).to_have_count(1)

        page.click("#settingsBtn")
        expect(page.locator("#settingsDialog")).to_be_visible()
        page.screenshot(path=str(SHOTS / "10_settings.png"))
        page.keyboard.press("Escape")

        # ---- iPhone-sized screenshots (offline build)
        phone = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                    is_mobile=True, has_touch=True)
        mp = phone.new_page()
        mp.on("pageerror", lambda e: errors.append(f"JS error (phone): {e}"))
        mp.clock.install()
        mp.goto(client_url)
        mp.wait_for_selector("html[data-ready='1']")
        mp.screenshot(path=str(SHOTS / "11_iphone_home.png"))
        mp.set_input_files("#fileInput", str(SAMPLES / "lemon_drizzle.docx"))
        expect(mp.locator("#reviewView")).to_be_visible(timeout=20000)
        mp.screenshot(path=str(SHOTS / "12_iphone_review.png"))
        mp.click("#startCooking")
        for _ in range(3):
            mp.click("#nextBtn")
        mp.click("#primaryBtn")
        mp.clock.run_for(125_000)
        mp.wait_for_timeout(500)
        mp.screenshot(path=str(SHOTS / "13_iphone_cook.png"))
        browser.close()

    if errors:
        print("\nFAILURES:\n  " + "\n  ".join(errors))
        sys.exit(1)
    print("\nAll browser checks passed. Screenshots in", SHOTS)


if __name__ == "__main__":
    main()
