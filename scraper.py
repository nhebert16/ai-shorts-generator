"""
scraper.py — Pulls top story posts from Reddit using the public JSON API.
No API key or PRAW required — uses Reddit's public .json endpoints directly.

Upgrades:
- Multi-time-filter fallback: day → week → month if not enough posts found
- Engagement scoring: ranks by upvote ratio × score, not just raw score
- Deduplication across time filters to avoid re-evaluating the same post
"""

import re
import time
import requests
from db import is_post_processed, mark_post_processed, is_comment_processed, mark_comment_processed

# ── Subreddits ────────────────────────────────────────────────────
TARGET_SUBREDDITS = [
    "AskReddit",
    "AmItheAsshole",
    "relationship_advice",
    "tifu",
    "confessions",
    "offmychest",
    "TrueOffMyChest",
]

# ── Tuning ────────────────────────────────────────────────────────
MIN_SCORE        = 3000    # Minimum upvotes
MIN_WORDS        = 100     # Too short = not enough content
MAX_WORDS        = 280     # ~90s @ +30% TTS speed
POSTS_PER_SUB   = 25      # How many to evaluate per subreddit per time filter
MAX_NEW_POSTS   = 3       # Max new posts to queue per run
REQUEST_DELAY   = 2       # Seconds between requests (be polite)

# Time filters tried in order — falls through to next if not enough posts found
TIME_FILTERS = ["day", "week", "month", "year"]

# AskReddit-specific thresholds
ASKREDDIT_MIN_POST_SCORE    = 5000   # Viral question bar is higher
ASKREDDIT_MIN_COMMENT_SCORE = 500   # Comment must be crowd-favourite
ASKREDDIT_MIN_WORDS         = 80     # Substantive but can be shorter than a story
ASKREDDIT_MAX_WORDS         = 250    # Keep tight for Shorts

# Engagement score weight: higher = prefer posts with better upvote ratio
# Score = raw_score * upvote_ratio^RATIO_WEIGHT
RATIO_WEIGHT = 2.0

# Keywords that trigger automatic post rejection (title + body checked)
BLOCKED_KEYWORDS = [
    # US Politics — parties, figures, institutions
    "trump", "biden", "harris", "maga", "democrat", "republican",
    "congress", "senate", "election", "political", "gop", "dnc",
    "pelosi", "obama", "desantis", "aoc", "bernie", "liberal", "conservative",
    "white house", "capitol", "inauguration", "ballot", "impeach",
    # International politics
    "israel", "palestine", "hamas", "gaza", "west bank",
    "russia", "ukraine", "putin", "zelensky", "nato", "kremlin",
    "china", "xi jinping", "taiwan", "hong kong",
    "iran", "north korea", "sanctions",
    # Healthcare / policy debates
    "healthcare", "health care", "obamacare", "medicaid", "medicare",
    "abortion", "abortions", "pro-life", "pro-choice", "roe v wade",
    "planned parenthood", "reproductive rights", "fetal", "fetus",
    "gun control", "gun rights", "second amendment", "nra", "mass shooting",
    "immigration", "border wall", "deportation", "asylum", "migrant", "refugee",
    # Government / leadership titles (catch political figures generically)
    "president", "vice president", "governor", "congressman", "congresswoman",
    "senator", "secretary of state", "prime minister", "chancellor",
    "administration", "executive order", "supreme court", "legislation", "bill passed",
    "protest", "rally", "activist", "lobbying",
    # Demonetization risks
    "suicide", "self-harm", "self harm", "rape", "assault",
    "cocaine", "heroin",
    # Hate / extreme content
    "nazi", "hitler", "terrorism", "terrorist", "genocide",
    # Low-performing niches
    "cryptocurrency", "crypto", "nft",
]

HEADERS = {"User-Agent": "RedditVideoBot/1.0 (personal project, read-only)"}


# ── Fetching ──────────────────────────────────────────────────────

def fetch_top_posts(subreddit: str, time_filter: str) -> list[dict]:
    """Fetch raw post data from Reddit's public JSON endpoint."""
    url    = f"https://www.reddit.com/r/{subreddit}/top.json"
    params = {"t": time_filter, "limit": POSTS_PER_SUB}
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return [child["data"] for child in data["data"]["children"]]
    except Exception as e:
        print(f"  [!] Failed to fetch r/{subreddit} ({time_filter}): {e}")
        return []


def fetch_top_comment(subreddit: str, post_id: str,
                       min_words: int = 50, max_words: int = 280,
                       min_score: int = 0,
                       skip_ids: set = None) -> dict | None:
    """
    Fetch the highest-scored suitable comment for a post.
    Returns {id, body, score} or None.
    skip_ids: set of comment IDs to skip (already processed).
    """
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data     = resp.json()
        comments = data[1]["data"]["children"]
        for child in comments:
            c      = child.get("data", {})
            body   = c.get("body", "")
            cid    = c.get("id", "")
            cscore = c.get("score", 0)
            wc     = count_words(strip_markdown(body))
            if skip_ids and cid in skip_ids:
                continue
            if (not c.get("distinguished")
                    and body not in ("[deleted]", "[removed]")
                    and cscore >= min_score
                    and min_words <= wc <= max_words):
                return {"id": cid, "body": body.strip(), "score": cscore}
    except Exception:
        pass
    return None


# ── Filtering & scoring ───────────────────────────────────────────

def strip_markdown(text: str) -> str:
    text = re.sub(r"\*\*?(.*?)\*\*?", r"\1", text)
    text = re.sub(r"~~(.*?)~~",        r"\1", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+",  "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s+",       "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n",   text)
    return text.strip()


def contains_blocked_keywords(text: str) -> str | None:
    """Returns the matched keyword if blocked, else None."""
    lowered = text.lower()
    for kw in BLOCKED_KEYWORDS:
        if re.search(r'' + re.escape(kw) + r'', lowered):
            return kw
    return None


def count_words(text: str) -> int:
    return len(text.split())


def engagement_score(post: dict) -> float:
    """
    Composite score that rewards both popularity and engagement quality.
    upvote_ratio is 0.0–1.0 (Reddit's own metric).
    A post with 5k upvotes and 0.97 ratio beats one with 8k and 0.72.
    """
    raw_score    = post.get("score", 0)
    upvote_ratio = post.get("upvote_ratio", 0.5)
    return raw_score * (upvote_ratio ** RATIO_WEIGHT)


def is_suitable(post: dict, subreddit: str = "") -> tuple[bool, str]:
    """Returns (is_suitable, reason_if_not)."""
    if post.get("over_18"):
        return False, "NSFW"

    # Check title for blocked keywords
    title_check = contains_blocked_keywords(post.get("title", ""))
    if title_check:
        return False, f"blocked keyword in title: '{title_check}'"

    if subreddit.lower() == "askreddit":
        # AskReddit: only need a high-scoring question, body checked at comment level
        if not post.get("is_self"):
            return False, "not a text post"
        if post.get("score", 0) < ASKREDDIT_MIN_POST_SCORE:
            return False, f"score too low ({post.get('score')})"
        return True, ""

    # Standard subreddits
    if not post.get("is_self"):
        return False, "not a text post"
    if post.get("score", 0) < MIN_SCORE:
        return False, f"score too low ({post.get('score')})"

    body = post.get("selftext", "")
    if not body or body in ("[deleted]", "[removed]"):
        return False, "deleted or empty"

    body_check = contains_blocked_keywords(body)
    if body_check:
        return False, f"blocked keyword in body: '{body_check}'"

    word_count = count_words(strip_markdown(body))
    if word_count < MIN_WORDS:
        return False, f"too short ({word_count} words)"
    if word_count > MAX_WORDS:
        return False, f"too long ({word_count} words)"

    return True, ""


# ── Main ──────────────────────────────────────────────────────────

def scrape_posts() -> list[dict]:
    """
    Main entry point. Returns a list of post dicts ready for processing.

    For each subreddit, tries TIME_FILTERS in order (day → week → month)
    until enough suitable posts are found. Posts are ranked by engagement
    score before being queued.
    """
    queued       = []
    seen_ids     = set()   # dedup across time filters within a run

    for sub_name in TARGET_SUBREDDITS:
        if len(queued) >= MAX_NEW_POSTS:
            break

        print(f"\n[Scraper] Checking r/{sub_name}...")

        # Collect candidates across all time filters
        candidates = []

        for time_filter in TIME_FILTERS:
            print(f"  [→] Fetching top posts ({time_filter})...")
            posts = fetch_top_posts(sub_name, time_filter)
            time.sleep(REQUEST_DELAY)

            new_this_filter = 0
            for post in posts:
                post_id = post.get("id")
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                if is_post_processed(post_id):
                    continue

                suitable, reason = is_suitable(post, subreddit=sub_name)
                if not suitable:
                    continue

                candidates.append(post)
                new_this_filter += 1

            print(f"  [→] {new_this_filter} new candidates from '{time_filter}'")

            # If we have enough candidates, no need to go further back in time
            if len(candidates) >= MAX_NEW_POSTS * 2:
                break

        if not candidates:
            print(f"  [→] No suitable posts found in r/{sub_name}")
            continue

        # Sort candidates by engagement score — best first
        candidates.sort(key=engagement_score, reverse=True)
        print(f"  [→] {len(candidates)} total candidates, sorted by engagement")

        # Queue the top ones
        for post in candidates:
            if len(queued) >= MAX_NEW_POSTS:
                break

            post_id   = post.get("id")
            eng_score = engagement_score(post)

            if sub_name.lower() == "askreddit":
                # Fetch top comment meeting AskReddit criteria
                comment = fetch_top_comment(
                    sub_name, post_id,
                    min_words=ASKREDDIT_MIN_WORDS,
                    max_words=ASKREDDIT_MAX_WORDS,
                    min_score=ASKREDDIT_MIN_COMMENT_SCORE,
                )
                if not comment:
                    print(f"  [→] No suitable comment for: {post['title'][:50]}")
                    continue
                blocked = contains_blocked_keywords(comment["body"])
                if blocked:
                    print(f"  [→] Comment blocked ('{blocked}'): {post['title'][:50]}")
                    continue
                if is_comment_processed(comment["id"]):
                    print(f"  [→] Comment already processed, skipping")
                    continue
                time.sleep(REQUEST_DELAY)

                clean_body = strip_markdown(comment["body"])
                word_count = count_words(clean_body)
                dedup_id   = comment["id"]

                post_data = {
                    "reddit_post_id":   dedup_id,
                    "subreddit":        sub_name,
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
                mark_comment_processed(dedup_id, sub_name, post["title"],
                                       post["score"], word_count)
                print(f"  [✓] Queued: \"{post['title'][:60]}\"")
                print(f"       comment {word_count}w score {comment['score']} | "
                      f"post {post['score']} upvotes | engagement: {round(eng_score):,}")
            else:
                clean_body = strip_markdown(post["selftext"])
                word_count = count_words(clean_body)

                post_data = {
                    "reddit_post_id":   post_id,
                    "subreddit":        sub_name,
                    "title":            post["title"],
                    "body":             clean_body,
                    "score":            post["score"],
                    "upvote_ratio":     post.get("upvote_ratio", 0),
                    "engagement_score": round(eng_score),
                    "word_count":       word_count,
                    "top_comment":      None,
                    "url":              f"https://reddit.com{post['permalink']}",
                    "format":           "standard",
                }
                mark_post_processed(post_id, sub_name, post["title"],
                                    post["score"], word_count)
                print(f"  [✓] Queued: \"{post['title'][:60]}\"")
                print(f"       {word_count} words | {post['score']} upvotes | "
                      f"{post.get('upvote_ratio',0):.0%} ratio | "
                      f"engagement: {round(eng_score):,}")

            queued.append(post_data)

        time.sleep(REQUEST_DELAY)

    print(f"\n[Scraper] Done. {len(queued)} new posts queued.")
    return queued


if __name__ == "__main__":
    from db import init_db
    init_db()
    posts = scrape_posts()
    for p in posts:
        print(f"\n--- {p['title']} ---")
        print(f"Score: {p['score']} | Ratio: {p['upvote_ratio']:.0%} | "
              f"Engagement: {p['engagement_score']:,}")
        print(p["body"][:300])
