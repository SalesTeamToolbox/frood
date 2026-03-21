#!/usr/bin/env python3
"""
Generate PNG icons for Agent42 PWA from the SVG favicon.

Usage:
    python scripts/generate-icons.py [--svg PATH] [--output-dir PATH]

Defaults:
    --svg        dashboard/frontend/dist/assets/agent42-favicon.svg
    --output-dir dashboard/frontend/dist/assets/icons/
"""

import argparse
import os
import sys


def _draw_agent42_icon(size: int, output_path: str) -> None:
    """
    Render the Agent42 robot-face icon at any pixel size using Pillow.

    Faithfully replicates the SVG favicon (32x32 viewBox) at the target resolution:
      - Gold rounded-rect background (#E8A838)
      - White antenna stem + ball
      - Semi-transparent white robot head box
      - Two curved-arc eyes
      - Smile arc
      - Ear sensor rectangles
    """
    from PIL import Image, ImageDraw

    s = size  # target pixel dimension
    scale = s / 32.0  # original SVG viewBox is 32x32

    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    def sc(v):
        """Scale a SVG coordinate to pixel space."""
        return v * scale

    # --- Background: rect 0 0 32 32 rx=6 fill=#E8A838 ---
    bg_r = sc(6)
    draw.rounded_rectangle([0, 0, s - 1, s - 1], radius=bg_r, fill=(232, 168, 56, 255))

    # --- Antenna stem: line x1=16 y1=7 x2=16 y2=3.5 stroke=#fff width=1.5 ---
    aw = max(1, int(sc(1.5)))
    draw.line([(sc(16), sc(7)), (sc(16), sc(3.5))], fill=(255, 255, 255, 255), width=aw)

    # --- Antenna ball: circle cx=16 cy=2.5 r=2 fill=#fff ---
    ar = sc(2)
    cx, cy = sc(16), sc(2.5)
    draw.ellipse([cx - ar, cy - ar, cx + ar, cy + ar], fill=(255, 255, 255, 255))

    # --- Robot head: rect x=6 y=7 w=20 h=19 rx=5 fill=#fff fill-opacity=0.15 ---
    head_color = (255, 255, 255, int(0.15 * 255))
    head_r = sc(5)
    draw.rounded_rectangle(
        [sc(6), sc(7), sc(6 + 20), sc(7 + 19)],
        radius=head_r,
        fill=head_color,
    )

    # --- Eyes: two arc paths drawn as bezier curves ---
    # Left eye: path "M10 14 Q12.5 11 15 14" — quadratic bezier
    # Right eye: path "M17 14 Q19.5 11 22 14"
    eye_w = max(1, int(sc(1.5)))
    eye_color = (255, 255, 255, 255)

    def draw_quad_bezier(draw_obj, p0, p1, p2, fill, width, steps=20):
        """Draw a quadratic Bezier curve as a polyline."""
        points = []
        for i in range(steps + 1):
            t = i / steps
            x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0]
            y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1]
            points.append((x, y))
        for i in range(len(points) - 1):
            draw_obj.line([points[i], points[i + 1]], fill=fill, width=width)

    # Left eye: M10 14 Q12.5 11 15 14
    draw_quad_bezier(
        draw,
        (sc(10), sc(14)),
        (sc(12.5), sc(11)),
        (sc(15), sc(14)),
        eye_color,
        eye_w,
    )

    # Right eye: M17 14 Q19.5 11 22 14
    draw_quad_bezier(
        draw,
        (sc(17), sc(14)),
        (sc(19.5), sc(11)),
        (sc(22), sc(14)),
        eye_color,
        eye_w,
    )

    # --- Smile: M10 21 Q16 26 22 21 ---
    smile_w = max(1, int(sc(1.5)))
    draw_quad_bezier(
        draw,
        (sc(10), sc(21)),
        (sc(16), sc(26)),
        (sc(22), sc(21)),
        (255, 255, 255, 255),
        smile_w,
    )

    # --- Ear sensors: two rects fill-opacity=0.4 ---
    ear_color = (255, 255, 255, int(0.4 * 255))
    ear_r = sc(1.5)
    # Left: x=3 y=13 w=3 h=6
    draw.rounded_rectangle(
        [sc(3), sc(13), sc(3 + 3), sc(13 + 6)],
        radius=ear_r,
        fill=ear_color,
    )
    # Right: x=26 y=13 w=3 h=6
    draw.rounded_rectangle(
        [sc(26), sc(13), sc(26 + 3), sc(13 + 6)],
        radius=ear_r,
        fill=ear_color,
    )

    # Save as PNG (flatten RGBA onto opaque background for PWA compatibility)
    final = Image.new("RGB", (s, s), (232, 168, 56))
    final.paste(img, mask=img.split()[3])
    final.save(output_path, "PNG", optimize=True)


def generate_with_pillow(svg_path: str, output_dir: str) -> None:
    """Generate icons by directly drawing the Agent42 robot face with Pillow."""
    from PIL import Image  # noqa: F401 — ensure Pillow is available

    icons = [
        ("icon-192.png", 192),
        ("icon-512.png", 512),
        ("apple-touch-icon-180.png", 180),
    ]

    for filename, size in icons:
        out_path = os.path.join(output_dir, filename)
        _draw_agent42_icon(size, out_path)
        file_size = os.path.getsize(out_path)
        print(f"Generated: {out_path} ({file_size} bytes)")


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
        default="dashboard/frontend/dist/assets/agent42-favicon.svg",
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
