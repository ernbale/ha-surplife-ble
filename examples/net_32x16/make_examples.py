"""Build example GIFs for the 32 x 16 net light (product 0x0071).

The animations are the built-in effects of the integration (``core/effects.py``) plus one
scrolling text, saved as GIFs with one image pixel per LED. Upload them with the
`surplife_ble.upload_animation` service and `resample: nearest`, or pick the same effects
from the Animation selector of the device.

Usage, from the repository root:
    python examples/net_32x16/make_examples.py [output directory] [scrolling text]
Requires Pillow.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from custom_components.surplife_ble.core import effects  # noqa: E402
from custom_components.surplife_ble.core import text as text_render  # noqa: E402

COLS, ROWS = 32, 16


def save(out: Path, name: str, frames: list[list[tuple[int, int, int]]], ms: int) -> None:
    images = [
        Image.frombytes("RGB", (COLS, ROWS), bytes(c for pixel in frame for c in pixel))
        for frame in frames
    ]
    images[0].save(
        out / f"{name}.gif", save_all=True, append_images=images[1:], duration=ms, loop=0
    )
    print(f"{name}.gif: {len(frames)} frames")


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    text = sys.argv[2] if len(sys.argv) > 2 else "BENVENUTI"
    out.mkdir(parents=True, exist_ok=True)
    for name, effect in effects.EFFECTS.items():
        # A GIF frame time that roughly matches the suggested device speed.
        save(out, name, effect.build(COLS, ROWS), max(60, 400 - effect.speed * 4))
    save(out, "scrolling_text", text_render.render_text(text, cols=COLS, rows=ROWS).frames, 80)


if __name__ == "__main__":
    main()
