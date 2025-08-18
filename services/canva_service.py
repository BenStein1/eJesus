import csv
import os
from datetime import datetime
from typing import Dict
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
import ffmpeg  # optional local render
from utils.logger import get_logger

load_dotenv()
logger = get_logger("canva_service")

def _brand_assets_dir() -> str:
    base = os.getenv("OUTPUT_DIR", "./output")
    assets = os.path.join(base, "assets")
    os.makedirs(assets, exist_ok=True)
    return assets

def export_bulk_create_csv(metadata: Dict[str, str]) -> str:
    """
    Creates a CSV compatible with Canva's Bulk Create feature, so you can bind
    data fields (e.g., {title}, {subtitle}, {date}) in your Canva template.
    """
    assets = _brand_assets_dir()
    csv_path = os.path.join(assets, "bulk_create_row.csv")
    fields = sorted(metadata.keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow(metadata)
    logger.info(f"Bulk Create CSV exported: {csv_path}")
    return csv_path

def render_title_card_png(title: str, subtitle: str | None = None) -> str:
    """
    Makes a simple 1920x1080 PNG title card for use in Canva or local renders.
    """
    assets = _brand_assets_dir()
    img_path = os.path.join(assets, "title_card.png")

    W, H = 1920, 1080
    bg = (18, 18, 18)  # neutral dark
    fg = (235, 235, 235)
    accent = (120, 180, 255)

    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    # Fonts: fall back to default if no system font path available
    def load_font(size):
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()

    title_font = load_font(72)
    sub_font = load_font(38)
    brand_font = load_font(28)

    # Title
    bbox = d.textbbox((0, 0), title, font=title_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    d.text(((W - tw) // 2, H // 2 - th), title, font=title_font, fill=fg)

    # Subtitle
    if subtitle:
        sb = d.textbbox((0, 0), subtitle, font=sub_font)
        sw = sb[2] - sb[0]
        d.text(((W - sw) // 2, H // 2 + 30), subtitle, font=sub_font, fill=accent)

    # Brand footer
    brand = os.getenv("BRAND_NAME", "eJesus")
    stamp = f"{brand} • {datetime.now().strftime('%Y-%m-%d')}"
    bb = d.textbbox((0, 0), stamp, font=brand_font)
    bw = bb[2] - bb[0]
    d.text((W - bw - 40, H - 80), stamp, font=brand_font, fill=(180, 180, 180))

    img.save(img_path, "PNG")
    logger.info(f"Title card image saved: {img_path}")
    return img_path

def optional_local_render_mp4(audio_mp3: str, title_png: str, out_mp4: str, target_resolution=(1920, 1080)):
    """
    OPTIONAL: Compose a simple static-video + audio MP4 locally using ffmpeg.
    This is a fallback if you want fully automated daily videos without opening Canva.
    """
    os.makedirs(os.path.dirname(out_mp4), exist_ok=True)
    width, height = target_resolution

    logger.info("Rendering local video via ffmpeg...")
    (
        ffmpeg
        .input(title_png, loop=1, framerate=1)
        .filter("scale", width, -2)
        .output(audio_mp3, out_mp4, shortest=None, vcodec="libx264", acodec="aac",
                video_bitrate="4000k", audio_bitrate="192k", pix_fmt="yuv420p", r=30, t=None)
        .overwrite_output()
        .run(quiet=True)
    )
    logger.info(f"Local render complete: {out_mp4}")
    return out_mp4

def canva_handoff_docs():
    """
    Prints short instructions for using Bulk Create with the CSV produced here.
    """
    msg = """
Canva Bulk Create handoff:

1) Open your Canva video template (ensure text fields use placeholders like {title}, {subtitle}, {date}).
2) In Canva: Apps → Bulk Create → Upload CSV → select output/assets/bulk_create_row.csv
3) Map fields (title, subtitle, date, description). Apply to design.
4) Drop in 'title_card.png' as the opening frame background if desired.
5) Add your ElevenLabs MP3 to the timeline under the canvas; extend background to audio length.
6) Export video → MP4.
"""
    logger.info(msg.strip())
