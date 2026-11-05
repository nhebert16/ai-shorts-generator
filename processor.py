"""
processor.py — Process Reddit posts with Claude to create scripts

Uses Claude Haiku to rewrite posts into engaging short-form scripts for TikTok/YouTube Shorts.
Key change: Script now leads with the post TITLE before diving into the body.
"""

import os
import json
from dotenv import load_dotenv
from anthropic import Anthropic
from llm import ask, HAIKU

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY not set in .env")

client = Anthropic()

def strip_emojis(text: str) -> str:
    """Remove unicode emojis and text emoticons from script."""
    import re
    # Remove all unicode emoji / symbol blocks
    text = re.sub(u'[\U00010000-\U0010ffff]', '', text)
    text = re.sub(u'[\U0001F000-\U0001FFFF]', '', text)
    text = re.sub(u'[\u2600-\u27BF]', '', text)
    # Remove text emoticons like :) :( ;) :D :/ :-) etc.
    text = re.sub(r'\s*[:;=8]-?[)(DdPpOoXx/\\|]+', '', text)
    text = re.sub(r'\s*[)(DdPpOoXx/\\|]+-?[:;=8]', '', text)
    # Clean up extra spaces
    text = re.sub(r'  +', ' ', text)
    return text.strip()

# AskReddit system prompt — question + top answer format
ASKREDDIT_SYSTEM_PROMPT = """You are a Reddit narrator reading AskReddit posts for short-form videos.

Your job is to:
1. Read the question (post title) naturally
2. Read the top comment word-for-word (do not summarize or rewrite)

Format your response as JSON with these fields:
{
  "hook": "",
  "title": "The original question",
  "body": "The EXACT comment body - read verbatim",
  "script": "Question + EXACT comment — NO hook, no intro, no transition phrase, no CTA",
  "tags": ["tag1", "tag2"]
}

Rules:
- DO NOT summarize or rewrite the comment
- DO NOT add any transition phrase between the question and the answer
- START with the question title
- READ THE COMMENT WORD FOR WORD immediately after the title
- DO NOT add any call-to-action or outro
"""

# System prompt that reads Reddit posts VERBATIM
SYSTEM_PROMPT = """You are a Reddit story narrator who reads Reddit posts verbatim for short-form videos.

Your job is to:
1. Read the post title naturally
2. Read the post body word-for-word (do not summarize or rewrite)

Format your response as JSON with these fields:
{
  "hook": "",
  "title": "The original post title",
  "body": "The EXACT post body - read verbatim, do not summarize",
  "script": "Title + Body — NO hook, no intro, no CTA, start directly with the title",
  "tags": ["tag1", "tag2"]
}

Rules:
- DO NOT add any intro hook or attention-grabbing opener
- DO NOT SUMMARIZE the post body
- DO NOT REWRITE the post
- DO NOT add any call-to-action or outro at the end
- START the script directly with the post title
- READ THE POST BODY WORD FOR WORD after the title
- Aim for 200-280 words total (title + body) but do NOT cut off the post — always finish the full story
- Example: "[Original Title]. [Exact post body]."
"""

def process_batch(posts: list[dict]) -> list[dict]:
    """Process a batch of Reddit posts through Claude."""
    results = []
    
    for i, post in enumerate(posts, 1):
        print(f"\n  [{i}/{len(posts)}] Processing: {post.get('title', 'Unknown')[:60]}...")
        
        # Handle missing selftext field - try multiple field names
        post_body = post.get('selftext') or post.get('body') or post.get('text') or ''

        is_askreddit   = post.get('format') == 'askreddit'
        active_system  = ASKREDDIT_SYSTEM_PROMPT if is_askreddit else SYSTEM_PROMPT

        if is_askreddit:
            user_prompt = f"""Process this AskReddit post into a short-form video script.

SUBREDDIT: {post.get('subreddit', 'unknown')}
QUESTION (title): {post.get('title', 'No title')}
TOP COMMENT (body): {post_body[:6000]}
POST SCORE: {post.get('score', 0)}

IMPORTANT: Script must be: [Question title]. [Exact comment word-for-word]. No hook. No transition phrase. No CTA."""
        else:
            user_prompt = f"""Process this Reddit post into a short-form video script.

SUBREDDIT: {post.get('subreddit', 'unknown')}
TITLE: {post.get('title', 'No title')}
BODY: {post_body[:6000]}
SCORE: {post.get('score', 0)}
COMMENTS: {post.get('num_comments', 0)}

IMPORTANT: The "script" field must start with the title, then contain the EXACT post body text above word-for-word. No hook. No intro. No CTA. Start directly with the title."""
        
        try:
            response_text = ask(client, HAIKU, user_prompt, max_tokens=4000, system=active_system)
            
            # Try to extract JSON
            try:
                # Look for JSON in the response
                start = response_text.find('{')
                end = response_text.rfind('}') + 1
                if start != -1 and end > start:
                    json_str = response_text[start:end]
                    result = json.loads(json_str)
                else:
                    raise ValueError("No JSON found in response")
            except (json.JSONDecodeError, ValueError):
                # Fallback if Claude didn't return valid JSON
                print(f"    [!] JSON parse failed, using text as-is")
                result = {
                    "hook": post.get('title', '')[:100],
                    "title": post.get('title', ''),
                    "body": post_body[:300],
                    "script": post_body[:500],
                    "tags": ["reddit"]
                }
            
            # Validate required fields
            result.setdefault("hook", post.get('title', '')[:100])
            result.setdefault("title", post.get('title', ''))
            result.setdefault("body", post_body[:300])
            result.setdefault("script", post_body[:500])
            result.setdefault("tags", [])
            
            # Word count validation
            script_words = len(result["script"].split())
            if script_words > 300:
                print(f"    [!] Script is {script_words} words (target: 200-280) — may be too long")
            elif script_words < 150:
                print(f"    [!] Script is {script_words} words (target: 200-280) — may be too short")
            else:
                print(f"    [✓] Script: {script_words} words")
            
            # Build final result
            final_result = {
                "hook": result.get("hook", ""),
                "title": result.get("title", post.get('title', '')),
                "script": result.get("script", ""),
                "body": result.get("body", ""),
                "conclusion": result.get("conclusion", "Drop your verdict in the comments below"),
                "tags": result.get("tags", []),
                "subreddit": post.get('subreddit', ''),
                "reddit_post_id": post.get('reddit_post_id', ''),
                "score": post.get('score', 0),
                "num_comments": post.get('num_comments', 0),
                "url": post.get('url', ''),
            }
            
            # Strip emojis and emoticons from script before TTS
            final_result["script"] = strip_emojis(final_result["script"])
            final_result["hook"]   = strip_emojis(final_result["hook"])

            results.append(final_result)
            print(f"    [✓] Processed: hook ({len(final_result['hook'])} chars)")
            
        except Exception as e:
            print(f"    [!] Failed: {e}")
            continue
    
    return results


if __name__ == "__main__":
    # Test with a sample post
    test_post = {
        "subreddit": "r/AITA",
        "title": "AITA for not wanting to go to my brother's wedding?",
        "selftext": "My brother is getting married next month. I've never been close with him and don't really want to attend. He says I have to because we're family. I hate weddings and would much rather stay home.",
        "reddit_post_id": "abc123",
        "score": 1000,
        "num_comments": 250,
        "url": "https://reddit.com/r/AITA/abc123",
    }
    
    results = process_batch([test_post])
    for r in results:
        print(f"\nHook: {r['hook']}")
        print(f"Title: {r['title']}")
        print(f"Script:\n{r['script']}")
