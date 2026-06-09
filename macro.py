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
import httpx
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
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
OP_IMAGE_MAP = {
    "+": "calc_plus.png",
    "-": "calc_minus.png",
    "*": "calc_multiply.png",
    "/": "calc_divide.png"
}

httpx_client = httpx.AsyncClient()
ollama_async_client = ollama.AsyncClient()

class CommandRequest(BaseModel):
    command: str

async def send_to_dashboard(msg):
    logger.info(f"==> {msg}")
    try:
        await httpx_client.post(WEB_LOG_URL, json={"message": msg}, timeout=0.5)
    except Exception:
        pass

def find_and_click_sync(image_name, confidence_level=0.8, wait_time=1.0):
    try:
        image_path = os.path.join(VISION_DIR, image_name)
        if not os.path.exists(image_path):
            logger.error(f"❌ 비전 파일 유실: [{image_path}]")
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
        logger.error(f"⚠️ 비전 크래시: {str(e)}")
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

async def run_macro_sequence(macro, delay_seconds, params=None):
    if params is None:
        params = {}

    if delay_seconds > 0:
        await send_to_dashboard(f"⏳ 예약 대기 ➡️ {delay_seconds}초 후 실행")
        await asyncio.sleep(delay_seconds)
    
    await send_to_dashboard(f"🔥 매크로 시퀀스 ➡️ [{macro.get('description', '')}]")
    
    for step in macro.get("steps", []):
        action = step.get("action")
        delay = step.get("delay", 1.0)

        if action == "vision_click":
            target_img = step.get("target")
            conf = step.get("confidence", 0.8)
            
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, find_and_click_sync, target_img, conf, delay)
            
            if not success:
                await send_to_dashboard(f"❌ 비전 타겟 매칭 실패 [{target_img}] 시퀀스 중단")
                return
            await send_to_dashboard(f"🎯 비전 클릭: [{target_img}]")

        elif action == "vision_click_op":
            op_sign = params.get("op", "+")
            target_img = OP_IMAGE_MAP.get(op_sign, "calc_plus.png")
            conf = step.get("confidence", 0.8)
            
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, find_and_click_sync, target_img, conf, delay)
            
            if not success:
                await send_to_dashboard(f"❌ 연산자 비전 매칭 실패 [{target_img}] 시퀀스 중단")
                return
            await send_to_dashboard(f"🎯 연산자 비전 클릭: [{target_img}] ({op_sign})")

        elif action == "type":
            text_to_type = step.get("text")
            if "{num1}" in text_to_type: text_to_type = text_to_type.replace("{num1}", params.get("num1", "0"))
            if "{num2}" in text_to_type: text_to_type = text_to_type.replace("{num2}", params.get("num2", "0"))
            
            pyautogui.write(text_to_type, interval=0.05)
            await send_to_dashboard(f"⌨️ 키보드 타이핑: '{text_to_type}'")
            await asyncio.sleep(delay)
            
        elif action == "press":
            key_to_press = step.get("key")
            pyautogui.press(key_to_press)
            await send_to_dashboard(f"⌨️ 단축키 입력: [{key_to_press}]")
            await asyncio.sleep(delay)

    await send_to_dashboard("✅ 시나리오 종료")

@app.post("/api/command")
async def process_macro_routing(request: CommandRequest):
    user_command = request.command
    await send_to_dashboard(f"📩 [Macro Engine] 자연어 해석 인입: '{user_command}'")

    all_scenarios = load_all_scenarios()
    scenarios_desc = ""
    for s_id, s_data in all_scenarios.items():
        scenarios_desc += f"- '{s_id}': {s_data.get('description', '')}\n"

    system_prompt = (
        "You are an advanced Windows automation router and parameter extractor.\n"
        "Analyze the user's command to match the correct scenario ID, detect delay time, and extract calculation parameters if applicable.\n\n"
        f"Available Scenario IDs:\n{scenarios_desc}- 'unknown': when no scenario matches.\n\n"
        "If the user wants to calculate (e.g., 'windows_calc'), you MUST extract 'num1', 'op', and 'num2'.\n"
        "Normalize 'op' to one of these single characters: '+', '-', '*', '/'. (e.g., '곱하기' or 'x' becomes '*')\n"
        "Convert Korean number words to strings of digits (e.g., '백' becomes '100', '삼' becomes '3').\n\n"
        "Strictly output ONLY a raw JSON object matching this structure:\n"
        "{\n"
        "  \"scenario_id\": \"string\",\n"
        "  \"delay_seconds\": 0,\n"
        "  \"num1\": \"string or null\",\n"
        "  \"op\": \"string or null\",\n"
        "  \"num2\": \"string or null\"\n"
        "}"
    )

    try:
        response_data = await ollama_async_client.chat(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_command}],
            options={"temperature": 0.0, "num_predict": 100},
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
            
            params = {
                "num1": parsed_intent.get("num1"),
                "op": parsed_intent.get("op"),
                "num2": parsed_intent.get("num2")
            }
            
            asyncio.create_task(run_macro_sequence(matched_macro, delay_seconds, params=params))
            
            msg = f"{delay_seconds}초후 예약 구동" if delay_seconds > 0 else "매크로 실행"
            await send_to_dashboard(f"🤖 AI 분석 ➡️ ID: {scenario_id} / 파라미터: {params}")
            return {"status": "success", "message": msg}
        else:
            await send_to_dashboard("⚠️ AI 매핑 실패 ➡️ 알수없는 커맨드, 등록되지 않은 매크로 ID")
            return {"status": "fail", "message": "일치하는 매크로 시나리오가 없습니다."}
            
    except Exception as e:
        logger.error(traceback.format_exc())
        try:
            await httpx_client.post(WEB_LOG_URL, json={"message": f"❌ 라우팅 내부 에러: {str(e)}"}, timeout=0.5)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=4445)