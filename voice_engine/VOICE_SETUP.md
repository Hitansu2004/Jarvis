# J.A.R.V.I.S. Voice Clone Setup Guide
## How to Create the Jarvis Voice Reference File

F5-TTS needs a 10-15 second clean audio clip of the JARVIS voice
(Paul Bettany from Iron Man) to clone. Follow these steps exactly.

### Step 1 — Find a Clean Jarvis Audio Clip

Search YouTube for: "JARVIS Iron Man voice clean compilation"
Best clips: JARVIS speaking clearly with no background music or sound effects.
Target: 10-15 seconds of speech. More = better clone quality.

Download with yt-dlp (already installed):
```bash
yt-dlp -x --audio-format wav --audio-quality 0 'YOUTUBE_URL' -o ~/voice_engine/jarvis_raw.wav
```

### Step 2 — Remove Background Music (if present)

If the clip has background music or sound effects, isolate the voice:
```bash
cd ~/voice_engine
python -m demucs --two-stems=vocals jarvis_raw.wav
cp ./separated/htdemucs/jarvis_raw/vocals.wav jarvis_ref.wav
```

If your clip is already clean speech only — skip this step:
```bash
cp jarvis_raw.wav ~/voice_engine/jarvis_ref.wav
```

### Step 3 — Update .env

Open .env and set:
```
TTS_VOICE_REF_FILE=~/voice_engine/jarvis_ref.wav
TTS_VOICE_REF_TEXT=<exact transcript of what JARVIS says in the clip>
```

The transcript must be EXACT — every word, exactly as spoken in the clip.
Example: TTS_VOICE_REF_TEXT=All systems are online, sir. Shall I run a diagnostic?

### Step 4 — Test the Voice Clone

```bash
source .venv/bin/activate
python3 -c "
from voice_engine.tts import get_tts_engine
import asyncio

tts = get_tts_engine()
print('F5-TTS available:', tts._f5tts_available)
asyncio.run(tts.speak('Good evening, Sir. All systems are fully operational.'))
"
```

If F5-TTS is working, you will hear the response in the Jarvis voice.
If jarvis_ref.wav is missing, Kokoro (fast preset voice) will be used instead.

### Step 5 — Test Full Voice Pipeline

Start the server, then:
```bash
curl -X POST http://localhost:8000/voice/speak \
  -H 'Content-Type: application/json' \
  -d '{"text": "Good afternoon, Sir. I am fully operational.", "urgent": false}'
```
