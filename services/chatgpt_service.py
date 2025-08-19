import os
from typing import Tuple, Optional
from dotenv import load_dotenv
from openai import OpenAI
from utils.logger import get_logger

load_dotenv()
logger = get_logger("chatgpt_service")

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

def _length_prompt(target_words: Optional[int]) -> str:
    if not target_words:
        return ""
    tw = max(80, int(target_words))  # sanity floor
    return f"\nAim for about {tw} words (±10%). Keep it concise for testing.\n"

def generate_sermon(seed_topic: Optional[str] = None,
                    target_words: Optional[int] = None) -> Tuple[str, str]:
    """
    Returns (title, body). Reads templates/sermon_prompt.txt as base instruction,
    optionally nudged by `seed_topic`. `target_words` lets you make short test sermons.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt_path = os.path.join("templates", "sermon_prompt.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    user_nudge = ""
    if seed_topic:
        user_nudge = f"Today's seed topic is: {seed_topic}\nPlease weave it in naturally.\n"
    user_nudge += _length_prompt(target_words)

    logger.info("Requesting sermon from OpenAI...")
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_nudge or "Please write today's sermon."}
        ],
        temperature=0.8,
    )

    text = resp.choices[0].message.content.strip()
    title = "Daily Sermon"
    if text.startswith("Title:"):
        parts = text.split("\n", 1)
        if len(parts) == 2:
            first_line, rest = parts
            title = first_line.replace("Title:", "").strip()
            body = rest.strip()
        else:
            body = text
    else:
        body = text

    logger.info("Sermon generated.")
    return title, body
