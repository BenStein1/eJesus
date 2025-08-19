import os
from typing import List, Optional
from dotenv import load_dotenv
from utils.logger import get_logger
from services.chatgpt_service import generate_sermon
from services.elevenlabs_service import synthesize_sermon
from services.render_service import (
    render_kenburns_video,
    chunk_text_for_overlays,
    make_title_card,
    ensure_dirs,
    _safe_name,
)
from services.youtube_service import upload_video

load_dotenv()
logger = get_logger("eJesus-main")

def ensure_output_dir() -> str:
    outdir = os.getenv("OUTPUT_DIR", "./output")
    ensure_dirs(outdir)
    return outdir

def write_text(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def list_images_recursive(root_dir: str) -> List[str]:
    """
    Walk assets/images recursively and return a sorted list of supported images.
    """
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    paths: List[str] = []
    if not os.path.isdir(root_dir):
        return paths
    for base, _dirs, files in os.walk(root_dir):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in exts:
                paths.append(os.path.join(base, name))
    paths.sort()
    return paths

def _env_int(name: str, default: Optional[int]) -> Optional[int]:
    val = os.getenv(name, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default

def _bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")

def main():
    outdir = ensure_output_dir()
    seed_topic = os.getenv("EJESUS_SEED_TOPIC", "").strip() or None
    res = os.getenv("EJESUS_RESOLUTION", "1920x1080")
    intro_seconds = float(os.getenv("EJESUS_INTRO_SECONDS", "8"))
    font_path = os.getenv("EJESUS_FONT_PATH", "")
    target_words = _env_int("EJESUS_SERMON_WORDS", None)  # e.g., 150–250 for cheap tests
    offline = _bool("EJESUS_OFFLINE", False)

    if offline:
        # ---- OFFLINE: read existing text + mp3, skip APIs ----
        base = os.getenv("EJESUS_TEST_BASENAME", "Embracing the Present Moment").strip()
        test_text = os.getenv("EJESUS_TEST_TEXT", os.path.join(outdir, f"{base}.txt"))
        test_mp3 = os.getenv("EJESUS_TEST_MP3", os.path.join(outdir, f"{base}.mp3"))

        if not os.path.isfile(test_text):
            raise FileNotFoundError(f"Offline text not found: {test_text}")
        if not os.path.isfile(test_mp3):
            raise FileNotFoundError(f"Offline audio not found: {test_mp3}")

        title = base
        with open(test_text, "r", encoding="utf-8") as f:
            body = f.read()

        audio_mp3 = test_mp3
        logger.info(f"OFFLINE mode → using text: {test_text}")
        logger.info(f"OFFLINE mode → using audio: {test_mp3}")

        # Also save/normalize a copy of the text under output/<Title>.txt for consistency
        title_safe = _safe_name(title)
        script_txt = os.path.join(outdir, f"{title_safe}.txt")
        if os.path.abspath(script_txt) != os.path.abspath(test_text):
            write_text(script_txt, body)
            logger.info(f"text → {script_txt}")
    else:
        # ---- ONLINE: generate via OpenAI + ElevenLabs ----
        title, body = generate_sermon(seed_topic=seed_topic, target_words=target_words)
        title_safe = _safe_name(title)
        script_txt = os.path.join(outdir, f"{title_safe}.txt")
        write_text(script_txt, body)
        logger.info(f"text → {script_txt}")

        audio_mp3 = os.path.join(outdir, f"{title_safe}.mp3")
        synthesize_sermon(body, audio_mp3)

    # 3) Images + overlays
    img_dir = os.path.join("assets", "images")
    images = list_images_recursive(img_dir)
    if not images:
        logger.info("No images found in assets/images; the title card will be reused as the single slide.")
    overlay_lines = chunk_text_for_overlays(body, max_chars=90)

    # 4) Render
    # derive a safe title if we’re in offline mode
    if offline:
        title_safe = _safe_name(title)
    video_mp4 = os.path.join(outdir, f"{title_safe}.mp4")
    render_kenburns_video(
        images=images,
        audio_mp3=audio_mp3,
        out_mp4=video_mp4,
        title_text=title,
        overlay_lines=overlay_lines,
        resolution=res,
        intro_seconds=intro_seconds,
        font_path=font_path if font_path else None
    )

    # 5) Upload (optional; usually off in offline mode)
    do_upload = _bool("EJESUS_UPLOAD", False)
    if do_upload:
        tags = [t.strip() for t in os.getenv("YOUTUBE_DEFAULT_TAGS", "").split(",") if t.strip()]
        description = f"{title}\n\n{body[:800]}..."
        upload_video(video_path=video_mp4, title=title, description=description, tags=tags)

if __name__ == "__main__":
    main()
