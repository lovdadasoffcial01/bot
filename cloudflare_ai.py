import os
import base64
import requests
import tempfile
import subprocess
from typing import Dict, Any, Optional
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
    "flux_image": {
        "url": f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell",
        "context": 1024,
        "payload_type": "image_generation"
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

def ask_cloudflare_ai(prompt: str, history: Optional[list] = None, model: str = "llama3") -> Dict[str, Any]:
    """General Cloudflare AI interface"""
    history = history or []
    
    try:
        model_info = MODEL_CONFIGS.get(model, MODEL_CONFIGS["llama3"])
        payload_type = model_info["payload_type"]
        context_limit = model_info["context"]
        url = model_info["url"]
        
        if payload_type == "messages":
            messages = history + [{"role": "user", "content": prompt}]
            max_tokens = min(1024, context_limit - len(str(messages)) // 4 - 100)
            payload = {"messages": messages, "max_tokens": max_tokens}
            
        elif payload_type == "image_generation":
            payload = {
                "prompt": prompt,
                "seed": int.from_bytes(os.urandom(2), 'big'),
                "num_inference_steps": 50,
                "guidance_scale": 7.5
            }
            
        else:
            return {"type": "text", "data": f"Unsupported payload type: {payload_type}"}
            
        response = requests.post(url, headers=HEADERS, json=payload)
        response.raise_for_status()
        result = response.json()
        
        if "error" in result:
            return {"type": "text", "data": f"API Error: {result['error']}"}
            
        if payload_type == "image_generation":
            image_data = result.get("result", {}).get("image")
            if not image_data:
                return {"type": "text", "data": "No image generated"}
            return {
                "type": "image",
                "data": f"data:image/jpeg;base64,{image_data}",
                "message": f"Generated image for: '{prompt}'"
            }
            
        return {"type": "text", "data": result.get("result", {}).get("response", "No response.")}
        
    except Exception as e:
        return {"type": "text", "data": f"Error: {str(e)}"}

def convert_audio_to_wav(audio_data: bytes) -> bytes:
    """Convert MP3 audio to WAV format"""
    try:
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
    except Exception as e:
        raise RuntimeError(f"Audio conversion error: {str(e)}")

def transcribe_audio(audio_data: bytes) -> str:
    """Transcribe audio using Whisper"""
    try:
        wav_data = convert_audio_to_wav(audio_data)
        base64_audio = base64.b64encode(wav_data).decode("utf-8")
        
        payload = {
            "audio": base64_audio,
            "encoding": "wav"
        }
        
        url = MODEL_CONFIGS["whisper_stt"]["url"]
        response = requests.post(url, headers=HEADERS, json=payload)
        response.raise_for_status()
        
        result = response.json()
        return result.get("result", {}).get("text", "❌ Unable to transcribe audio.")
    except Exception as e:
        return f"Error processing audio: {str(e)}"

def image_to_text(image_data: bytes) -> str:
    """Generate image description using LLaVA"""
    try:
        base64_image = base64.b64encode(image_data).decode("utf-8")
        payload = {"image": base64_image}
        
        url = MODEL_CONFIGS["image_captioning"]["url"]
        response = requests.post(url, headers=HEADERS, json=payload)
        response.raise_for_status()
        
        result = response.json()
        return result.get("result", {}).get("response", "❌ Unable to analyze image.")
    except Exception as e:
        return f"Error processing image: {str(e)}"

def generate_image(prompt: str) -> Dict[str, Any]:
    """Generate image using Flux"""
    try:
        return ask_cloudflare_ai(prompt, model="flux_image")
    except Exception as e:
        return {"type": "text", "data": f"Image generation error: {str(e)}"}
