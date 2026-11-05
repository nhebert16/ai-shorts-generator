"""
test_video_askreddit.py — Test the AskReddit short-form pipeline.
Scrapes a suitable AskReddit post + top comment, processes it through
Claude, generates TTS, and builds a short-form video. No upload.
"""

import os
import shutil
from db import init_db
from scraper import (
    fetch_top_posts, fetch_top_comment, is_suitable, engagement_score,
    strip_markdown, count_words,
    ASKREDDIT_MIN_POST_SCORE, ASKREDDIT_MIN_COMMENT_SCORE,
    ASKREDDIT_MIN_WORDS, ASKREDDIT_MAX_WORDS,
    TIME_FILTERS, REQUEST_DELAY, HEADERS,
)
from db import is_comment_processed, mark_comment_processed
from processor import process_batch
from tts import generate_audio, save_timestamps
from video_builder import build_video
import time

init_db()

JOB_ID = 97

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


# ── Scrape AskReddit ──────────────────────────────────────────────
print("\n[Test] Scraping r/AskReddit...")

post_data = None
seen_post_ids = set()

for time_filter in TIME_FILTERS:
    print(f"  [→] Fetching top posts ({time_filter})...")
    posts = fetch_top_posts("AskReddit", time_filter)
    time.sleep(REQUEST_DELAY)

    for post in posts:
        post_id = post.get("id")
        if post_id in seen_post_ids:
            continue
        seen_post_ids.add(post_id)

        suitable, reason = is_suitable(post, subreddit="AskReddit")
        if not suitable:
            continue

        # Fetch top comment meeting criteria
        comment = fetch_top_comment(
            "AskReddit", post_id,
            min_words=ASKREDDIT_MIN_WORDS,
            max_words=ASKREDDIT_MAX_WORDS,
            min_score=ASKREDDIT_MIN_COMMENT_SCORE,
        )
        if not comment:
            continue
        if is_comment_processed(comment["id"]):
            continue

        # Found a good one
        clean_body = strip_markdown(comment["body"])
        word_count = count_words(clean_body)
        eng_score  = engagement_score(post)

        post_data = {
            "reddit_post_id":   comment["id"],
            "subreddit":        "AskReddit",
            "title":            post["title"],
            "body":             clean_body,
            "score":            post["score"],
            "upvote_ratio":     post.get("upvote_ratio", 0),
            "engagement_score": round(eng_score),
            "word_count":       word_count,
            "top_comment":      None,
            "url":              f"https://reddit.com{post['permalink']}",
            "format":           "askreddit",
        }

        print(f"  [✓] Post  : {post['title'][:70]}")
        print(f"  [✓] Comment: {word_count} words | score {comment['score']:,}")
        print(f"  [✓] Post score: {post['score']:,} ({post.get('upvote_ratio',0):.0%})")
        break

    if post_data:
        break

if not post_data:
    print("  [!] No suitable AskReddit post+comment found.")
    exit(1)


# ── Process through Claude ────────────────────────────────────────
print("\n[Test] Processing with Claude...")
processed = process_batch([post_data])
if not processed:
    print("  [!] Processing failed.")
    exit(1)

result   = processed[0]
HOOK     = result["title"]
cta      = "What do you think? Comment below."
SCRIPT   = result["script"].rstrip() + " " + cta

print(f"  [✓] Script : {len(SCRIPT.split())} words")
print(f"  [✓] CTA    : {cta}")


# ── Generate audio + Whisper timestamps ──────────────────────────
print("\n[Test] Generating audio...")
tts_result = generate_audio(SCRIPT, job_id=JOB_ID)
if not tts_result:
    print("  [!] TTS failed — check Whisper is installed in your venv.")
    exit(1)

save_timestamps(tts_result["word_timestamps"], job_id=JOB_ID)
print(f"  [✓] {len(tts_result['word_timestamps'])} word timestamps")


# ── Build video ───────────────────────────────────────────────────
print("\n[Test] Building video...")
video_result = build_video(
    job_id=JOB_ID,
    audio_path=tts_result["audio_path"],
    word_timestamps=tts_result["word_timestamps"],
    hook=HOOK,
    post_cards=None,
    subreddit="r/AskReddit",
    upvotes=f"{post_data['score']:,}",
    reddit_url=post_data["url"],
)

print("\nResult:", video_result)
