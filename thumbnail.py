"""
thumbnail.py — Auto-generates YouTube/Facebook thumbnails using Pillow.

Layout:
  - Bold gradient background (dark red → dark purple, feels dramatic)
  - Large ALL CAPS hook text centered
  - Reddit logo watermark bottom right
  - Subtle vignette overlay for depth

Output: 1280x720 JPEG (standard YouTube thumbnail size)
Also saves a 1080x1920 version for Facebook/Instagram cover use.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
import textwrap
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

FONT_PATH = os.getenv("FONT_PATH", "assets/fonts/Montserrat-Bold.ttf")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))

# Thumbnail dimensions
THUMB_W = 1280
THUMB_H = 720

# Vertical cover dimensions (Facebook/Instagram)
COVER_W = 1080
COVER_H = 1920

# Color schemes — rotated per video to avoid looking identical
COLOR_SCHEMES = [
    {"grad_top": (139, 0, 0),    "grad_bot": (40, 0, 60),   "text": (255, 255, 255), "accent": (255, 69, 0)},   # dark red → purple
    {"grad_top": (0, 30, 80),    "grad_bot": (0, 0, 20),    "text": (255, 255, 255), "accent": (0, 180, 255)},   # dark blue
    {"grad_top": (20, 60, 20),   "grad_bot": (5, 15, 5),    "text": (255, 255, 255), "accent": (50, 220, 50)},   # dark green
    {"grad_top": (80, 40, 0),    "grad_bot": (20, 10, 0),   "text": (255, 255, 255), "accent": (255, 180, 0)},   # dark amber
]


def _make_gradient(width: int, height: int, top_color: tuple, bot_color: tuple) -> Image.Image:
    """Create a vertical gradient background."""
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / height
        r = int(top_color[0] * (1 - t) + bot_color[0] * t)
        g = int(top_color[1] * (1 - t) + bot_color[1] * t)
        b = int(top_color[2] * (1 - t) + bot_color[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return img


def _add_vignette(img: Image.Image) -> Image.Image:
    """Add a subtle dark vignette around the edges."""
    w, h = img.size
    vignette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(vignette)

    steps = 60
    for i in range(steps):
        alpha = int(180 * (i / steps) ** 2)
        margin = i * 6
        draw.rectangle(
            [margin, margin, w - margin, h - margin],
            outline=(0, 0, 0, alpha),
        )

    img = img.convert("RGBA")
    img = Image.alpha_composite(img, vignette)
    return img.convert("RGB")


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _draw_centered_text(draw: ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                         color: tuple, canvas_w: int, y: int,
                         stroke_color=(0, 0, 0), stroke_width=4) -> int:
    """Draw centered text with stroke. Returns y position after text."""
    lines = textwrap.wrap(text, width=20)
    for line in lines:
        bbox = font.getbbox(line)
        text_w = bbox[2] - bbox[0]
        x = (canvas_w - text_w) // 2
        # Stroke
        for dx in range(-stroke_width, stroke_width + 1):
            for dy in range(-stroke_width, stroke_width + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, font=font, fill=stroke_color)
        # Main text
        draw.text((x, y), line, font=font, fill=color)
        line_h = (bbox[3] - bbox[1]) + 16
        y += line_h
    return y


def _add_accent_bar(draw: ImageDraw, width: int, y: int, color: tuple, thickness: int = 6):
    """Draw a horizontal accent line."""
    draw.rectangle([80, y, width - 80, y + thickness], fill=color)


def generate_thumbnail(thumbnail_text: str, subreddit: str,
                        job_id: int, scheme_index: int = 0) -> str:
    """
    Generates a 1280x720 YouTube thumbnail.
    Returns the path to the saved file.
    """
    thumbs_dir = OUTPUT_DIR / "thumbnails"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    output_path = thumbs_dir / f"job_{job_id}_thumb.jpg"

    scheme = COLOR_SCHEMES[scheme_index % len(COLOR_SCHEMES)]

    # Base gradient
    img = _make_gradient(THUMB_W, THUMB_H, scheme["grad_top"], scheme["grad_bot"])
    img = _add_vignette(img)

    draw = ImageDraw.Draw(img)

    font_main = _load_font(108)
    font_sub = _load_font(42)
    font_small = _load_font(32)

    # Top label: subreddit
    sub_text = f"r/{subreddit}".upper()
    bbox = font_small.getbbox(sub_text)
    sub_w = bbox[2] - bbox[0]
    draw.text(((THUMB_W - sub_w) // 2, 60), sub_text,
              font=font_small, fill=scheme["accent"])

    # Accent bar below subreddit
    _add_accent_bar(draw, THUMB_W, 110, scheme["accent"])

    # Main thumbnail text — centered vertically
    total_lines = len(textwrap.wrap(thumbnail_text, width=20))
    line_h = 108 + 16
    total_text_h = total_lines * line_h
    start_y = (THUMB_H - total_text_h) // 2 + 20

    _draw_centered_text(draw, thumbnail_text, font_main,
                        scheme["text"], THUMB_W, start_y,
                        stroke_color=(0, 0, 0), stroke_width=5)

    # Bottom accent bar
    _add_accent_bar(draw, THUMB_W, THUMB_H - 90, scheme["accent"])

    # Bottom label
    bottom_text = "FULL STORY IN VIDEO 👇"
    bbox = font_small.getbbox(bottom_text)
    bw = bbox[2] - bbox[0]
    draw.text(((THUMB_W - bw) // 2, THUMB_H - 72), bottom_text,
              font=font_small, fill=scheme["text"])

    img.save(str(output_path), "JPEG", quality=95)
    print(f"  [Thumbnail] Saved: {output_path}")
    return str(output_path)


def extract_thumbnail(video_path: str, job_id: int, timestamp: float = 0.5) -> str | None:
    """
    Extract a frame from the video as a YouTube thumbnail.
    Defaults to 0.5s — post card is fully visible by then.
    Returns path to the saved JPEG, or None on failure.
    """
    import subprocess
    thumbs_dir = OUTPUT_DIR / "thumbnails"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    output_path = thumbs_dir / f"job_{job_id}_thumb.jpg"

    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",          # high quality JPEG
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            print(f"  [!] Thumbnail extraction failed: {result.stderr.decode()}")
            return None
        print(f"  [Thumbnail] Extracted frame at {timestamp}s: {output_path}")
        return str(output_path)
    except Exception as e:
        print(f"  [!] Thumbnail extraction error: {e}")
        return None


if __name__ == "__main__":
    path = generate_thumbnail(
        thumbnail_text="SHE BANNED HER MOM FROM THE WEDDING",
        subreddit="AmItheAsshole",
        job_id=0,
        scheme_index=0,
    )
    print(f"Thumbnail saved to: {path}")
    print("Open it in Windows Photos to preview.")
