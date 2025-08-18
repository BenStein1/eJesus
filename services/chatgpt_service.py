import os
from typing import Tuple
from dotenv import load_dotenv
from openai import OpenAI
from utils.logger import get_logger

load_dotenv()
logger = get_logger("chatgpt_service")

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

def generate_sermon(seed_topic: str | None = None) -> Tuple[str, str]:
    """
    Returns (title, body). Reads templates/sermon_prompt.txt as base instruction,
    optionally nudged by `seed_topic`.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt_path = os.path.join("templates", "sermon_prompt.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    user_nudge = ""
    if seed_topic:
        user_nudge = f"Today's seed topic is: {seed_topic}\nPlease weave it in naturally.\n"

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
        first_line, rest = text.split("\n", 1)
        title = first_line.replace("Title:", "").strip()
        body = rest.strip()
    else:
        body = text

    logger.info("Sermon generated.")
    return title, body
