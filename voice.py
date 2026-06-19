import sys
import os
import re
import json
import requests
import queue
import tempfile
import sounddevice as sd
from vosk import Model, KaldiRecognizer
import edge_tts
import pygame
import asyncio

WAKE_WORD = "야야"
API_URL = "http://127.0.0.1:4445/api/command"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TEMP_DIR = tempfile.gettempdir()
MP3_FILE_PATH = os.path.join(TEMP_DIR, "doobot_speech.mp3")

q = queue.Queue()

def callback(indata, frames, time, status):
    if status:
        print(status, file=sys.stderr, flush=True)
    q.put(bytes(indata))

def play_tts(text):
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        async def amain():
            communicate = edge_tts.Communicate(text, "ko-KR-InJoonNeural")
            await communicate.save(MP3_FILE_PATH)
            pygame.mixer.music.load(MP3_FILE_PATH)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
            pygame.mixer.music.unload()
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(amain())
        loop.close()
    except Exception as e:
        print(f"❌ [TTS 에러]: {e}", flush=True)

def voice_monitor_loop():
    print("🔄 [Vosk] 로컬 한국어 모델 로드 중...", flush=True)
    model = Model(lang="ko") 
    rec = KaldiRecognizer(model, 16000)
    rec.SetWords(True)
    
    print("🎤 [Vosk Client] 초고감도 오디오 파이프라인 가동.", flush=True)

    with sd.RawInputStream(samplerate=16000, blocksize=2000, dtype='int16',
                           channels=1, callback=callback):
        while True:
            data = q.get()

            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                speech_text = result.get("text", "").strip()
            else:
                partial_result = json.loads(rec.PartialResult())
                speech_text = partial_result.get("partial", "").strip()
            
            if speech_text:
                print(f"[Captured]: {speech_text}", flush=True)
                
                if speech_text.startswith(WAKE_WORD) or speech_text.replace(" ", "").startswith(WAKE_WORD):
                    pure_command = re.sub(r"^야\s*야", "", speech_text).strip()
                    print(f"🔥 트리거 즉시 감지: {pure_command}", flush=True)
                    rec.Reset()
                    
                    try:
                        response = requests.post(API_URL, json={"command": pure_command}, timeout=5)
                        if response.status_code == 200:
                            res_data = response.json()
                            if res_data.get("status") == "success":
                                play_tts(res_data.get("message"))
                        else:
                            print(f"❌ 코어 응답 실패: {response.status_code}", flush=True)
                    except Exception as e:
                        print(f"❌ 코어 오프라인: {e}", flush=True)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    voice_monitor_loop()