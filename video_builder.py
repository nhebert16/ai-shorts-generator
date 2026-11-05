"""
video_builder.py — MoviePy v2, 720x1280 mobile vertical

Fixes applied:
- Intro Reddit post card (non-opaque dark card, awards row)
- Music always plays via auto-resolved get_music_path()
- Subtitles moved up to SUB_Y=860 so they never get clipped
- Outro always uses assets/outro/outro_animated_final.mp4
"""

import os
import textwrap
import numpy as np
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from moviepy import (
    VideoFileClip,
    AudioFileClip,
    ImageClip,
    TextClip,
    CompositeVideoClip,
    ColorClip,
    concatenate_audioclips,
    concatenate_videoclips,
    AudioArrayClip,
    CompositeAudioClip,
)

from music import get_music_path
from post_card import render_post_card
from thumbnail import extract_thumbnail

load_dotenv()

BACKGROUND_PATH  = os.getenv("BACKGROUND_VIDEO_PATH", "assets/background.mp4")
FONT_PATH        = os.getenv("FONT_PATH", "assets/fonts/Montserrat-Bold.ttf")
SUB_FONT_PATH    = "assets/fonts/Bangers-Regular.ttf"
OUTPUT_DIR       = Path(os.getenv("OUTPUT_DIR", "output"))
MUSIC_VOLUME     = float(os.getenv("MUSIC_VOLUME", "0.4"))  # Reduced by 20%

# Permanent branded outro
OUTRO_VIDEO_PATH = Path("assets/outro/outro_animated_final.mp4")
SFX_INTRO_PATH   = Path(os.getenv("SFX_INTRO_PATH", "assets/sfx/pop-cut.mp3"))

WIDTH  = 720
HEIGHT = 1280
FPS    = 30

VERDICT_DURATION    = 0.0   # Verdict card removed
OUTRO_DURATION      = 3.0
INTRO_CARD_DURATION = 3.5
SFX_DELAY           = 0.25  # Narration/subtitles start after SFX plays

CARD_MARGIN = 40

SUB_FONT_SIZE    = 72
SUB_COLOR        = "white"
SUB_STROKE_COLOR = "black"
SUB_STROKE_WIDTH = 6
WORDS_PER_SUBTITLE = 1
SUB_CENTER_Y     = 480
SUB_BELOW_CARD_Y = 900


def build_video(job_id: int, audio_path: str, word_timestamps: list[dict],
                hook: str, post_cards: list[dict] = None,
                top_comment: str = None, comment_bait: str = None,
                subreddit: str = "", music_path: str = None,
                outro_card_path: str = None, outro_chime_path: str = None,
                reddit_url: str = "",
                upvotes: str = "", comments: str = "") -> str | None:

    video_dir = OUTPUT_DIR / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    output_path = video_dir / f"job_{job_id}.mp4"

    try:
        narration = AudioFileClip(audio_path).with_start(SFX_DELAY)
        narration_duration = narration.duration
        total_duration = SFX_DELAY + narration_duration + OUTRO_DURATION

        bg = _build_background(total_duration)

        # Dynamic intro card duration — stays on screen until the title is fully read.
        # We expand abbreviations the same way TTS does so word count matches timestamps.
        import re
        def _expand_for_count(text):
            abbrevs = [
                (r'\bAITA\b', 'Am I the asshole'),
                (r'\bWIBTA\b', 'Would I be the asshole'),
                (r'\bNTA\b', 'Not the asshole'),
                (r'\bYTA\b', 'You are the asshole'),
                (r'\bSIL\b', 'sister in law'),
                (r'\bBIL\b', 'brother in law'),
                (r'\bMIL\b', 'mother in law'),
                (r'\bFIL\b', 'father in law'),
                (r'\bSTBX\b', 'soon to be ex'),
                (r'\bSTBXH\b', 'soon to be ex husband'),
                (r'\bSTBXW\b', 'soon to be ex wife'),
            ]
            for pattern, replacement in abbrevs:
                text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            return text

        expanded_hook = _expand_for_count(hook.strip())
        hook_words = expanded_hook.lower().split()
        hook_word_count = len(hook_words)

        intro_card_duration = INTRO_CARD_DURATION  # default
        if word_timestamps and hook_word_count > 0:
            # Match the hook words against the leading timestamps by scanning forward.
            # Allow up to hook_word_count + 4 timestamps to account for any expansion
            # differences between _expand_for_count and tts._preprocess_script.
            scan_limit = min(hook_word_count + 6, len(word_timestamps))
            # The title ends at whichever timestamp index best aligns — use the
            # timestamp at hook_word_count - 1 but capped to scan_limit.
            title_end_idx = min(hook_word_count - 1, scan_limit - 1)
            title_read_end = word_timestamps[title_end_idx]["end"] + 0.5
            intro_card_duration = max(INTRO_CARD_DURATION, title_read_end)

        print(f"  [VideoBuilder] Intro card: {intro_card_duration:.2f}s ({hook_word_count} title words)")

        # Extend post card by SFX_DELAY so it stays in sync with delayed narration
        intro_card_duration += SFX_DELAY

        # Shift all subtitle timestamps forward by SFX_DELAY to match delayed narration
        shifted_timestamps = [
            {**wt, "start": wt["start"] + SFX_DELAY, "end": wt["end"] + SFX_DELAY}
            for wt in word_timestamps
        ]

        # Intro Reddit post card
        intro_clips = _build_intro_card(
            job_id=job_id,
            title=hook,
            subreddit=subreddit or "r/AITA",
            upvotes=upvotes,
            comments=comments,
            duration=intro_card_duration,
        )

        # No body cards — intro post card is the only overlay
        card_clips = []

        subtitle_clips = _build_subtitles(shifted_timestamps, intro_end=intro_card_duration)

        # Outro
        outro_clips  = []
        outro_audio  = None
        outro_start  = SFX_DELAY + narration_duration
        if OUTRO_VIDEO_PATH.exists():
            outro_clips, outro_audio = _build_outro_video(outro_start)
        elif outro_card_path:
            outro_clips = _build_outro(outro_card_path, OUTRO_DURATION, start=outro_start)

        # Audio — music always auto-resolves
        # Narration is offset by SFX_DELAY; pad with silence at the end for outro
        silence_end = AudioArrayClip(
            np.zeros((max(1, int(OUTRO_DURATION * 44100)), 2)),
            fps=44100
        ).with_duration(OUTRO_DURATION).with_start(SFX_DELAY + narration_duration)

        full_narration = CompositeAudioClip([narration, silence_end]).with_duration(total_duration)

        if not music_path:
            music_path = get_music_path(total_duration)

        final_audio = full_narration
        if music_path:
            music_audio = _build_music_track(music_path, total_duration)
            if music_audio:
                final_audio = CompositeAudioClip([music_audio, full_narration])

        # Mix in outro audio (the static/chime sounds from the outro MP4)
        if outro_audio:
            try:
                final_audio = CompositeAudioClip([final_audio, outro_audio])
            except Exception as e:
                print(f"  [!] Outro audio mix failed: {e}")

        # Intro sound effect — plays at t=0 to catch attention
        if SFX_INTRO_PATH.exists():
            try:
                sfx = AudioFileClip(str(SFX_INTRO_PATH)).with_start(0)
                final_audio = CompositeAudioClip([final_audio, sfx])
                print(f"  [SFX] Intro sound effect added: {SFX_INTRO_PATH.name}")
            except Exception as e:
                print(f"  [!] Intro SFX failed: {e}")
        else:
            print(f"  [!] Intro SFX not found: {SFX_INTRO_PATH}")

        if outro_chime_path:
            try:
                chime = AudioFileClip(outro_chime_path).with_start(outro_start)
                final_audio = CompositeAudioClip([final_audio, chime])
            except Exception as e:
                print(f"  [!] Chime mix failed: {e}")

        all_clips = [bg] + intro_clips + card_clips + subtitle_clips + outro_clips
        final = CompositeVideoClip(all_clips, size=(WIDTH, HEIGHT))
        final = final.with_audio(final_audio).with_duration(total_duration)

        print(f"  [VideoBuilder] Rendering {total_duration:.1f}s at {WIDTH}x{HEIGHT}...")

        final.write_videofile(
            str(output_path),
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            audio_bitrate="320k",
            bitrate="10000k",  # 10Mbps — YouTube recommends 8-12Mbps for 1080p Shorts
            threads=4,
            preset="medium",
            logger="bar",
        )

        _write_post_log(job_id, str(output_path), reddit_url, hook)
        print(f"  [✓] Video saved: {output_path}")

        # Extract first frame with post card visible as YouTube thumbnail
        extract_thumbnail(str(output_path), job_id, timestamp=0.5)

        return str(output_path)

    except Exception as e:
        print(f"  [!] Video build failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def _write_post_log(job_id: int, video_path: str, reddit_url: str, hook: str):
    log_path = OUTPUT_DIR / "post_log.txt"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] Job {job_id}\n")
        f.write(f"  Video : {video_path}\n")
        f.write(f"  Post  : {reddit_url}\n")
        f.write(f"  Hook  : {hook}\n\n")
    print(f"  [Log] Entry written to {log_path}")


# ── INTRO CARD ────────────────────────────────────────────────────

def _build_intro_card(job_id, title, subreddit, upvotes, comments, duration=None):
    """
    Builds intro card without zoom effect.
    Card is displayed at normal 100% scale for the full intro duration.
    Award bounce animation is baked into the frames from post_card.py.
    duration — if provided, overrides INTRO_CARD_DURATION for single-frame cards.
    """
    card_duration = duration if duration is not None else INTRO_CARD_DURATION
    try:
        result = render_post_card(
            job_id=job_id,
            title=title,
            subreddit=subreddit,
            upvotes=upvotes,
            comments=comments,
            animated=True,
            duration=card_duration,
        )

        # Resolve frames list or single path
        if isinstance(result, list):
            frames = result   # [(path, start, dur), ...]
        else:
            frames = [(result, 0, card_duration)]

        clips = []

        for path, start, dur in frames:
            img = ImageClip(path)
            # Extend each frame by 1 frame (1/30s) to close any compositing gap
            # that causes flickering between adjacent frames
            padded_dur = dur + (1 / 30)
            x_pos = (WIDTH - img.w) // 2
            y_pos = (HEIGHT - img.h) // 2
            clips.append(img.with_start(start).with_duration(padded_dur)
                            .with_position((x_pos, y_pos)))

        return clips
    except Exception as e:
        print(f"  [!] Intro card failed: {e}")
        import traceback; traceback.print_exc()
        return []
        print(f"  [!] Intro card failed: {e}")
        import traceback; traceback.print_exc()
        return []



# ── OUTRO ─────────────────────────────────────────────────────────

def _build_outro_video(start):
    """Use the permanent pre-rendered branded outro video, keeping its audio."""
    try:
        clip = (VideoFileClip(str(OUTRO_VIDEO_PATH), audio=True)
                .with_start(start)
                .with_position((0, 0)))
        return [clip], clip.audio.with_start(start) if clip.audio else None
    except Exception as e:
        print(f"  [!] Outro video failed: {e}")
        return [], None


def _build_outro(outro_card_path, duration, start):
    """Fallback static image outro if the video file is missing."""
    try:
        fade_duration = 0.6
        steps = 12
        clips = []
        for i in range(steps):
            t = i / steps
            clips.append(ImageClip(outro_card_path)
                         .resized((WIDTH, HEIGHT))
                         .with_start(start + t * fade_duration)
                         .with_duration(fade_duration / steps + 0.01)
                         .with_position((0, 0)).with_opacity(t))
        clips.append(ImageClip(outro_card_path)
                     .resized((WIDTH, HEIGHT))
                     .with_start(start + fade_duration)
                     .with_duration(duration - fade_duration)
                     .with_position((0, 0)))
        return clips
    except Exception as e:
        print(f"  [!] Outro card failed: {e}")
        return []


# ── BACKGROUND ───────────────────────────────────────────────────

def _build_background(duration):
    import random
    bg_video = VideoFileClip(BACKGROUND_PATH, audio=False)

    bg_aspect     = bg_video.w / bg_video.h
    target_aspect = WIDTH / HEIGHT

    if bg_aspect > target_aspect:
        new_w    = int(bg_video.h * target_aspect)
        x1       = (bg_video.w - new_w) // 2
        bg_video = bg_video.cropped(x1=x1, y1=0, x2=x1 + new_w, y2=bg_video.h)
    else:
        new_h    = int(bg_video.w / target_aspect)
        y1       = (bg_video.h - new_h) // 2
        bg_video = bg_video.cropped(x1=0, y1=y1, x2=bg_video.w, y2=y1 + new_h)

    bg_video = bg_video.resized((WIDTH, HEIGHT))

    # Pick a random start point, ensuring enough video remains for full duration
    # Skip first 3s to avoid fade-from-black in most source footage
    BG_SKIP  = 3.0
    max_start = max(BG_SKIP, bg_video.duration - duration)
    if max_start > BG_SKIP:
        bg_start = random.uniform(BG_SKIP, max_start)
        print(f"  [BG] Random start: {bg_start:.1f}s (video: {bg_video.duration:.1f}s, need: {duration:.1f}s)")
    else:
        bg_start = BG_SKIP
        print(f"  [BG] Video too short for random start — looping from {BG_SKIP}s")

    if bg_video.duration - bg_start < duration:
        # Not enough remaining — use what we have then loop from beginning
        part1     = bg_video.subclipped(bg_start)
        remaining = duration - part1.duration
        loops     = int(np.ceil(remaining / bg_video.duration)) + 1
        looped    = concatenate_videoclips([bg_video] * loops).subclipped(0, remaining)
        bg_video  = concatenate_videoclips([part1, looped]).subclipped(0, duration)
    else:
        bg_video = bg_video.subclipped(bg_start, bg_start + duration)

    overlay = (ColorClip(size=(WIDTH, HEIGHT), color=(0, 0, 0))
               .with_opacity(0.45).with_duration(duration))

    return CompositeVideoClip([bg_video, overlay])


# ── BODY CARDS ───────────────────────────────────────────────────

def _build_card_overlays(post_cards, word_timestamps, narration_duration):
    if not post_cards or not word_timestamps:
        return []

    total_words    = len(word_timestamps)
    num_cards      = len(post_cards)
    clips          = []
    words_per_card = max(1, total_words // num_cards)

    for i, card in enumerate(post_cards):
        start_idx  = min(i * words_per_card, total_words - 1)
        end_idx    = min((i + 1) * words_per_card - 1 if i < num_cards - 1 else total_words - 1,
                         total_words - 1)
        start_time = word_timestamps[start_idx]["start"]
        end_time   = word_timestamps[end_idx]["end"]
        duration   = max(end_time - start_time, 0.5)

        try:
            img_clip = ImageClip(card["image_path"])
            scale    = (WIDTH - CARD_MARGIN * 2) / img_clip.w
            img_clip = img_clip.resized(scale)
            x_pos    = (WIDTH  - img_clip.w) // 2
            y_pos    = (HEIGHT - img_clip.h) // 2
            clips.append(img_clip.with_start(start_time).with_duration(duration)
                         .with_position((x_pos, y_pos)))
        except Exception as e:
            print(f"  [!] Card load failed: {e}")

    return clips


# ── SUBTITLES ────────────────────────────────────────────────────

def _build_subtitles(word_timestamps, intro_end: float = 0.0):
    clips  = []
    chunks = [word_timestamps[i:i + WORDS_PER_SUBTITLE]
              for i in range(0, len(word_timestamps), WORDS_PER_SUBTITLE)]

    for idx, chunk in enumerate(chunks):
        text  = " ".join(w["word"] for w in chunk)
        start = chunk[0]["start"]
        # Whisper: use next word's start as the cut point — perceptually tight.
        # For the last chunk fall back to Whisper's own end time.
        if idx + 1 < len(chunks):
            end = chunks[idx + 1][0]["start"]
        else:
            end = chunk[-1]["end"]
        duration = max(end - start, 0.05)
        wrapped  = "\n".join(textwrap.wrap(text, width=24))

        # During intro card: show subtitles below the card so title is readable
        if start < intro_end:
            position = ("center", SUB_BELOW_CARD_Y)
        else:
            position = ("center", SUB_CENTER_Y)

        try:
            txt = TextClip(
                text=text,
                font_size=SUB_FONT_SIZE,
                font=SUB_FONT_PATH,
                color=SUB_COLOR,
                stroke_color=SUB_STROKE_COLOR,
                stroke_width=SUB_STROKE_WIDTH,
                method="caption",
                size=(WIDTH - 80, 200),   # fixed height with plenty of room for stroke
                text_align="center",
            )
            x_pos = (WIDTH - txt.w) // 2
            y_pos = position[1]
            txt = (txt.with_start(start)
                      .with_duration(duration)
                      .with_position((x_pos, y_pos)))
            clips.append(txt)
        except Exception as e:
            print(f"  [!] Subtitle clip failed: {e}")

    return clips


# ── VERDICT CARD ─────────────────────────────────────────────────

def _build_verdict_card(text, duration, start):
    card_height = 280
    card_bg = (ColorClip(size=(WIDTH, card_height), color=(15, 15, 15))
               .with_opacity(0.92).with_duration(duration))

    wrapped = "\n".join(textwrap.wrap(text, width=34))
    txt = (TextClip(
        text=wrapped,
        font_size=VERDICT_FONT_SIZE,
        font=FONT_PATH,
        color="white",
        method="caption",
        size=(WIDTH - 60, None),
        text_align="center",
    ).with_duration(duration).with_position("center"))

    label = (TextClip(
        text="YOUR VERDICT?",
        font_size=26,
        font=FONT_PATH,
        color="#FF4500",
    ).with_duration(duration).with_position(("center", 18)))

    card = (CompositeVideoClip([card_bg, label, txt], size=(WIDTH, card_height))
            .with_position((0, HEIGHT - card_height))
            .with_start(start))
    return card


# ── MUSIC ────────────────────────────────────────────────────────

def _build_music_track(music_path, total_duration):
    try:
        music = AudioFileClip(music_path)
        try:
            music = music.with_volume_scaled(MUSIC_VOLUME)
        except AttributeError:
            music = music.multiply_volume(MUSIC_VOLUME)
        if music.duration < total_duration:
            loops = int(np.ceil(total_duration / music.duration))
            music = concatenate_audioclips([music] * loops)
        music = music.subclipped(0, total_duration)

        # Manually apply fade using AudioArrayClip
        # Read audio samples, apply linear fade from 100%→10% over last 7s
        try:
            FADE_DURATION = 7.0
            sr = 44100
            samples = music.to_soundarray(fps=sr)  # shape: (n_samples, n_channels)
            n_total = samples.shape[0]
            fade_samples = int(FADE_DURATION * sr)
            fade_start   = n_total - fade_samples

            # Build per-sample multiplier: 1.0 until fade_start, then 1.0→0.10
            multiplier = np.ones(n_total, dtype=np.float32)
            fade_range = np.linspace(1.0, 0.10, fade_samples, dtype=np.float32)
            multiplier[fade_start:] = fade_range

            # Apply to all channels
            if samples.ndim == 2:
                samples = samples * multiplier[:, np.newaxis]
            else:
                samples = samples * multiplier

            from moviepy import AudioArrayClip as AAC
            music = AAC(samples, fps=sr).with_duration(total_duration)
            print(f"  [Music] Fade applied: 100%→10% over last {FADE_DURATION}s")
        except Exception as e:
            print(f"  [Music] Fade failed ({e}), using audio_fadeout fallback")
            try:
                music = music.audio_fadeout(7.0)
            except Exception:
                pass

        print(f"  [Music] Track loaded at volume {MUSIC_VOLUME}: {music_path}")
        return music
    except Exception as e:
        print(f"  [!] Music load failed: {e}")
        return None


def _format_verdict(comment_bait, top_comment):
    if comment_bait and len(comment_bait) > 10:
        return comment_bait
    if top_comment:
        return top_comment[:197] + "..." if len(top_comment) > 200 else top_comment
    return "What do YOU think? Drop your verdict in the comments below"


if __name__ == "__main__":
    print("video_builder.py loaded — call build_video() to render.")
