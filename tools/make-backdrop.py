#!/usr/bin/env python3
"""Condition any photograph into a usable glass backdrop.

    python3 tools/make-backdrop.py ~/Downloads/snow.jpg
    python3 tools/make-backdrop.py rainforest.jpg --name forest --target 42

Why this exists: with clear (unfrosted) glass the only thing between a
photograph and 12px monospace is the panel's own fill. A dark image is fine.
A bright one — snow, sky, sand — pushes white text toward unreadable, and
you cannot tell by eye which side of the line a given photo falls on.

So this measures the image instead of trusting it: it reports the luminance
the panels will actually sit on, darkens the image until that number is in
range, and prints the contrast ratio white text will get. Pick any photo you
like; this makes it safe.

It deliberately does NOT blur. Clear glass needs the detail, and blurring the
source would throw away exactly what the refraction lens bends.
"""
import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageEnhance
except ImportError:
    sys.exit("Pillow is required:  /home/server/odoo-17.0/.venv/bin/python -m pip install pillow")

BG_DIR = Path(__file__).resolve().parent.parent / "static" / "bg"
WIDTH = 2560          # plenty for a full-bleed backdrop; keeps the file small
TARGET_MEAN = 46      # 0-255. Measured sweet spot for the current panel fills.


def luminance(img):
    """Mean perceptual luminance, 0-255."""
    small = img.convert("RGB").resize((160, 120))
    px = list(small.getdata())
    return sum(.2126 * r + .7152 * g + .0722 * b for r, g, b in px) / len(px)


def contrast_vs_white(mean_lum, fill_alpha=.62, fill_lum=8.0):
    """Approximate contrast white text will get on a panel over this image.

    The panel composites a dark fill over the photo, so the effective
    background is a blend of the two. Rough, but it ranks images correctly
    and that is all it needs to do.
    """
    eff = mean_lum * (1 - fill_alpha) + fill_lum * fill_alpha

    def lin(c):
        c /= 255
        return c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4

    L = lin(eff)
    return 1.05 / (L + .05)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="any jpg/png/webp")
    ap.add_argument("--name", default="backdrop", help="output basename (default: backdrop)")
    ap.add_argument("--target", type=float, default=TARGET_MEAN,
                    help=f"target mean luminance 0-255 (default {TARGET_MEAN}); lower = darker/safer")
    ap.add_argument("--saturation", type=float, default=.92,
                    help="colour multiplier; slightly under 1 stops the photo "
                         "competing with the UI's own accent colours")
    ap.add_argument("--width", type=int, default=WIDTH)
    ap.add_argument("--quality", type=int, default=82)
    args = ap.parse_args()

    src = Path(args.source).expanduser()
    if not src.is_file():
        sys.exit(f"no such file: {src}")

    im = Image.open(src)
    im.load()
    im = im.convert("RGB")
    print(f"source      {src.name}  {im.width}x{im.height}  {src.stat().st_size/1048576:.1f} MB")

    before = luminance(im)
    print(f"luminance   {before:.1f}  ->  white text would get {contrast_vs_white(before):.1f}:1")

    if im.width != args.width:
        h = round(im.height * args.width / im.width)
        im = im.resize((args.width, h), Image.LANCZOS)

    if args.saturation != 1.0:
        im = ImageEnhance.Color(im).enhance(args.saturation)

    # Darken multiplicatively toward the target. Multiplying preserves the
    # highlights' structure, which is what the lens needs; subtracting a
    # constant would crush the blacks flat instead.
    if before > args.target:
        im = ImageEnhance.Brightness(im).enhance(args.target / before)
        after = luminance(im)
        print(f"darkened    x{args.target/before:.2f}  ->  {after:.1f}")
    else:
        after = before
        print("darkened    not needed, already dark enough")

    ratio = contrast_vs_white(after)
    BG_DIR.mkdir(parents=True, exist_ok=True)
    out = BG_DIR / f"{args.name}.jpg"
    im.save(out, quality=args.quality, optimize=True, progressive=True)

    print(f"wrote       {out}  {out.stat().st_size/1024:.0f} KB")
    print(f"white text  {ratio:.1f}:1  {'OK' if ratio >= 7 else 'TIGHT — lower --target'}")
    print()
    print("Use it:  --bg-photo: url('/static/bg/%s.jpg');" % args.name)
    print("         in the [data-theme=\"glass\"] block of static/vision-lab.html")
    print()
    print("This is an estimate from the image's mean. Verify the real page with")
    print("the 9-point sampler before trusting it on a high-variance photo.")


if __name__ == "__main__":
    main()
