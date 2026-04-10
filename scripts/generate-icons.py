#!/usr/bin/env python3
"""
Generate PNG icons for Frood PWA from the SVG favicon.

Usage:
    python scripts/generate-icons.py [--svg PATH] [--output-dir PATH]

Defaults:
    --svg        dashboard/frontend/dist/assets/frood-favicon.svg
    --output-dir dashboard/frontend/dist/assets/icons/
"""

import argparse
import os
import sys


def _draw_frood_icon(size: int, output_path: str) -> None:
    """
    Render the Frood robot-face icon at any pixel size using Pillow.

    Bold, app-icon style matching the SVG favicon (32x32 viewBox):
      - Gold rounded-rect background (#E8A838) with subtle border
      - White antenna stem + ball
      - Semi-transparent white robot head box
      - Bold curved-arc eyes (thick strokes for visibility at small sizes)
      - Wide smile arc
      - Prominent ear sensor rectangles
    """
    from PIL import Image, ImageDraw

    s = size  # target pixel dimension
    scale = s / 32.0  # original SVG viewBox is 32x32

    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    def sc(v):
        """Scale a SVG coordinate to pixel space."""
        return v * scale

    def draw_quad_bezier(draw_obj, p0, p1, p2, fill, width, steps=32):
        """Draw a quadratic Bezier curve as a polyline."""
        points = []
        for i in range(steps + 1):
            t = i / steps
            x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0]
            y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1]
            points.append((x, y))
        for i in range(len(points) - 1):
            draw_obj.line([points[i], points[i + 1]], fill=fill, width=width)

    # --- Background: rounded rect with subtle border ---
    bg_r = sc(7)
    draw.rounded_rectangle([0, 0, s - 1, s - 1], radius=bg_r, fill=(232, 168, 56, 255))
    # Subtle darker border for depth
    draw.rounded_rectangle(
        [0, 0, s - 1, s - 1],
        radius=bg_r,
        fill=None,
        outline=(212, 146, 42, 128),
        width=max(1, int(sc(0.5))),
    )

    # --- Robot head: more visible (0.25 opacity) ---
    head_color = (255, 255, 255, int(0.25 * 255))
    head_r = sc(5)
    draw.rounded_rectangle(
        [sc(5.5), sc(7), sc(26.5), sc(27)],
        radius=head_r,
        fill=head_color,
    )

    # --- Antenna stem: thicker ---
    aw = max(2, int(sc(2)))
    draw.line([(sc(16), sc(7)), (sc(16), sc(3))], fill=(255, 255, 255, 255), width=aw)

    # --- Antenna ball: slightly larger ---
    ar = sc(2.2)
    cx, cy = sc(16), sc(2.5)
    draw.ellipse([cx - ar, cy - ar, cx + ar, cy + ar], fill=(255, 255, 255, 255))

    # --- Eyes: bold arcs (stroke-width=2.2 in SVG) ---
    eye_w = max(2, int(sc(2.2)))
    eye_color = (255, 255, 255, 255)

    # Left eye: M9.5 15 Q12.5 10.5 15.5 15
    draw_quad_bezier(
        draw,
        (sc(9.5), sc(15)),
        (sc(12.5), sc(10.5)),
        (sc(15.5), sc(15)),
        eye_color,
        eye_w,
    )

    # Right eye: M16.5 15 Q19.5 10.5 22.5 15
    draw_quad_bezier(
        draw,
        (sc(16.5), sc(15)),
        (sc(19.5), sc(10.5)),
        (sc(22.5), sc(15)),
        eye_color,
        eye_w,
    )

    # --- Smile: wider and bolder ---
    smile_w = max(2, int(sc(2.2)))
    draw_quad_bezier(
        draw,
        (sc(9.5), sc(21)),
        (sc(16), sc(27)),
        (sc(22.5), sc(21)),
        (255, 255, 255, 255),
        smile_w,
    )

    # --- Ear sensors: more prominent (0.5 opacity, larger) ---
    ear_color = (255, 255, 255, int(0.5 * 255))
    ear_r = sc(1.75)
    # Left: x=2 y=13 w=3.5 h=7
    draw.rounded_rectangle(
        [sc(2), sc(13), sc(5.5), sc(20)],
        radius=ear_r,
        fill=ear_color,
    )
    # Right: x=26.5 y=13 w=3.5 h=7
    draw.rounded_rectangle(
        [sc(26.5), sc(13), sc(30), sc(20)],
        radius=ear_r,
        fill=ear_color,
    )

    # Save as PNG (flatten RGBA onto opaque background for PWA compatibility)
    final = Image.new("RGB", (s, s), (232, 168, 56))
    final.paste(img, mask=img.split()[3])
    final.save(output_path, "PNG", optimize=True)


def _generate_ico(source_png: str, output_dir: str) -> None:
    """Generate a multi-size .ico file from an existing PNG (for Windows shortcuts)."""
    import io
    import struct

    from PIL import Image

    src = Image.open(source_png).convert("RGBA")
    sizes = [16, 32, 48, 64, 128, 256]
    entries = []
    for s in sizes:
        buf = io.BytesIO()
        src.resize((s, s), Image.LANCZOS).save(buf, format="PNG")
        entries.append((s, buf.getvalue()))

    # Build ICO binary: header + directory entries + image data
    header = struct.pack("<HHH", 0, 1, len(entries))
    data_offset = 6 + 16 * len(entries)
    dir_entries = b""
    image_data = b""
    for s, png_data in entries:
        w = h = 0 if s >= 256 else s
        dir_entries += struct.pack(
            "<BBBBHHII",
            w,
            h,
            0,
            0,
            1,
            32,
            len(png_data),
            data_offset + len(image_data),
        )
        image_data += png_data

    ico_path = os.path.join(output_dir, "frood.ico")
    with open(ico_path, "wb") as f:
        f.write(header + dir_entries + image_data)
    file_size = os.path.getsize(ico_path)
    print(f"Generated: {ico_path} ({file_size} bytes)")


def generate_with_pillow(svg_path: str, output_dir: str) -> None:
    """Generate icons by directly drawing the Frood robot face with Pillow."""
    from PIL import Image  # noqa: F401 — ensure Pillow is available

    icons = [
        ("icon-192.png", 192),
        ("icon-512.png", 512),
        ("apple-touch-icon-180.png", 180),
    ]

    for filename, size in icons:
        out_path = os.path.join(output_dir, filename)
        _draw_frood_icon(size, out_path)
        file_size = os.path.getsize(out_path)
        print(f"Generated: {out_path} ({file_size} bytes)")

    # Also generate .ico for Windows desktop shortcuts
    png_512 = os.path.join(output_dir, "icon-512.png")
    if os.path.isfile(png_512):
        _generate_ico(png_512, output_dir)


def generate(svg_path: str, output_dir: str) -> None:
    """
    Convert SVG favicon to PNG icons at multiple sizes for PWA use.

    Tries renderers in order of quality:
    1. cairosvg — best vector rendering (requires Cairo native library)
    2. svglib + reportlab — fallback vector rendering (also requires Cairo)
    3. Pillow — faithful pixel-art recreation of the robot face (pure Python)
    """
    os.makedirs(output_dir, exist_ok=True)

    icons = [
        ("icon-192.png", 192, 192),
        ("icon-512.png", 512, 512),
        ("apple-touch-icon-180.png", 180, 180),
    ]

    # Try cairosvg first (best SVG rendering quality)
    try:
        import cairosvg

        for filename, width, height in icons:
            out_path = os.path.join(output_dir, filename)
            cairosvg.svg2png(
                url=svg_path,
                write_to=out_path,
                output_width=width,
                output_height=height,
            )
            size = os.path.getsize(out_path)
            print(f"Generated: {out_path} ({size} bytes)")

        # Generate .ico for Windows desktop shortcuts
        png_512 = os.path.join(output_dir, "icon-512.png")
        if os.path.isfile(png_512):
            _generate_ico(png_512, output_dir)

        return

    except (ImportError, OSError):
        print(
            "cairosvg not available (Cairo library missing), trying svglib+reportlab...",
            file=sys.stderr,
        )

    # Fallback: svglib + reportlab
    try:
        from reportlab.graphics import renderPM
        from svglib.svglib import svg2rlg

        drawing = svg2rlg(svg_path)
        if drawing is None:
            raise RuntimeError(f"svglib could not parse: {svg_path}")

        for filename, width, height in icons:
            out_path = os.path.join(output_dir, filename)
            from PIL import Image as PILImage

            # Render at target size via reportlab, then resize with Pillow
            renderPM.drawToFile(drawing, out_path, fmt="PNG")
            img = PILImage.open(out_path).resize((width, height), PILImage.LANCZOS)
            img.save(out_path, "PNG")
            size = os.path.getsize(out_path)
            print(f"Generated: {out_path} ({size} bytes)")

        # Generate .ico for Windows desktop shortcuts
        png_512 = os.path.join(output_dir, "icon-512.png")
        if os.path.isfile(png_512):
            _generate_ico(png_512, output_dir)

        return

    except (ImportError, OSError):
        print("svglib+reportlab not available, using Pillow pixel-art renderer...", file=sys.stderr)

    # Pure-Python fallback: draw the robot face directly with Pillow
    try:
        generate_with_pillow(svg_path, output_dir)
        return

    except ImportError as e:
        print(f"ERROR: No suitable image library found: {e}", file=sys.stderr)
        print("Install Pillow: pip install Pillow", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate PWA icons from SVG favicon")
    parser.add_argument(
        "--svg",
        default="dashboard/frontend/dist/assets/frood-favicon.svg",
        help="Path to source SVG file",
    )
    parser.add_argument(
        "--output-dir",
        default="dashboard/frontend/dist/assets/icons/",
        help="Directory to write PNG icons into",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.svg):
        print(f"ERROR: SVG file not found: {args.svg}", file=sys.stderr)
        sys.exit(1)

    generate(args.svg, args.output_dir)
