# services/elevenlabs_service.py
import os
from typing import Optional, List
from io import BytesIO

from dotenv import load_dotenv
from pydub import AudioSegment
from elevenlabs import ElevenLabs, VoiceSettings
from elevenlabs.core.api_error import ApiError

from utils.logger import get_logger

load_dotenv()
logger = get_logger("elevenlabs_service")

def _allowed_formats(env_val: Optional[str]) -> List[str]:
    """
    Order matters: we try the env format first (if provided), then fallbacks
    that are widely available on lower tiers.
    """
    fallbacks = [
        "mp3_44100_128",
        "mp3_44100_64",
        "mp3_22050_64",
        "mp3_44100_32",
    ]
    if env_val and env_val not in fallbacks:
        return [env_val] + fallbacks
    if env_val and env_val in fallbacks:
        # Put env_val first, then the rest without duplicating it
        return [env_val] + [f for f in fallbacks if f != env_val]
    return fallbacks

def synthesize_sermon(sermon_text: str, outfile_mp3: str, voice_id: Optional[str] = None) -> str:
    """
    Converts sermon text to speech using ElevenLabs, writes MP3 with gentle
    head/tail padding. Auto-downgrades output format if plan doesn’t allow
    the requested one.
    Returns the path to the MP3.
    """
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY missing in .env")
    client = ElevenLabs(api_key=api_key)

    voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID")
    if not voice_id:
        raise RuntimeError("ELEVENLABS_VOICE_ID missing in .env")

    # voice settings from .env
    stability = float(os.getenv("ELEVENLABS_STABILITY", "0.30"))
    similarity = float(os.getenv("ELEVENLABS_SIMILARITY", "0.75"))
    style = float(os.getenv("ELEVENLABS_STYLE", "0.75"))

    settings = VoiceSettings(
        stability=stability,
        similarity_boost=similarity,
        style_exaggeration=style,
        use_speaker_boost=True
    )

    # output format handling with graceful fallback
    requested = os.getenv("ELEVENLABS_OUTPUT_FORMAT", "").strip() or None
    formats_to_try = _allowed_formats(requested)

    last_err: Optional[Exception] = None
    audio_bytes: Optional[bytes] = None
    used_format: Optional[str] = None

    for fmt in formats_to_try:
        try:
            logger.info(f"Requesting TTS from ElevenLabs (format {fmt})...")
            audio_iter = client.text_to_speech.convert(
                voice_id=voice_id,
                output_format=fmt,
                text=sermon_text,
                voice_settings=settings
            )
            audio_bytes = b"".join(audio_iter)
            used_format = fmt
            break
        except ApiError as e:
            # If plan disallows this format, try the next one
            msg = getattr(e, "body", {}) or {}
            detail = msg.get("detail") if isinstance(msg, dict) else None
            status = (detail or {}).get("status") if isinstance(detail, dict) else None
            if status == "output_format_not_allowed":
                logger.warning(f"Format {fmt} not allowed on current ElevenLabs plan; trying another…")
                last_err = e
                continue
            # Some other API error — stop
            last_err = e
            break
        except Exception as e:
            last_err = e
            logger.warning(f"TTS attempt with format {fmt} failed: {e}")
            continue

    if audio_bytes is None:
        raise RuntimeError(
            f"Failed to synthesize audio with available formats ({formats_to_try}). "
            f"Last error: {last_err}"
        )

    # Save MP3 with a gentle pad.
    # Note: regardless of used_format bitrate, we re-export at 192k for YouTube-friendly quality.
    os.makedirs(os.path.dirname(outfile_mp3), exist_ok=True)

    try:
        # The ElevenLabs mp3_* formats come back as MP3 bytes.
        audio = AudioSegment.from_file(BytesIO(audio_bytes), format="mp3")
    except Exception:
        # In case ElevenLabs ever returns a non-mp3 container for a future format,
        # try letting pydub detect it implicitly (ffmpeg backend).
        audio = AudioSegment.from_file(BytesIO(audio_bytes))

    pad = AudioSegment.silent(duration=500)
    final_audio = pad + audio + pad
    final_audio.export(outfile_mp3, format="mp3", bitrate="192k")

    logger.info(f"TTS saved to {outfile_mp3} (requested format={requested or 'default'}, used={used_format})")
    return outfile_mp3
