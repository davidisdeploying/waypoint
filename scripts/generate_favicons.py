#!/usr/bin/env python3
"""Regenerate the raster favicons from the Waypoint diamond geometry.

The rasters are derived from `favicon.svg`, but they cannot be produced by
naively rasterizing it: the outer diamond is stroked with `currentColor` so
the SVG can invert for dark mode, and every rasterizer available here drops
that to the sibling path's red. That is exactly how the shipped favicons
became a solid red smudge with no outline at all.

So the geometry is restated directly. Both shapes are diamonds centred on the
canvas, which makes them L1-norm tests -- a point is inside a diamond of
radius R when |dx| + |dy| <= R -- and the stroke is the band between the
inset and outset diamonds. Coverage is supersampled for antialiasing.

Only the favicons are written. apple-touch-icon*.png and icon-192*.png are
correct already and are hash-guarded in the Waypoint HANDOFF; this script
must never touch them.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

# Straight from favicon.svg's 100x100 viewBox.
VIEWBOX = 100.0
OUTER_RADIUS = 41.0          # M50 9 L91 50 L50 91 L9 50 Z
STROKE_WIDTH = 8.0
INNER_RADIUS = 18.0          # M50 32 L68 50 L50 68 L32 50 Z
OUTLINE_RGB = (0x11, 0x11, 0x11)
ACCENT_RGB = (0xE5, 0x33, 0x1C)

# A miter-joined stroke on a 45-degree rhombus offsets the vertex radius by
# half the width times sqrt(2), not by half the width.
HALF_STROKE_VERTEX = STROKE_WIDTH / 2.0 * (2 ** 0.5)
STROKE_OUTER = OUTER_RADIUS + HALF_STROKE_VERTEX
STROKE_INNER = OUTER_RADIUS - HALF_STROKE_VERTEX

SAMPLES = 4  # per axis, so 16 coverage samples per pixel


def _coverage(px, py, size):
    """Return (outline, accent) coverage in 0..1 for one pixel."""
    scale = VIEWBOX / size
    outline = accent = 0
    for sy in range(SAMPLES):
        for sx in range(SAMPLES):
            x = (px + (sx + 0.5) / SAMPLES) * scale - VIEWBOX / 2
            y = (py + (sy + 0.5) / SAMPLES) * scale - VIEWBOX / 2
            distance = abs(x) + abs(y)
            if distance <= INNER_RADIUS:
                accent += 1
            elif STROKE_INNER <= distance <= STROKE_OUTER:
                outline += 1
    total = SAMPLES * SAMPLES
    return outline / total, accent / total


def render(size):
    """RGBA pixel rows for one square icon, transparent outside the mark."""
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            outline, accent = _coverage(px, py, size)
            alpha = outline + accent
            if alpha <= 0:
                row += b"\x00\x00\x00\x00"
                continue
            # Composite the two marks by coverage weight; they never overlap.
            r = (OUTLINE_RGB[0] * outline + ACCENT_RGB[0] * accent) / alpha
            g = (OUTLINE_RGB[1] * outline + ACCENT_RGB[1] * accent) / alpha
            b = (OUTLINE_RGB[2] * outline + ACCENT_RGB[2] * accent) / alpha
            row += bytes((round(r), round(g), round(b), round(min(1.0, alpha) * 255)))
        rows.append(bytes(row))
    return rows


def write_png(path, size, rows):
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag, payload):
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)
    return len(png)


def write_ico(path, renders):
    """ICO with uncompressed BGRA entries, which every browser accepts."""
    entries, payloads, offset = [], [], 6 + 16 * len(renders)
    for size, rows in renders:
        pixels = b""
        for row in reversed(rows):  # BMP rows run bottom-up
            line = bytearray()
            for i in range(0, len(row), 4):
                r, g, b, a = row[i:i + 4]
                line += bytes((b, g, r, a))
            pixels += bytes(line)
        mask_stride = ((size + 31) // 32) * 4  # 1bpp AND mask, 32-bit aligned
        mask = b"\x00" * (mask_stride * size)
        header = struct.pack(
            "<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0
        )
        payload = header + pixels + mask
        entries.append(struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(payload), offset
        ))
        payloads.append(payload)
        offset += len(payload)
    path.write_bytes(struct.pack("<HHH", 0, 1, len(renders)) + b"".join(entries) + b"".join(payloads))
    return path.stat().st_size


def main(targets):
    renders = [(size, render(size)) for size in (16, 32, 48)]
    for root in targets:
        root = Path(root)
        if not root.is_dir():
            print("skip (missing): %s" % root)
            continue
        for size, rows in renders:
            written = write_png(root / ("favicon-%d.png" % size), size, rows)
            print("  %s/favicon-%d.png  %d bytes" % (root.name, size, written))
        written = write_ico(root / "favicon.ico", renders)
        print("  %s/favicon.ico  %d bytes" % (root.name, written))


if __name__ == "__main__":
    main(sys.argv[1:] or ["."])
