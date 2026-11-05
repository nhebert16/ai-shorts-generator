"""
screenshot.py — Renders Reddit post content as styled image cards using Pillow.

Instead of taking a real browser screenshot (which requires Selenium + ChromeDriver),
we render clean, Reddit-styled cards directly in Python. This is faster, more reliable,
and produces more consistent results.

Each post is split into chunks:
  - Chunk 0: Title card (subreddit label + post title)
  - Chunks 1..N: One paragraph per chunk

These image cards are then passed to video_builder.py to be overlaid on the
background video in sync with the narration.
"""

from PIL import Image, ImageDraw, ImageFont
import textwrap
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

FONT_PATH = os.getenv("FONT_PATH", "assets/fonts/Montserrat-Bold.ttf")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))

# Card dimensions — wide enough to be readable, not so wide it fills the screen
CARD_WIDTH = 980
CARD_PADDING = 40
CORNER_RADIUS = 24

# Reddit-style dark theme colors
BG_COLOR = (26, 26, 27)          # Reddit dark background
CARD_COLOR = (30, 30, 30)        # Slightly lighter card
TITLE_COLOR = (215, 218, 220)    # Near-white for title text
BODY_COLOR = (193, 200, 205)     # Slightly dimmer for body text
SUBREDDIT_COLOR = (255, 69, 0)   # Reddit orange
META_COLOR = (130, 130, 130)     # Dim grey for metadata

# Font sizes
SUBREDDIT_FONT_SIZE = 28
TITLE_FONT_SIZE = 38
BODY_FONT_SIZE = 32
META_FONT_SIZE = 24

# Characters per line before wrapping
TITLE_WRAP = 32
BODY_WRAP = 38


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        # Fallback to default if font not found
        return ImageFont.load_default()


def _draw_rounded_rect(draw: ImageDraw, xy: tuple, radius: int, fill: tuple):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)


def _render_text_block(draw: ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                        color: tuple, x: int, y: int, max_width: int,
                        wrap_chars: int) -> int:
    """
    Draw wrapped text, returns the y position after the last line.
    """
    lines = textwrap.wrap(text, width=wrap_chars)
    for line in lines:
        draw.text((x, y), line, font=font, fill=color)
        bbox = font.getbbox(line)
        line_height = (bbox[3] - bbox[1]) + 8
        y += line_height
    return y


def render_title_card(title: str, subreddit: str, score: int) -> Image.Image:
    """
    Renders the title card — subreddit label, upvote count, and post title.
    """
    font_sub = _load_font(SUBREDDIT_FONT_SIZE)
    font_title = _load_font(TITLE_FONT_SIZE)
    font_meta = _load_font(META_FONT_SIZE)

    # Calculate height needed
    title_lines = textwrap.wrap(title, width=TITLE_WRAP)
    line_h = TITLE_FONT_SIZE + 10
    content_height = (
        CARD_PADDING
        + SUBREDDIT_FONT_SIZE + 12   # subreddit label
        + META_FONT_SIZE + 20        # upvote count
        + len(title_lines) * line_h  # title lines
        + CARD_PADDING
    )
    card_height = max(content_height, 200)

    img = Image.new("RGBA", (CARD_WIDTH, card_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Card background
    _draw_rounded_rect(draw, (0, 0, CARD_WIDTH - 1, card_height - 1),
                       CORNER_RADIUS, CARD_COLOR)

    # Left accent bar (Reddit orange)
    draw.rectangle([0, 0, 6, card_height], fill=SUBREDDIT_COLOR)

    y = CARD_PADDING

    # Subreddit label
    draw.text((CARD_PADDING + 10, y), f"r/{subreddit}",
              font=font_sub, fill=SUBREDDIT_COLOR)
    y += SUBREDDIT_FONT_SIZE + 12

    # Upvote count
    upvotes = f"▲ {score:,} upvotes"
    draw.text((CARD_PADDING + 10, y), upvotes, font=font_meta, fill=META_COLOR)
    y += META_FONT_SIZE + 20

    # Title
    y = _render_text_block(draw, title, font_title, TITLE_COLOR,
                           CARD_PADDING + 10, y, CARD_WIDTH - CARD_PADDING * 2,
                           TITLE_WRAP)

    y += CARD_PADDING

    # Crop to actual content height
    img = img.crop((0, 0, CARD_WIDTH, y))
    return img


def render_paragraph_card(paragraph: str, paragraph_num: int,
                           total_paragraphs: int) -> Image.Image:
    """Renders a single paragraph as a styled card — no progress markers."""
    font_body = _load_font(BODY_FONT_SIZE)

    lines = textwrap.wrap(paragraph, width=BODY_WRAP)
    line_h = BODY_FONT_SIZE + 10
    content_height = CARD_PADDING + len(lines) * line_h + CARD_PADDING
    card_height = max(content_height, 120)

    img = Image.new("RGBA", (CARD_WIDTH, card_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    _draw_rounded_rect(draw, (0, 0, CARD_WIDTH - 1, card_height - 1),
                       CORNER_RADIUS, CARD_COLOR)

    y = CARD_PADDING
    y = _render_text_block(draw, paragraph, font_body, BODY_COLOR,
                           CARD_PADDING, y, CARD_WIDTH - CARD_PADDING * 2,
                           BODY_WRAP)
    y += CARD_PADDING
    img = img.crop((0, 0, CARD_WIDTH, y))
    return img


def split_script_into_paragraphs(script: str) -> list[str]:
    """
    Splits the narration script into paragraphs for chunked display.
    Tries to split on double newlines first, then falls back to
    splitting into roughly equal sentence groups.
    """
    # Try splitting on paragraph breaks
    paragraphs = [p.strip() for p in script.split("\n\n") if p.strip()]

    if len(paragraphs) >= 2:
        return paragraphs

    # Fall back: split into sentence groups of ~3 sentences each
    import re
    sentences = re.split(r'(?<=[.!?])\s+', script.strip())
    group_size = 3
    groups = []
    for i in range(0, len(sentences), group_size):
        group = " ".join(sentences[i:i + group_size])
        if group:
            groups.append(group)
    return groups if groups else [script]


def generate_post_cards(title: str, script: str, subreddit: str,
                        score: int, job_id: int) -> list[dict]:
    """
    Main entry point. Generates all image cards for a post and saves them.

    Returns a list of card dicts:
    [
        {
            "image_path": "output/cards/job_1_card_0.png",
            "paragraph_index": 0,   # 0 = title card
            "paragraph_text": "...",
            "word_count": 12,
        },
        ...
    ]
    """
    cards_dir = OUTPUT_DIR / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)

    paragraphs = split_script_into_paragraphs(script)
    total = len(paragraphs)
    results = []

    # Card 0: Title
    title_img = render_title_card(title, subreddit, score)
    title_path = cards_dir / f"job_{job_id}_card_0.png"
    title_img.save(str(title_path))

    results.append({
        "image_path": str(title_path),
        "paragraph_index": 0,
        "paragraph_text": title,
        "word_count": len(title.split()),
        "is_title": True,
    })

    print(f"  [Cards] Title card saved: {title_path}")

    # Cards 1..N: Paragraphs
    for i, para in enumerate(paragraphs):
        img = render_paragraph_card(para, i + 1, total)
        card_path = cards_dir / f"job_{job_id}_card_{i + 1}.png"
        img.save(str(card_path))

        results.append({
            "image_path": str(card_path),
            "paragraph_index": i + 1,
            "paragraph_text": para,
            "word_count": len(para.split()),
            "is_title": False,
        })

        print(f"  [Cards] Paragraph {i + 1}/{total} saved: {card_path}")

    return results


if __name__ == "__main__":
    test_title = "AITA for telling my sister her wedding dress is ugly?"
    test_script = (
        "So here's the situation. Sarah had been planning her wedding for two years, "
        "and last week she finally showed me the dress.\n\n"
        "Honestly? It wasn't great. Big, puffy, covered in lace — very 1985. "
        "She asked me directly what I thought, so I told her it wasn't really my style "
        "but that she looked happy in it.\n\n"
        "She burst into tears. Now my entire family is saying I ruined the moment. "
        "But she literally asked me for my honest opinion. Was I wrong?"
    )

    cards = generate_post_cards(
        title=test_title,
        script=test_script,
        subreddit="AmItheAsshole",
        score=4521,
        job_id=0,
    )

    print(f"\nGenerated {len(cards)} cards:")
    for c in cards:
        label = '[Title]' if c['is_title'] else '[Para ' + str(c['paragraph_index']) + ']'
        print(f"  {label} {c['word_count']} words -> {c['image_path']}")
