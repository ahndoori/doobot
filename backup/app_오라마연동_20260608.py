import logging
import json
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pyautogui
import ollama

# 1. 로깅 및 FastAPI 인프라 세팅
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("OllamaAgent")

app = FastAPI(title="Embedded AI Agent via Ollama")
pyautogui.FAILSAFE = False

# 2. Ollama 모델 지정
MODEL_NAME = "qwen2.5:1.5b"
logger.info(f"Ollama 백그라운드 엔진 연동 상태 체크 (Target: {MODEL_NAME})")
logger.info("🔥 [더블클릭 스펙 확장] 초경량 인프라 가동!")

class CommandRequest(BaseModel):
    command: str

# 3. 핵심 명령 처리 라우터
@app.post("/api/command")
async def process_command(request: CommandRequest):
    user_command = request.command
    logger.info(f"이벤트 수신 ➡️ 유저 명령: '{user_command}'")

    # 프롬프트 제약 조건 수정: double_click 액션을 명시적으로 추가합니다.
    system_prompt = (
        "You are a Windows OS automation assistant. Convert the user's input into a raw JSON object. "
        "Do not write any explanation, introduction, or markdown block. Output ONLY the JSON string. "
        "Format: {\"action\": \"click\" or \"double_click\" or \"move\" or \"unknown\", \"x\": int, \"y\": int}\n"
        "Example 1: '300x300에 마우스클릭' -> {\"action\": \"click\", \"x\": 300, \"y\": 300}\n"
        "Example 2: '10x10에 마우스 더블클릭' -> {\"action\": \"double_click\", \"x\": 10, \"y\": 10}\n"
        "Example 3: '500,200으로 마우스 옮겨줘' -> {\"action\": \"move\", \"x\": 500, \"y\": 200}"
    )

    try:
        logger.info("Ollama 로컬 가속 커널 추론 요청 중...")
        
        response_data = ollama.chat(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_command}
            ],
            options={
                "temperature": 0.0,
                "num_predict": 40
            }
        )

        response = response_data['message']['content'].strip()
        logger.info(f"AI 원본 출력 결과물: {response}")

        # 정규식 기반 안전한 JSON 추출 및 파싱
        json_match = re.search(r"\{.*?\}", response)
        if not json_match:
            raise ValueError("AI가 규격에 맞는 정형 JSON 포맷을 반환하지 않았습니다.")
        
        parsed_data = json.loads(json_match.group(0))
        action = parsed_data.get("action", "unknown")
        x = parsed_data.get("x", -1)
        y = parsed_data.get("y", -1)

        # 4. OS 네이티브 물리 하드웨어 핸들러 분기 확장
        if action in ["click", "double_click", "move"] and x != -1 and y != -1:
            logger.info(f"하드웨어 오토메이션 가동 ➡️ 포인터 이동 목표: [{x}, {y}]")
            pyautogui.moveTo(x, y, duration=0.2)
            
            if action == "click":
                logger.info("하드웨어 오토메이션 가동 ➡️ 마우스 왼쪽 클릭 딸깍")
                pyautogui.click()
            elif action == "double_click":
                logger.info("하드웨어 오토메이션 가동 ➡️ 마우스 왼쪽 더블클릭 따닥! 🔥")
                pyautogui.doubleClick()  # PyAutoGUI의 네이티브 더블클릭 API 가동
                
            return {"status": "success", "action": action, "x": x, "y": y}
        else:
            logger.warning(f"파싱은 성공했으나 제어 좌표가 유효하지 않음: {parsed_data}")
            return {"status": "fail", "reason": "해석은 성공했으나 좌표 정보가 부정확합니다."}

    except Exception as e:
        logger.error(f"추론 및 하드웨어 제어 중 에러 발생: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}