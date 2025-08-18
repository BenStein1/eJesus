import os
import re
from typing import List, Tuple
from dotenv import load_dotenv
from pydub import AudioSegment
import ffmpeg
from PIL import Image, ImageDraw, ImageFont
from utils.logger import get_logger

load_dotenv()
logger = get_logger("render_service")

def _parse_resolution(res_str: str) -> Tuple[int, int]:
    m = re.match(r"^(\d+)x(\d+)$", res_str.strip())
    if not m:
        return (1920, 1080)
    return (int(m.group(1)), int(m.group(2)))

def _safe_name(s: str) -> str:
    return "".join(c for c in s if c.isalnum() or c in (" ", "_", "-")).rstrip()

def ensure_dirs(outdir: str):
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(os.path.join(outdir, "cache"), exist_ok=True)

def make_title_card(title: str, subtitle: str, out_png: str, resolution: str, font_path: str | None):
    W, H = _parse_resolution(resolution)
    bg = (18, 18, 18)
    fg = (235, 235, 235)
    accent = (120, 180, 255)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    def load_font(size):
        try:
            if font_path and os.path.exists(font_path):
                return ImageFont.truetype(font_path, size)
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()

    title_font = load_font(72)
    sub_font = load_font(40)
    brand_font = load_font(28)

    # Centered title
    tb = d.textbbox((0, 0), title, font=title_font)
    tw = tb[2] - tb[0]; th = tb[3] - tb[1]
    d.text(((W - tw) // 2, H // 2 - th), title, font=title_font, fill=fg)

    # Subtitle under
    sb = d.textbbox((0, 0), subtitle, font=sub_font)
    sw = sb[2] - sb[0]
    d.text(((W - sw) // 2, H // 2 + 30), subtitle, font=sub_font, fill=accent)

    # Brand footer
    brand = os.getenv("BRAND_NAME", "eJesus")
    bb = d.textbbox((0,0), brand, font=brand_font)
    bw = bb[2]-bb[0]
    d.text((W - bw - 40, H - 60), brand, font=brand_font, fill=(180, 180, 180))

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    img.save(out_png, "PNG")
    logger.info(f"title card → {out_png}")
    return out_png

def chunk_text_for_overlays(body: str, max_chars=90) -> List[str]:
    """
    Create short overlay lines from the sermon body: pick first sentence of each
    paragraph; fallback to chunks of ~max_chars.
    """
    paras = [p.strip() for p in body.split("\n") if p.strip()]
    chosen = []
    for p in paras:
        # first sentence-ish
        m = re.split(r'(?<=[.!?])\s+', p)
        if m and m[0]:
            chosen.append(m[0].strip())
    if not chosen:
        body_clean = re.sub(r"\s+", " ", body).strip()
        for i in range(0, len(body_clean), max_chars):
            chosen.append(body_clean[i:i+max_chars].strip())
    # Limit to something reasonable; renderer uses min(len(images), len(lines))
    return chosen[:50]

def _build_zoompan_filter(idx: int, frames: int, out_w: int, out_h: int, direction: int) -> str:
    """
    Create a gentle Ken Burns zoompan expression; direction flips per slide to add variety.
    """
    # zoom from 1.0 to ~1.12 over duration; pan horizontally a bit.
    zoom_expr = "min(zoom+0.0004,1.12)"
    # horizontal shift right or left over time; keep within bounds by referencing iw, ih
    move = "on" if direction >= 0 else "op"
    if direction >= 0:
        x_expr = f"(iw-ow)*((in/{frames}))"
    else:
        x_expr = f"(iw-ow)*(1-(in/{frames}))"
    y_expr = f"(ih-oh)/2"
    return f"[v{idx}:v]zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={out_w}x{out_h}[z{idx}]"

def _drawtext_filter(label: str, font: str | None, out_w: int, out_h: int) -> str:
    label = label.replace(":", r"\:").replace("'", r"\'")
    font_opt = f":fontfile={font}" if font and os.path.exists(font) else ""
    # Semi-opaque box behind text for readability
    return (
        f"drawtext=text='{label}'{font_opt}:fontsize=40:"
        f"fontcolor=white:box=1:boxcolor=black@0.4:boxborderw=20:"
        f"x=(w-text_w)/2:y=h- text_h - 120"
    )

def render_kenburns_video(
    images: List[str],
    audio_mp3: str,
    out_mp4: str,
    title_text: str,
    overlay_lines: List[str],
    resolution: str = "1920x1080",
    intro_seconds: float = 8.0,
    font_path: str | None = None
) -> str:
    """
    Build a full video:
      - intro: title card with slow push
      - slides: each image with gentle zoom/pan
      - floating overlay text line per slide (short quote/line)
      - synchronized to the narration length (last slide extends if needed)
    """
    out_w, out_h = _parse_resolution(resolution)
    audio = AudioSegment.from_file(audio_mp3)
    total_ms = len(audio)
    total_sec = total_ms / 1000.0
    if total_sec < intro_seconds + 5:
        intro_seconds = max(3.0, total_sec * 0.25)  # keep something for intro

    # inputs
    inputs = []
    streams = []
    filter_parts = []

    # 0: audio
    a_in = ffmpeg.input(audio_mp3)
    inputs.append(a_in)

    # Create a generated title card PNG (so we can animate it too)
    cache_dir = os.path.join(os.path.dirname(out_mp4), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    title_png = os.path.join(cache_dir, "title_card.png")
    make_title_card(title_text, os.getenv("BRAND_NAME", "eJesus"), title_png, resolution, font_path)

    # intro clip
    intro_frames = int(intro_seconds * 30)
    v0 = ffmpeg.input(title_png, loop=1, framerate=30)
    inputs.append(v0)
    filter_parts.append(f"[1:v]scale={out_w}:{out_h},setsar=1[v0]")
    filter_parts.append(_build_zoompan_filter(0, intro_frames, out_w, out_h, direction=1))
    # Add title drawtext on intro
    intro_text = _drawtext_filter(title_text, font_path, out_w, out_h)
    filter_parts.append(f"[z0]{intro_text},format=yuv420p[clip0]")

    # slides
    if not images:
        images = [title_png]  # fallback

    # compute per-slide duration to fill remaining time
    remaining = max(1.0, total_sec - intro_seconds)
    n = len(images)
    per_slide = max(6.0, remaining / n)  # at least 6s each
    # If last slide needs to soak the tail, we’ll let concat handle slightly different durations.

    vid_labels = ["[clip0]"]
    in_idx = 2  # 0 is audio, 1 is intro image; subsequent inputs start at 2

    for idx, img in enumerate(images, start=1):
        frames = int(per_slide * 30)
        vin = ffmpeg.input(img, loop=1, framerate=30)
        inputs.append(vin)
        filter_parts.append(f"[{in_idx}:v]scale={out_w}:{out_h},setsar=1[v{idx}]")
        direction = 1 if idx % 2 == 0 else -1
        filter_parts.append(_build_zoompan_filter(idx, frames, out_w, out_h, direction))

        # overlay text for this slide if available
        label = overlay_lines[idx - 1] if idx - 1 < len(overlay_lines) else ""
        if label:
            dt = _drawtext_filter(label, font_path, out_w, out_h)
            filter_parts.append(f"[z{idx}]{dt},format=yuv420p[clip{idx}]")
        else:
            filter_parts.append(f"[z{idx}]format=yuv420p[clip{idx}]")

        vid_labels.append(f"[clip{idx}]")
        in_idx += 1

    # concat all video clips
    concat_n = len(vid_labels)
    concat_inputs = "".join(vid_labels)
    filter_parts.append(f"{concat_inputs}concat=n={concat_n}:v=1:a=0[vout]")

    logger.info("building ffmpeg graph…")
    graph = ffmpeg.filter_([], 'anull')  # dummy to hold place; we use filter_complex via string
    # Build the complex filter string manually
    complex_filter = ";".join(filter_parts)

    out = (
        ffmpeg
        .concat(*inputs, v=1, a=1)  # placeholder to satisfy API; replaced by complex filter below
    )

    # We actually need to craft the output with filter_complex; ffmpeg-python lets us pass it at output.
    stream = ffmpeg.output(
        *inputs,
        out_mp4,
        vf=complex_filter + ";[vout]null",
        # map the filtered video
        **{
            "map": "[vout]",
            # map audio 0
            "map:a": "0:a",
            "c:v": "libx264",
            "preset": "veryfast",
            "r": 30,
            "b:v": "4500k",
            "pix_fmt": "yuv420p",
            "c:a": "aac",
            "b:a": "192k",
            "shortest": None,  # let video extend; audio sets total length
        }
    ).overwrite_output()

    # NOTE: We can’t pass vf with filter_complex like this unless we use `filter_complex` kw.
    # ffmpeg-python doesn’t expose `filter_complex` as a direct kw on output, so we use `global_args`.
    # Solve by generating a raw ffmpeg command via `compile()`, then inject `-filter_complex`.
    compiled = stream.compile()
    # inject filter_complex right before "-map"
    try:
        map_index = compiled.index("-map")
    except ValueError:
        map_index = len(compiled)

    rendered = compiled[:]
    rendered.insert(map_index, complex_filter)
    rendered.insert(map_index, "-filter_complex")

    logger.info("running ffmpeg render…")
    ffmpeg.run_async(rendered, pipe_stderr=True).wait()

    logger.info(f"rendered → {out_mp4}")
    return out_mp4
