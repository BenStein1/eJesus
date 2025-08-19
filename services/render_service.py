# services/render_service.py
import os
import re
import subprocess
from typing import List, Tuple, Optional

from dotenv import load_dotenv
from pydub import AudioSegment
from PIL import Image, ImageDraw, ImageFont

from utils.logger import get_logger

load_dotenv()
logger = get_logger("render_service")

# ----------------- helpers: general -----------------

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

# ----------------- title card (Pillow) -----------------

def _load_font(font_path: Optional[str], size: int) -> ImageFont.FreeTypeFont:
    try:
        if font_path and os.path.exists(font_path):
            return ImageFont.truetype(font_path, size)
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()

def make_title_card(title: str, subtitle: str, out_png: str, resolution: str, font_path: Optional[str]):
    W, H = _parse_resolution(resolution)
    bg = (18, 18, 18)
    fg = (235, 235, 235)
    accent = (120, 180, 255)

    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    title_font = _load_font(font_path, 72)
    sub_font = _load_font(font_path, 40)
    brand_font = _load_font(font_path, 28)

    tb = d.textbbox((0, 0), title, font=title_font)
    tw = tb[2] - tb[0]; th = tb[3] - tb[1]
    d.text(((W - tw) // 2, H // 2 - th), title, font=title_font, fill=fg)

    sb = d.textbbox((0, 0), subtitle, font=sub_font)
    sw = sb[2] - sb[0]
    d.text(((W - sw) // 2, H // 2 + 30), subtitle, font=sub_font, fill=accent)

    brand = os.getenv("BRAND_NAME", "eJesus")
    bb = d.textbbox((0, 0), brand, font=brand_font)
    bw = bb[2] - bb[0]
    d.text((W - bw - 40, H - 60), brand, font=brand_font, fill=(180, 180, 180))

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    img.save(out_png, "PNG")
    logger.info(f"title card → {out_png}")
    return out_png

# ----------------- compatibility stub for main.py (not used yet) -----------------

def chunk_text_for_overlays(body: str, max_chars: int = 90) -> List[str]:
    """
    Compatibility helper for main.py. Not used in images-only pipeline.
    Returns short lines from the body (first sentence of each paragraph),
    falling back to fixed-size chunks.
    """
    body = body or ""
    paras = [p.strip() for p in body.split("\n") if p.strip()]
    chosen: List[str] = []
    for p in paras:
        parts = re.split(r'(?<=[.!?])\s+', p)
        if parts and parts[0]:
            line = parts[0].strip()
            if len(line) > max_chars:
                line = line[:max_chars].rsplit(" ", 1)[0] + "…"
            chosen.append(line)
    if not chosen:
        body_clean = re.sub(r"\s+", " ", body).strip()
        for i in range(0, len(body_clean), max_chars):
            chunk = body_clean[i:i+max_chars].strip()
            if chunk:
                chosen.append(chunk)
    return chosen[:100]

# ----------------- ffmpeg helpers -----------------

def _run(cmd: List[str], label: str):
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="ignore")
        logger.error(f"{label} failed (code {e.returncode})\n{stderr}")
        raise

def _scale_to_cover_clause(out_w: int, out_h: int) -> str:
    """
    Portable 'cover' scaling via expressions (no force_original_aspect_ratio).
    Result of this filter has size out_w x out_h.
    """
    ratio_expr = f"{out_w}/{out_h}"
    return (
        f"scale=w='if(gt(a,{ratio_expr}),{out_h}*a,{out_w})':"
        f"h='if(gt(a,{ratio_expr}),{out_h},{out_w}/a)',"
        f"crop={out_w}:{out_h},setsar=1"
    )

# ----------------- motion patterns (fixed-zoom Ken Burns) -----------------
# Allowed moves only:
#   0: pan right
#   1: pan diag up-right
#   2: pan diag down-right
#   3: pan diag up-left
#   4: pan diag down-left
#
# No zoom animation (push/pull). We pre-zoom to a fixed factor so we have room to pan.

def _zoompan_expr(frames: int, mode: int) -> Tuple[str, str, str]:
    """
    Return (zoom_expr, x_expr, y_expr) for zoompan based on a mode.
    - Fixed zoom for the whole slide (default 1.25, overridable via KB_ZOOM env).
    - Pan is a linear interpolation between integer anchors to prevent jitter.
    - Spans are computed at the fixed zoom so motion is feasible across the clip.
    """
    frames_m1 = max(1, frames - 1)
    t = f"(on/{frames_m1})"  # 0..1 linear progress

    # Fixed pre-zoom (e.g., 1.25 => 125%); keep as a literal so ffmpeg treats it constant.
    zfixed = float(os.getenv("KB_ZOOM", "1.25"))
    zoom = f"{zfixed:.5f}"

    # SAFE spans at fixed zoom (constant over time); quantize to integers.
    xspan_safe = f"floor(max(iw-(ow/{zoom}),0))"
    yspan_safe = f"floor(max(ih-(oh/{zoom}),0))"

    # Integer centers
    xmid = f"round({xspan_safe}/2)"
    ymid = f"round({yspan_safe}/2)"

    # Start/end anchors
    x0, x1 = "0", xspan_safe
    y0, y1 = "0", yspan_safe

    # Integer lerp
    def lerp(a: str, b: str) -> str:
        return f"round(({a})*(1-{t})+({b})*{t})"

    # Modes (no zooming changes, just panning)
    if mode == 0:
        # pan right
        x = lerp(x0, x1)
        y = ymid
    elif mode == 1:
        # pan diag up-right
        x = lerp(x0, x1)
        y = lerp(y1, y0)
    elif mode == 2:
        # pan diag down-right
        x = lerp(x0, x1)
        y = lerp(y0, y1)
    elif mode == 3:
        # pan diag up-left
        x = lerp(x1, x0)
        y = lerp(y1, y0)
    else:
        # pan diag down-left
        x = lerp(x1, x0)
        y = lerp(y0, y1)

    return (zoom, x, y)

# ----------------- per-clip builders -----------------

def _make_intro_still_clip(bg_png: str, seconds: float, out_w: int, out_h: int, out_mp4: str):
    """Intro: **static** title card (no motion)."""
    cover = _scale_to_cover_clause(out_w, out_h)
    cmd = [
        "ffmpeg", "-y",
        "-framerate", "30", "-loop", "1", "-i", bg_png,
        "-filter_complex",
        (
            f"[0:v]{cover},format=yuv420p[vout]"
        ),
        "-map", "[vout]",
        "-vsync", "cfr",
        "-r", "30",
        "-t", f"{seconds:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", "4500k", "-pix_fmt", "yuv420p",
        out_mp4
    ]
    _run(cmd, "intro-still")

def _make_slide_clip(img_path: str, seconds: float, out_w: int, out_h: int, out_mp4: str, mode: int):
    """Slide: fixed-zoom panning (no push/pull), one motion for entire clip."""
    frames = max(1, int(seconds * 30))
    zoom, kb_x, kb_y = _zoompan_expr(frames, mode % 5)
    cover = _scale_to_cover_clause(out_w, out_h)
    cmd = [
        "ffmpeg", "-y",
        "-framerate", "30", "-loop", "1", "-i", img_path,
        "-filter_complex",
        (
            f"[0:v]{cover}[v];"
            f"[v]zoompan=z='{zoom}':x='{kb_x}':y='{kb_y}':d=1:fps=30:s={out_w}x{out_h},"
            f"format=yuv420p[vout]"
        ),
        "-map", "[vout]",
        "-vsync", "cfr",
        "-r", "30",
        "-t", f"{seconds:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", "4500k", "-pix_fmt", "yuv420p",
        out_mp4
    ]
    _run(cmd, f"slide-clip:{os.path.basename(img_path)}")

def _concat_clips(clips: List[str], out_mp4: str, cache_dir: str):
    """Concat pre-encoded clips (same codec/params) using concat demuxer."""
    list_path = os.path.join(cache_dir, "concat_list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for c in clips:
            f.write(f"file '{os.path.abspath(c)}'\n")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        out_mp4
    ]
    _run(cmd, "concat")

def _mux_audio(video_mp4: str, audio_path: str, out_mp4: str):
    """Mux the audio track with the final video; cut to shortest (audio is source of truth)."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_mp4,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        out_mp4
    ]
    _run(cmd, "mux")

# ----------------- main render -----------------

def render_kenburns_video(
    images: List[str],
    audio_mp3: str,
    out_mp4: str,
    title_text: str,
    overlay_lines: List[str],  # unused for now; keeping signature stable
    resolution: str = "1920x1080",
    intro_seconds: float = 5.0,
    font_path: Optional[str] = None
) -> str:
    """
    Build video by:
      1) Intro **static** title card (no motion)
      2) Slides with fixed-zoom pans (pan right / diagonals only)
      3) Concat all clips
      4) Mux audio (audio dictates the final duration)
    """
    out_w, out_h = _parse_resolution(resolution)
    audio = AudioSegment.from_file(audio_mp3)
    total_sec = max(1.0, len(audio) / 1000.0)

    cache_dir = os.path.join(os.path.dirname(out_mp4), "cache")
    os.makedirs(cache_dir, exist_ok=True)

    # Title card background
    title_bg_png = os.path.join(cache_dir, "title_card.png")
    make_title_card(title_text, os.getenv("BRAND_NAME", "eJesus"), title_bg_png, resolution, font_path)

    # Guardrails on intro vs total
    if total_sec < intro_seconds + 3:
        intro_seconds = max(2.0, total_sec * 0.20)

    # If no backgrounds, reuse the title card
    if not images:
        images = [title_bg_png]

    # Remaining seconds after intro
    remaining = max(0.1, total_sec - intro_seconds)

    # Per-slide target bounds and heuristic
    min_per_slide = 4.0
    max_per_slide = 12.0
    ideal = max(min_per_slide, min(max_per_slide, remaining / max(1, len(images))))

    # Build a slide plan by cycling images until we cover the remaining duration
    slide_plan: List[Tuple[str, float]] = []
    t_accum = 0.0
    i = 0
    while t_accum + ideal < remaining - 0.25:  # small epsilon
        img = images[i % len(images)]
        slide_plan.append((img, ideal))
        t_accum += ideal
        i += 1
    # Tail gets the exact leftover (>= 1s)
    tail = max(1.0, remaining - t_accum)
    slide_plan.append((images[i % len(images)], tail))

    # Build the clips
    clips: List[str] = []
    intro_clip = os.path.join(cache_dir, "clip_00_intro_still.mp4")
    _make_intro_still_clip(title_bg_png, intro_seconds, out_w, out_h, intro_clip)
    clips.append(intro_clip)

    for idx, (img, secs) in enumerate(slide_plan, start=1):
        clip_path = os.path.join(cache_dir, f"clip_{idx:02d}.mp4")
        mode = (idx - 1) % 5  # cycle through 5 motion patterns
        _make_slide_clip(img, secs, out_w, out_h, clip_path, mode)
        clips.append(clip_path)

    # Concat video-only
    concat_video = os.path.join(cache_dir, "video_concat.mp4")
    _concat_clips(clips, concat_video, cache_dir)

    # Mux audio, audio is source of truth
    tmp_final = os.path.join(cache_dir, "final_mux.mp4")
    _mux_audio(concat_video, audio_mp3, tmp_final)

    # Move to out_mp4
    try:
        if os.path.abspath(tmp_final) != os.path.abspath(out_mp4):
            if os.path.exists(out_mp4):
                os.remove(out_mp4)
            os.replace(tmp_final, out_mp4)
    except Exception as e:
        logger.error(f"Failed to move final file: {e}")
        raise

    logger.info(f"rendered → {out_mp4}")
    return out_mp4
