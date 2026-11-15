#!/usr/bin/env python3
"""Capture every user-facing Vkus navigation tab from the real Tk application."""
from __future__ import annotations
import argparse, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "Vkus_3.17_NATIVE_EXCHANGE"
sys.path.insert(0, str(ROOT))
from PIL import ImageGrab
from vkus.app import VkusApp

def pump(root, seconds=0.7):
    end = time.time() + seconds
    while time.time() < end:
        root.update_idletasks()
        root.update()
        time.sleep(0.03)

def save_screen(path):
    img = ImageGrab.grab().convert("RGB")
    img.save(path, "PNG")
    if path.stat().st_size < 30_000:
        raise RuntimeError(f"Screenshot too small: {path}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default="artifacts/vkus_tabs")
    args = ap.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    app = VkusApp()
    try:
        app._unlock()
        # The test environment skips waiting for the cinematic splash but builds
        # the exact same application UI through its normal completion callback.
        if getattr(app, "splash", None) is not None:
            app.splash.finish()
        pump(app.root, 1.0)

        tabs = [
            ("01_Primary_Setup.png", app._show_setup),
            ("02_Search.png", app._show_search),
            ("03_Messages.png", app._show_messages),
        ]
        for filename, show in tabs:
            show()
            pump(app.root, 0.8)
            save_screen(out / filename)

        # The Exchange is intentionally a separate full-size window. Capture
        # its actual rendered window area, not the old static reference preview.
        app._show_exchange()
        pump(app.root, 1.0)
        win = app.exchange_window
        x, y = win.winfo_rootx(), win.winfo_rooty()
        w, h = win.winfo_width(), win.winfo_height()
        if w < 900 or h < 550:
            raise RuntimeError(f"Exchange window size unexpected: {w}x{h}")
        ImageGrab.grab(bbox=(x, y, x+w, y+h)).convert("RGB").save(out / "04_Exchange.png", "PNG")

        # Capture the real license store page using the app's bundled HTML file.
        # Firefox ESR is installed in CI and opens the same local page the button uses.
        import subprocess
        store = ROOT / "store" / "index.html"
        firefox = subprocess.Popen(["wkhtmltoimage", "--width", "1600", "--height", "1000",
                                    store.as_uri(), str(out / "05_License.png")],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                if (out / "05_License.png").exists() and (out / "05_License.png").stat().st_size > 30_000:
                    break
                time.sleep(0.2)
        finally:
            firefox.terminate()
            try: firefox.wait(timeout=3)
            except Exception: firefox.kill()
        if not (out / "05_License.png").exists():
            raise RuntimeError("Firefox did not render the bundled license store")

        def close_about():
            save_screen(out / "06_About.png")
            for child in app.root.winfo_children():
                if child.winfo_class() == "Toplevel":
                    try: child.destroy()
                    except Exception: pass
        app.root.after(500, close_about)
        app._show_about()
        pump(app.root, 0.8)
        print("CAPTURED_TABS=" + ",".join(p.name for p in sorted(out.glob("*.png"))))
    finally:
        try: app.close()
        except Exception:
            try: app.root.destroy()
            except Exception: pass

if __name__ == "__main__":
    main()
