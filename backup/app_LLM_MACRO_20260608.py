import logging
import json
import re
import os
import time
import glob
import asyncio  # 비동기 지연 처리를 위해 도입
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pyautogui
import ollama

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AIAgent")

app = FastAPI(title="AI Router Agent")
pyautogui.FAILSAFE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCENARIOS_DIR = os.path.join(BASE_DIR, "scenarios")
VISION_DIR = os.path.join(BASE_DIR, "vision")
MODEL_NAME = "qwen2.5:1.5b"

class CommandRequest(BaseModel):
    command: str

def find_and_click(image_name, confidence_level=0.8, wait_time=1.0):
    try:
        image_path = os.path.join(VISION_DIR, image_name)
        logger.info(f"👁️ 비전 스캔 ➡️ [{image_name}] 탐색 중...")
        if not os.path.exists(image_path):
            logger.error(f"❌ 자원 유실: [{image_path}]")
            return False

        location = pyautogui.locateOnScreen(image_path, confidence=confidence_level)
        if location:
            center_x, center_y = pyautogui.center(location)
            logger.info(f"🎯 타겟 일치! 좌표: [{center_x}, {center_y}]")
            pyautogui.moveTo(center_x, center_y, duration=0.2)
            pyautogui.click()
            time.sleep(wait_time)
            return True
        return False
    except Exception as e:
        logger.error(f"비전 에러: {e}")
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
            logger.error(f"❌ 파일 파싱 실패 [{os.path.basename(file_path)}]: {e}")
    return merged_scenarios

# 백그라운드에서 지연 시간(delay)을 대기한 후 매크로 시퀀스를 실행하는 비동기 함수
async def run_macro_sequence(macro, delay_seconds):
    if delay_seconds > 0:
        logger.info(f"⏳ 예약 타임아웃 가동 ➡️ {delay_seconds}초 동안 대기 후 실행합니다.")
        await asyncio.sleep(delay_seconds)  # FastAPI 프로세스를 막지 않고 비동기로 대기
    
    logger.info(f"🔥 매크로 파이프라인 구동 ➡️ [{macro['description']}]")
    for step in macro["steps"]:
        action = step.get("action")
        delay = step.get("delay", 1.0)

        if action == "vision_click":
            target_img = step.get("target")
            conf = step.get("confidence", 0.8)
            if not find_and_click(target_img, confidence_level=conf, wait_time=delay):
                logger.error(f"❌ [{target_img}] 검색 실패로 예약 시퀀스가 취소되었습니다.")
                return
        
        elif action == "type":
            text_to_type = step.get("text")
            logger.info(f"⌨️ 타이핑 시뮬레이션: '{text_to_type}'")
            pyautogui.write(text_to_type, interval=0.05)
            time.sleep(delay)
    logger.info("✅ 예약된 시나리오 수행이 완벽하게 종료되었습니다.")

@app.post("/api/command")
async def process_command(request: CommandRequest):
    user_command = request.command
    logger.info(f"📩 자연어 명령 인입 ➡️ '{user_command}'")

    all_scenarios = load_all_scenarios()
    
    # 1. 로컬 LLM에게 현재 등록된 시나리오 리스트 정보를 바인딩하여 룰 주입
    scenarios_desc = ""
    for s_id, s_data in all_scenarios.items():
        scenarios_desc += f"- '{s_id}': {s_data['description']}\n"

    system_prompt = (
        "You are an advanced Windows automation router.\n"
        "Analyze the user's natural language command and match it to the correct scenario ID and detect any delay time.\n\n"
        f"Available Scenario IDs:\n{scenarios_desc}"
        "- 'unknown': when no scenario matches.\n\n"
        "Strictly output ONLY a raw JSON object with 'scenario_id' (string) and 'delay_seconds' (integer, default 0 if not mentioned).\n"
        "Example 1: '30초 있다가 오버워치를 켜봐' -> {\"scenario_id\": \"overwatch_launch\", \"delay_seconds\": 30}\n"
        "Example 2: '지금 옵치 켜줘' -> {\"scenario_id\": \"overwatch_launch\", \"delay_seconds\": 0}\n"
        "Example 3: '컴퓨터 꺼줘' -> {\"scenario_id\": \"unknown\", \"delay_seconds\": 0}"
    )

    try:
        # 2. 로컬 Qwen 모델에게 의도 분석(Intent Parsing) 요청
        logger.info("Ollama 로컬 가속 커널 추론 가동 (자연어 의도 해석 중...)")
        response_data = ollama.chat(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_command}],
            options={"temperature": 0.0, "num_predict": 50}
        )
        
        response = response_data['message']['content'].strip()
        logger.info(f"🤖 AI 분석 결과 원본: {response}")

        json_match = re.search(r"\{.*?\}", response)
        if not json_match:
            raise ValueError("AI가 정형 JSON을 반환하지 않았습니다.")
            
        parsed_intent = json.loads(json_match.group(0))
        scenario_id = parsed_intent.get("scenario_id", "unknown")
        delay_seconds = parsed_intent.get("delay_seconds", 0)

        # 3. 분석 결과에 따른 시나리오 매핑 및 동적 런타임 분기
        if scenario_id != "unknown" and scenario_id in all_scenarios:
            matched_macro = all_scenarios[scenario_id]
            
            # 태스크를 백그라운드 이벤트 루프에 던져서 즉시 응답을 주고, 실행은 비동기로 대기하게 만듭니다.
            asyncio.create_task(run_macro_sequence(matched_macro, delay_seconds))
            
            return {
                "status": "scheduled" if delay_seconds > 0 else "executing",
                "matched_scenario": scenario_id,
                "delay_seconds": delay_seconds,
                "message": f"{delay_seconds}초 후 매크로가 실행됩니다." if delay_seconds > 0 else "즉시 실행합니다."
            }
        else:
            return {"status": "fail", "reason": "AI가 명령의 의도를 이해하지 못했거나 매칭되는 매크로가 없습니다."}

    except Exception as e:
        logger.error(f"AI 오케스트레이션 중 에러: {e}")
        raise HTTPException(status_code=500, detail=str(e))