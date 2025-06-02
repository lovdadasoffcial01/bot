import os
import base64
import requests
import tempfile
import subprocess
from dotenv import load_dotenv

# Load credentials
load_dotenv()
ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
AUTH_TOKEN = os.getenv("CF_AUTH_TOKEN")

if not ACCOUNT_ID or not AUTH_TOKEN:
    raise EnvironmentError("Missing CF_ACCOUNT_ID or CF_AUTH_TOKEN in .env")

HEADERS = {
    "Authorization": f"Bearer {AUTH_TOKEN}",
    "Content-Type": "application/json"
}

# Available models and configuration
MODEL_CONFIGS = {
    "llama3": {
        "url": f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/meta/llama-3-8b-instruct",
        "context": 8000,
        "payload_type": "messages"
    },
    "qwancoder": {
        "url": f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/qwen/qwen2.5-coder-32b-instruct",
        "context": 32768,  # Fixed comma issue
        "payload_type": "messages"
    },
    "bart_summarizer": {
        "url": f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/facebook/bart-large-cnn",
        "context": 1024,
        "payload_type": "input_text"
    },
    "whisper_stt": {
        "url": f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/openai/whisper-large-v3-turbo",
        "context": 4000,
        "payload_type": "audio"
    },
    "image_captioning": {
        "url": f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/llava/llava-1.5-7b-hf",
        "context": 2048,
        "payload_type": "image"
    }
}

# Task-to-model mapping
def select_model_by_task(task: str) -> str:
    return {
        "chat": "llama3",
        "code": "qwancoder",
        "summary": "bart_summarizer",
        "speech_to_text": "whisper_stt",
        "image_to_text": "image_captioning"
    }.get(task.lower(), "llama3")

# General Cloudflare AI interface
def ask_cloudflare_ai(prompt, history=None, model="llama3", parameters=None):
    history = history or []
    parameters = parameters or {}

    model_info = MODEL_CONFIGS.get(model, MODEL_CONFIGS["llama3"])
    payload_type = model_info["payload_type"]
    context_limit = model_info["context"]
    url = model_info["url"]

    try:
        if payload_type == "messages":
            messages = history + [{"role": "user", "content": prompt}]
            max_tokens = min(1024, context_limit - len(str(messages)) // 4 - 100)
            payload = {"messages": messages, "max_tokens": max_tokens, **parameters}

        elif payload_type == "input_text":
            max_length = min(1024, context_limit - len(prompt) // 4 - 100)
            payload = {"input_text": prompt, "parameters": {"max_length": max_length, **parameters}}

        elif payload_type == "audio":
            return {"type": "text", "data": "Use transcribe_audio() for audio input."}

        elif payload_type == "image":
            return {"type": "text", "data": "Use image_to_text() for image input."}

        else:
            return {"type": "text", "data": f"Unsupported payload type: {payload_type}"}

        res = requests.post(url, headers=HEADERS, json=payload)
        res.raise_for_status()
        data = res.json()
        return {"type": "text", "data": data.get("result", {}).get("response", "No response.")}

    except Exception as e:
        return {"type": "text", "data": f"Error: {e}"}

# Image generation via external API that returns base64
def generate_image(prompt: str) -> dict:
    try:
        api_url = "https://text-to-image.api-url-production.workers.dev/"
        payload = {"prompt": prompt}
        response = requests.post(api_url, json=payload)
        response.raise_for_status()

        result = response.json()
        image_data = result.get("image_base64")
        if not image_data:
            return {"type": "text", "data": "No image returned from API."}

        return {
            "type": "image",
            "data": f"data:image/png;base64,{image_data}",
            "message": f"Here's your image for: '{prompt}'"
        }
    except Exception as e:
        return {"type": "text", "data": f"Image generation error: {e}"}

# Convert MP3 audio to WAV for Whisper STT
def convert_audio_to_wav(audio_data: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as in_file, \
         tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out_file:

        in_file.write(audio_data)
        in_file.flush()

        subprocess.run([
            'ffmpeg', '-i', in_file.name,
            '-acodec', 'pcm_s16le',
            '-ac', '1',
            '-ar', '16000',
            out_file.name
        ], check=True)

        with open(out_file.name, "rb") as f:
            return f.read()

# Speech-to-text using Whisper
def transcribe_audio(audio_data: bytes) -> str:
    try:
        wav_data = convert_audio_to_wav(audio_data)
        base64_audio = base64.b64encode(wav_data).decode("utf-8")

        payload = {
            "audio": base64_audio,
            "encoding": "wav"
        }

        url = MODEL_CONFIGS["whisper_stt"]["url"]
        res = requests.post(url, headers=HEADERS, json=payload)
        res.raise_for_status()

        return res.json().get("result", {}).get("text", "❌ Unable to transcribe audio.")
    except Exception as e:
        return f"Error processing audio: {e}"

# Image captioning (image-to-text) using LLaVA
def image_to_text(image_data: bytes) -> str:
    try:
        base64_image = base64.b64encode(image_data).decode("utf-8")
        payload = {"image": base64_image}

        url = MODEL_CONFIGS["image_captioning"]["url"]
        res = requests.post(url, headers=HEADERS, json=payload)
        res.raise_for_status()

        return res.json().get("result", {}).get("response", "❌ Unable to caption image.")
    except Exception as e:
        return f"Error processing image: {e}"
