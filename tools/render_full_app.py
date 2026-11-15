#!/usr/bin/env python3
"""Capture the real Vkus desktop after its normal unlock and 8-second splash flow."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1] / "Vkus_3.17_NATIVE_EXCHANGE"
sys.path.insert(0, str(PROJECT_ROOT))

from PIL import ImageGrab
from vkus.app import VkusApp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/Vkus_3.18_Full_Launch.png")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    app = VkusApp()
    # CI has no human to enter the local lock-screen password. Trigger the same
    # unlock callback; the app itself then runs its real 8-second splash and UI build.
    app._unlock()

    def capture():
        try:
            app.root.update_idletasks()
            app.root.update()
            width, height = app.root.winfo_width(), app.root.winfo_height()
            if width < 1100 or height < 680:
                raise RuntimeError(f"Unexpected Vkus main window size: {width}x{height}")
            image = ImageGrab.grab().convert("RGB")
            image.save(output, format="PNG")
            if output.stat().st_size < 100_000:
                raise RuntimeError("Full application screenshot is unexpectedly small")
            print(f"FULL_APP_SCREENSHOT={output.resolve()} SIZE={width}x{height} BYTES={output.stat().st_size}")
        finally:
            try:
                app.close()
            except Exception:
                try:
                    app.root.destroy()
                except Exception:
                    pass

    # The normal splash has an intentional 8-second duration.
    app.root.after(9000, capture)
    app.root.mainloop()


if __name__ == "__main__":
    main()
