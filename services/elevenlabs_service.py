import os
from dotenv import load_dotenv
from utils.logger import get_logger
from typing import Optional
from pydub import AudioSegment
from io import BytesIO
from elevenlabs import ElevenLabs

load_dotenv()
logger = get_logger("elevenlabs_service")

def synthesize_sermon(sermon_text: str, outfile_mp3: str, voice_id: Optional[str] = None) -> str:
    """
    Converts sermon text to speech using ElevenLabs and writes MP3 44.1k/192kbps.
    Returns the path to the MP3.
    """
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY missing in .env")
    client = ElevenLabs(api_key=api_key)

    voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID")
    if not voice_id:
        raise RuntimeError("ELEVENLABS_VOICE_ID missing in .env")

    logger.info("Requesting TTS from ElevenLabs...")
    audio_bytes = b"".join(client.text_to_speech.convert(
        voice_id=voice_id,
        output_format="mp3_44100_192",
        text=sermon_text
    ))

    os.makedirs(os.path.dirname(outfile_mp3), exist_ok=True)
    with open(outfile_mp3, "wb") as f:
        f.write(audio_bytes)

    # Gentle pad for cleaner start/end
    audio = AudioSegment.from_file(BytesIO(audio_bytes), format="mp3")
    pad = AudioSegment.silent(duration=500)
    final_audio = pad + audio + pad
    final_audio.export(outfile_mp3, format="mp3", bitrate="192k")

    logger.info(f"TTS saved to {outfile_mp3}")
    return outfile_mp3
