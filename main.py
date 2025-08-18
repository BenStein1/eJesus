import os
from dotenv import load_dotenv
from utils.logger import get_logger
from services.chatgpt_service import generate_sermon
from services.elevenlabs_service import synthesize_sermon
from services.render_service import render_kenburns_video, chunk_text_for_overlays, make_title_card, ensure_dirs, _safe_name
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

def list_images(img_dir: str) -> list[str]:
    if not os.path.isdir(img_dir):
        return []
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    files = [os.path.join(img_dir, f) for f in sorted(os.listdir(img_dir))]
    return [f for f in files if os.path.splitext(f)[1].lower() in exts]

def main():
    outdir = ensure_output_dir()
    seed_topic = os.getenv("EJESUS_SEED_TOPIC", "").strip() or None
    res = os.getenv("EJESUS_RESOLUTION", "1920x1080")
    intro_seconds = float(os.getenv("EJESUS_INTRO_SECONDS", "8"))
    font_path = os.getenv("EJESUS_FONT_PATH", "")

    # 1) Script
    title, body = generate_sermon(seed_topic=seed_topic)
    title_safe = _safe_name(title)
    script_txt = os.path.join(outdir, f"{title_safe}.txt")
    write_text(script_txt, body)
    logger.info(f"text → {script_txt}")

    # 2) TTS
    audio_mp3 = os.path.join(outdir, f"{title_safe}.mp3")
    synthesize_sermon(body, audio_mp3)

    # 3) Collect images and generate overlays
    img_dir = os.path.join("assets", "images")
    images = list_images(img_dir)
    overlay_lines = chunk_text_for_overlays(body, max_chars=90)

    # 4) Render full video with Ken Burns + overlays
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

    # 5) Upload (optional)
    do_upload = os.getenv("EJESUS_UPLOAD", "false").lower() in ("1","true","yes")
    if do_upload:
        tags = [t.strip() for t in os.getenv("YOUTUBE_DEFAULT_TAGS", "").split(",") if t.strip()]
        description = f"{title}\n\n{body[:800]}..."
        upload_video(video_path=video_mp4, title=title, description=description, tags=tags)

if __name__ == "__main__":
    main()
