import logging
import json
import re
import os
import time
import glob
import asyncio
import traceback
import requests
import pyautogui
import ollama
from pydantic import BaseModel
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MacroCore")

app = FastAPI(title="Macro Core")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pyautogui.FAILSAFE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCENARIOS_DIR = os.path.join(BASE_DIR, "scenarios")
VISION_DIR = os.path.join(BASE_DIR, "vision")
MODEL_NAME = "qwen2.5:1.5b"
WEB_LOG_URL = "http://127.0.0.1:4444/api/push-log"

class CommandRequest(BaseModel):
    command: str

def send_to_dashboard(msg):
    """app.py 대시보드 화면으로 로그를 실시간 포워딩"""
    try:
        requests.post(WEB_LOG_URL, json={"message": msg}, timeout=1)
    except Exception:
        pass
    logger.info(msg)

def find_and_click(image_name, confidence_level=0.8, wait_time=1.0):
    try:
        image_path = os.path.join(VISION_DIR, image_name)
        if not os.path.exists(image_path):
            send_to_dashboard(f"❌ 비전 파일 유실: [{image_path}]")
            return False
        location = pyautogui.locateOnScreen(image_path, confidence=confidence_level)
        if location:
            center_x, center_y = pyautogui.center(location)
            pyautogui.moveTo(center_x, center_y, duration=0.2)
            pyautogui.click()
            time.sleep(wait_time)
            return True
        return False
    except Exception as e:
        send_to_dashboard(f"⚠️ 비전 크래시: {str(e)}")
        return False

def load_all_scenarios():
    merged_scenarios = {}
    if not os.path.exists(SCENARIOS_DIR):
        os.makedirs(SCENARIOS_DIR)
        return merged_scenarios
    json_files = glob.glob(os.path.join(SCENARIOS_DIR, "*.json"))
    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                merged_scenarios.update(json.load(f))
        except Exception as e:
            logger.error(f"시나리오 로드 실패: {e}")
    return merged_scenarios

async def run_macro_sequence(macro, delay_seconds):
    if delay_seconds > 0:
        send_to_dashboard(f"⏳ 예약 대기 ➡️ {delay_seconds}초 후 실행")
        await asyncio.sleep(delay_seconds)
    
    send_to_dashboard(f"🔥 매크로 시퀀스 가동 ➡️ [{macro.get('description', '')}]")
    for step in macro.get("steps", []):
        action = step.get("action")
        delay = step.get("delay", 1.0)

        if action == "vision_click":
            target_img = step.get("target")
            conf = step.get("confidence", 0.8)
            if not find_and_click(target_img, confidence_level=conf, wait_time=delay):
                send_to_dashboard(f"❌ 비전 타겟 매칭 실패 [{target_img}] 시퀀스 중단")
                return
            send_to_dashboard(f"🎯 비전 클릭 성공: [{target_img}]")
        elif action == "type":
            text_to_type = step.get("text")
            pyautogui.write(text_to_type, interval=0.05)
            send_to_dashboard(f"⌨️ 키보드 타이핑: '{text_to_type}'")
            time.sleep(delay)
    send_to_dashboard("✅ 시나리오 전 단계 최종 완료")

@app.post("/api/command")
async def process_macro_routing(request: CommandRequest):
    user_command = request.command
    send_to_dashboard(f"📩 [Macro Engine] 자연어 해석 인입: '{user_command}'")

    all_scenarios = load_all_scenarios()
    scenarios_desc = ""
    for s_id, s_data in all_scenarios.items():
        scenarios_desc += f"- '{s_id}': {s_data.get('description', '')}\n"

    system_prompt = (
        "You are an advanced Windows automation router. Analyze the user's command and match it to the correct scenario ID and detect any delay time.\n\n"
        f"Available Scenario IDs:\n{scenarios_desc}- 'unknown': when no scenario matches.\n\n"
        "Strictly output ONLY a raw JSON object with 'scenario_id' and 'delay_seconds' (integer, default 0)."
    )

    try:
        response_data = ollama.chat(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_command}],
            options={"temperature": 0.0, "num_predict": 50},
            format="json"
        )
        response = response_data['message']['content'].strip()
        
        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        if not json_match:
            raise ValueError("OLLAMA JSON 응답 파싱 에러")
            
        parsed_intent = json.loads(json_match.group(0))
        scenario_id = parsed_intent.get("scenario_id", "unknown")
        delay_seconds = parsed_intent.get("delay_seconds", 0)

        if scenario_id != "unknown" and scenario_id in all_scenarios:
            matched_macro = all_scenarios[scenario_id]
            # 비동기로 매크로 시퀀스 백그라운드 실행
            asyncio.create_task(run_macro_sequence(matched_macro, delay_seconds))
            
            msg = f"{delay_seconds}초후 예약 구동" if delay_seconds > 0 else "매크로 실행"
            send_to_dashboard(f"🤖 AI 분석 성공 ➡️ ID: {scenario_id} / 예약: {delay_seconds}초")
            return {"status": "success", "message": msg}
        else:
            send_to_dashboard("⚠️ AI 매핑 실패 ➡️ 알수없는 커맨드, 등록되지 않은 매크로 ID")
            return {"status": "fail", "message": "일치하는 매크로 시나리오가 없습니다."}
            
    except Exception as e:
        logger.error(traceback.format_exc())
        send_to_dashboard(f"❌ 라우팅 내부 에러: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=4445)