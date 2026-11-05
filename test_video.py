"""
test_video.py — Run this to test the video pipeline.
Fetches a real Reddit post by URL using the public JSON API,
then runs the full TTS + video build pipeline on it.
"""

import os
import re
import shutil
import requests
from db import init_db
from tts import generate_audio, save_timestamps
from video_builder import build_video

init_db()

def _get_cta(subreddit: str) -> str:
    """Return a hardcoded CTA based on subreddit."""
    sub = subreddit.lower()
    if any(x in sub for x in ["aita", "amithea", "askreddit"]):
        return "What do you think? Comment below."
    else:
        return "What would you do? Comment below."

# ── Config ────────────────────────────────────────────────────────
REDDIT_POST_URL = "https://www.reddit.com/r/relationship_advice/comments/1s64wxk/my_boyfriend_28m_thinks_the_reason_why_he_cant/"
JOB_ID          = 99
HEADERS         = {"User-Agent": "RedditVideoBot/1.0 (personal project, read-only)"}
MAX_WORDS       = 280

# ── Clear caches ──────────────────────────────────────────────────
for path in [
    f"assets/cards/card_{JOB_ID}.png",
    f"output/audio/job_{JOB_ID}.mp3",
    f"output/timestamps/job_{JOB_ID}.json",
]:
    if os.path.exists(path):
        os.remove(path)
        print(f"  [Test] Cleared: {path}")

frames_dir = f"assets/cards/frames_{JOB_ID}"
if os.path.exists(frames_dir):
    shutil.rmtree(frames_dir)
    print(f"  [Test] Cleared: {frames_dir}")


# ── Fetch post from Reddit ────────────────────────────────────────
def strip_markdown(text: str) -> str:
    text = re.sub(r"\*\*?(.*?)\*\*?", r"\1", text)
    text = re.sub(r"~~(.*?)~~",        r"\1", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+",  "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s+",       "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n",   text)
    return text.strip()

def fetch_reddit_post(url: str) -> dict | None:
    # Convert to .json endpoint
    clean = url.rstrip("/")
    json_url = clean + ".json"
    print(f"  [Fetch] {json_url}")
    try:
        resp = requests.get(json_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        post = data[0]["data"]["children"][0]["data"]
        return post
    except Exception as e:
        print(f"  [!] Failed to fetch post: {e}")
        return None

print("\n[Test] Fetching Reddit post...")
post = fetch_reddit_post(REDDIT_POST_URL)

if not post:
    print("  [!] Could not fetch post. Check URL or internet connection.")
    exit(1)

title  = post.get("title", "").strip()
body   = strip_markdown(post.get("selftext", ""))
score  = post.get("score", 0)
ratio  = post.get("upvote_ratio", 0)
sub    = post.get("subreddit_name_prefixed", "r/relationship_advice")

# Trim body to MAX_WORDS
words = body.split()
if len(words) > MAX_WORDS:
    body = " ".join(words[:MAX_WORDS])
    print(f"  [Test] Body trimmed to {MAX_WORDS} words")

print(f"  [✓] Title : {title[:80]}")
print(f"  [✓] Body  : {len(body.split())} words")
print(f"  [✓] Score : {score:,} ({ratio:.0%} upvoted)")

HOOK   = title
# Prepend title so TTS reads it — the post card stays on screen while the title plays,
# then slides away as the body begins. Title + body combined must stay under MAX_WORDS.
title_words = len(title.split())
body_words  = body.split()
if title_words + len(body_words) > MAX_WORDS:
    body_words = body_words[:MAX_WORDS - title_words]
    body = " ".join(body_words)
    print(f"  [Test] Body re-trimmed to {len(body_words)} words to fit title")

cta    = _get_cta(sub)
SCRIPT = title + " " + body + " " + cta
print(f"  [✓] CTA   : {cta}")

# ── Generate audio + real timestamps ─────────────────────────────
print("\n[Test] Generating audio...")
tts_result = generate_audio(SCRIPT, job_id=JOB_ID)
if not tts_result:
    print("  [!] TTS failed — check your internet connection")
    exit(1)

save_timestamps(tts_result["word_timestamps"], job_id=JOB_ID)
print(f"  [✓] {len(tts_result['word_timestamps'])} word timestamps generated")

# ── Build video ───────────────────────────────────────────────────
print("\n[Test] Building video...")
result = build_video(
    job_id=JOB_ID,
    audio_path=tts_result["audio_path"],
    word_timestamps=tts_result["word_timestamps"],
    hook=HOOK,
    post_cards=None,
    subreddit=sub,
    upvotes=f"{score:,}",
    reddit_url=REDDIT_POST_URL,
)

print("\nResult:", result)
