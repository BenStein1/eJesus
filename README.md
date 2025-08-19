<p align="center">
  <img src="assets/eJesus_icon.png" alt="eJesus logo" width="160">
</p>
<h1 align="center">eJesus</h1>

# eJesus

Daily sermon pipeline: **OpenAI** (script) → **ElevenLabs** (TTS) → **Canva handoff** (CSV + title card) or **local render** → **YouTube** upload.

## Quickstart

1. **Clone** and create your `.env` (copy `.env.example`).
2. Install system deps: `sudo apt install ffmpeg`
3. Create and activate a venv; install requirements:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
