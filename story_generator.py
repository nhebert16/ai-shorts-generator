"""
story_generator.py — Generates original Reddit-style short stories for Shorts.

Short-form sibling of Long Videos/story_generator.py. Uses Claude Sonnet.
Stories are modelled on viral Reddit posts with:
- Specific ages/genders in (29F) format
- A hook in the first sentence and one clear twist
- An open ending that invites comments
- 200-280 words total (~90 seconds of narration)
"""

import json
import random
from anthropic import Anthropic
from dotenv import load_dotenv
from llm import ask, SONNET

load_dotenv()
client = Anthropic()

SYSTEM_PROMPT = """You are a creative writer who specialises in original Reddit-style stories for YouTube Shorts narration.

Write stories that feel authentic to Reddit — specific, grounded, emotionally real. The narrator should sound like a real person posting, not a storyteller.

Story criteria:
- First sentence is the hook: drop the listener straight into the conflict
- Build quickly to ONE clear twist or confrontation; no long backstory
- Ending: open and slightly uncomfortable, so viewers want to weigh in. No moral lessons.
- Age/gender tags: include (29F), (31M) etc. for named people on first mention
- Length: 200-250 words for the body — this is non-negotiable, the Short must stay under 90 seconds
- Names: common American names (e.g. Ashley, Tyler, Brittany, Derek, Kayla, Jason, Megan, Brandon)
- No emojis. No lists. No politics, no self-harm, no sexual content, no drugs.
- Match the voice of the given subreddit (AITA posts ask for judgment, TIFU posts are self-deprecating, confessions are guilty and quiet)

Format your response as JSON:
{
  "title": "Post title in the subreddit's style",  (MUST be under 100 characters — YouTube title limit)
  "body": "Full story text. Use \\n\\n between paragraphs.",
  "tags": ["aita", "redditstories"]
}"""

# Theme seeds — each maps to the most fitting subreddit
THEMES = [
    ("refused to give up my seat at a family dinner for my sister's new boyfriend",          "AmItheAsshole"),
    ("told my best friend the truth about her fiance at the bachelorette party",             "AmItheAsshole"),
    ("charged my brother rent after he moved in for 'two weeks' eight months ago",           "AITAH"),
    ("skipped my coworker's baby shower after she took credit for my project",               "AITAH"),
    ("found out my boyfriend has been using my Netflix to message his ex",                   "relationship_advice"),
    ("partner secretly planned a move across the country without asking me",                 "relationship_advice"),
    ("accidentally sent a rant about my boss to my boss",                                    "tifu"),
    ("mixed up two gifts at Christmas and exposed a family secret",                          "tifu"),
    ("pretended to be sick to skip a wedding and got caught by the bride",                   "tifu"),
    ("I've been secretly paying my neighbor's electricity bill for a year",                  "confessions"),
    ("I let my parents believe my sister broke the heirloom I actually broke",               "confessions"),
    ("my mother-in-law reorganized my entire kitchen while we were on vacation",             "TrueOffMyChest"),
    ("my dad forgot my wedding date but remembered his golf tournament",                     "TrueOffMyChest"),
    ("I finally stopped covering for my sister and the whole family found out why",          "offmychest"),
    ("my friend group planned a trip in a separate chat and only invited me to pay",         "offmychest"),
    ("uninvited my cousin from my wedding after she tried to propose at it",                 "AmItheAsshole"),
]


def generate_story() -> dict | None:
    """
    Generate an original Reddit-style short story using Claude Sonnet.
    Returns a post dict compatible with processor.process_batch().
    """
    theme, subreddit = random.choice(THEMES)
    print(f"  [StoryGen] Generating story — theme: {theme} | subreddit: r/{subreddit}")

    try:
        text = ask(
            client, SONNET,
            f"Write an r/{subreddit} post on this theme: {theme}. Make it feel completely original and specific.",
            max_tokens=1200,
            system=SYSTEM_PROMPT,
        )
        start = text.find('{')
        end   = text.rfind('}') + 1
        if start == -1 or end <= start:
            print("  [!] StoryGen: no JSON in response")
            return None

        data = json.loads(text[start:end], strict=False)   # tolerate raw newlines inside strings
        title = data.get("title", "").strip()
        body  = data.get("body", "").strip()

        if not title or not body:
            print("  [!] StoryGen: empty title or body")
            return None

        # Enforce YouTube 100 character title limit
        if len(title) > 100:
            title = title[:100].rsplit(' ', 1)[0].rstrip('.,')

        word_count = len(body.split())
        print(f"  [StoryGen] Generated: {word_count} words — \"{title[:70]}\"")

        return {
            "reddit_post_id":   f"generated_{random.getrandbits(24):06x}",
            "subreddit":        subreddit,
            "title":            title,
            "body":             body,
            "selftext":         body,
            "score":            0,
            "num_comments":     0,
            "word_count":       word_count,
            "top_comment":      None,
            "url":              "",
            "format":           "generated",
            "tags":             data.get("tags", ["aita", "redditstories"]),
        }

    except Exception as e:
        print(f"  [!] StoryGen failed: {e}")
        return None
