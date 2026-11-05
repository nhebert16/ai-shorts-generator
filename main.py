"""
main.py — Master orchestrator for the Generated Story → Short → YouTube pipeline

Run manually:    python main.py
Run on schedule: python main.py --schedule   (runs twice daily at 4pm + 7pm)
"""

import argparse
import traceback
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler

from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
OUTPUT_DIR = Path(__import__("os").getenv("OUTPUT_DIR", "output"))
MAX_POSTS  = 1   # stories generated per run (override with --max-posts)

from db import init_db, create_video_job, update_job, log_platform_post
from story_generator import generate_story
from processor import process_batch
from tts import generate_audio, save_timestamps
from video_builder import build_video
from poster import post_to_youtube



def _get_cta(subreddit: str) -> str:
    """Return a hardcoded CTA based on subreddit."""
    sub = subreddit.lower()
    if any(x in sub for x in ["aita", "amithea", "askreddit"]):
        return "What do you think? Comment below."
    else:
        return "What would you do? Comment below."

def run_pipeline():
    print("\n" + "=" * 60)
    print(f"  Pipeline started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ── Stage 1: Generate original stories ────────────────────
    print("\n[Stage 1] Generating original stories...")
    raw_posts = [s for s in (generate_story() for _ in range(MAX_POSTS)) if s]
    if not raw_posts:
        print("[!] Story generation failed. Exiting.")
        return

    # ── Stage 2: Process with Claude ───────────────────────────
    print("\n[Stage 2] Processing with Claude...")
    processed_posts = process_batch(raw_posts)
    if not processed_posts:
        print("[!] No posts passed processing. Exiting.")
        return

    # ── Stages 3–5 per post ────────────────────────────────────
    for post in processed_posts:
        post_id = post["reddit_post_id"]
        print(f"\n{'─' * 50}")
        print(f"Processing post: {post_id}")

        job_id = create_video_job(post_id)
        update_job(job_id, script=post["script"], hook=post["title"],
                   top_comment=post.get("top_comment"), status="scripted")

        # ── Stage 3: TTS + Whisper alignment ──────────────────
        print(f"\n[Stage 3] Generating TTS for job {job_id}...")
        # Append subreddit-aware CTA to script
        cta = _get_cta(post.get("subreddit", ""))
        script_with_cta = post["script"].rstrip() + " " + cta
        tts_result = generate_audio(script_with_cta, job_id)

        if not tts_result:
            update_job(job_id, status="failed", error_message="TTS generation failed")
            print(f"[!] TTS failed for job {job_id}. Skipping.")
            continue

        save_timestamps(tts_result["word_timestamps"], job_id)
        update_job(job_id, script=script_with_cta)
        update_job(job_id, audio_path=tts_result["audio_path"], status="tts_done")

        # ── Stage 4: Build Video ───────────────────────────────
        # Notes:
        #   - music      → auto-resolved from assets/music/ by video_builder
        #   - outro      → auto-loaded from assets/outro/outro_animated_final.mp4
        #   - intro card → rendered by post_card.py using hook + subreddit
        #   - post_cards → None (intro post card handles title display)
        print(f"\n[Stage 4] Building video for job {job_id}...")
        try:
            video_path = build_video(
                job_id=job_id,
                audio_path=tts_result["audio_path"],
                word_timestamps=tts_result["word_timestamps"],
                hook=post["title"],
                post_cards=None,
                top_comment=post.get("top_comment"),
                comment_bait=post.get("comment_bait"),
                subreddit=post.get("subreddit", ""),
                upvotes=str(post.get("score", "")),
                reddit_url=post.get("url", ""),
            )
        except Exception as e:
            update_job(job_id, status="failed", error_message=str(e))
            print(f"[!] Video build failed for job {job_id}: {e}")
            traceback.print_exc()
            continue

        if not video_path:
            update_job(job_id, status="failed", error_message="video_builder returned None")
            continue

        update_job(job_id, video_path=video_path, status="rendered")
        print(f"\n[✓] Job {job_id} complete — video: {video_path}")

        # Thumbnail is extracted inside build_video — just derive the path
        from pathlib import Path as _Path
        thumbnail_path = str(OUTPUT_DIR / "thumbnails" / f"job_{job_id}_thumb.jpg")
        if not _Path(thumbnail_path).exists():
            thumbnail_path = None

        # ── Stage 5: Post to YouTube ───────────────────────────
        print(f"\n[Stage 5] Posting to YouTube...")
        try:
            # Build subreddit-specific hashtags
            sub = post.get("subreddit", "").lower()
            if "aita" in sub or "amithea" in sub:
                niche_tags = "#AITA #AmITheAsshole #RedditStories"
            elif "tifu" in sub:
                niche_tags = "#TIFU #RedditStories #Storytime"
            elif "relationship" in sub:
                niche_tags = "#RelationshipAdvice #RedditStories #Storytime"
            elif "confession" in sub or "offmychest" in sub or "trueoffmychest" in sub:
                niche_tags = "#Confessions #OffMyChest #RedditStories"
            else:
                niche_tags = "#RedditStories #Storytime #Confessions"

            yt_result = post_to_youtube(
                video_path=str(video_path),
                title=post["title"][:100],  # Max 100 chars
                description=f"{niche_tags} #Shorts #Viral",
                tags=["reddit", "stories", "aita", "viral", "shorts", "storytime", "redditstories", "confession"],
                privacy_status="public",  # Change to "unlisted" or "private" for testing
                thumbnail_path=thumbnail_path,
            )
            
            # Log result
            if yt_result["status"] == "success":
                log_platform_post(job_id, "youtube", "success", yt_result.get("video_id"), 
                                yt_result.get("url"))
                print(f"    ✓ YouTube: {yt_result['url']}")
                update_job(job_id, status="posted")
            else:
                log_platform_post(job_id, "youtube", "failed", error_message=yt_result.get("error"))
                print(f"    ✗ YouTube: {yt_result['error']}")
                update_job(job_id, status="failed", error_message=yt_result.get("error"))
        except Exception as e:
            log_platform_post(job_id, "youtube", "failed", error_message=str(e))
            print(f"    ✗ YouTube posting failed: {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"  Pipeline finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Reddit → Video pipeline")
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Run on a schedule (4pm + 7pm daily) instead of once",
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        help="Videos per run (default 1)",
    )
    args = parser.parse_args()

    if args.max_posts:
        global MAX_POSTS
        MAX_POSTS = args.max_posts

    init_db()

    if args.schedule:
        scheduler = BlockingScheduler()
        scheduler.add_job(run_pipeline, "cron", hour="16,19", minute=0)
        print("[Scheduler] Pipeline scheduled for 4:00 PM and 7:00 PM daily.")
        print("[Scheduler] Press Ctrl+C to stop.")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            print("[Scheduler] Stopped.")
    else:
        run_pipeline()


if __name__ == "__main__":
    main()
