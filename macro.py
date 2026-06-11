import sys
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
import rules
import cv2
import numpy as np
import platform
import subprocess
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import ImageGrab
from datetime import datetime

handler = logging.StreamHandler(sys.stdout)
handler.setStream(sys.stdout)
handler.encoding = "utf-8" 
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("Macro-Core")

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
    "/": "calc_devide.png"
}

httpx_client = httpx.AsyncClient()
ollama_async_client = ollama.AsyncClient()

class CommandRequest(BaseModel):
    command: str

def log_sync(msg: str):
    """실제 콘솔창에 강제로 로그를 밀어내어 출력하는 동기 함수 (스레드 안전)"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except NameError:
        import datetime as dt
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
    # sys.stdout으로 직접 밀어내고 flush까지 해줘서 콘솔 누락을 완전히 방지합니다.
    sys.stdout.write(f"{timestamp} [Macro-Core] {msg}\n")
    sys.stdout.flush()

def log(msg: str):
    """비동기/동기/스레드 어디서나 호출해도 안전한 유니버설 로깅 함수"""
    # 1. 일단 logger 표준 출력과 콘솔 출력을 가장 먼저, 무조건 수행합니다.
    logger.info(f"==> {msg}")
    log_sync(msg) 
    
    # 2. 메인 비동기 루프에 태스크를 전달하는 행위는 오직 메인 스레드(비동기 공간)일 때만 안전하게 시도합니다.
    try:
        loop = asyncio.get_running_loop()
        # 이미 이 함수를 실행한 주체가 백그라운드 스레드(to_thread)라면 
        # run_in_executor를 또 쓰지 않고 그냥 넘어갑니다. (위에서 이미 log_sync를 했으므로)
    except RuntimeError:
        # 이벤트 루프가 없는 일반 동기 스레드 공간인 경우 무시
        pass

async def dashboard(msg,tts=False):
    logger.info(f"==> {msg}")
    try:
        await httpx_client.post(WEB_LOG_URL, json={"message": msg}, timeout=0.5)
    except Exception:
        pass
    if tts: asyncio.create_task(asyncio.to_thread(tts_out,msg))

def tts_out(text):
    log("test")
    try:
        current_os = platform.system()
        if current_os == "Darwin":
            subprocess.run(["say", text], check=True)
        elif current_os == "Windows":
            # Windowscom 패키지가 제대로 로드되는지 확인하기 위해 내부 동적 임포트 처리
            try:
                import win32com.client
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                speaker.Speak(text)
            except ImportError:
                log("❌ Windows 환경이지만 'pywin32' 패키지가 설치되지 않았습니다. (pip install pywin32 필요)")
        else:
            logger.warning(f"⚠️ 지원하지 않는 OS 환경입니다: {current_os}")
    except Exception as e:
        # 이 블록 덕분에 NameError나 시스템 크래시가 나더라도 로그에 정확히 기록됩니다.
        log(f"❌ TTS 백그라운드 재생 중 치명적 오류 발생: {str(e)}")
        log(traceback.format_exc())

def click_sync(image_name, confidence_level=0.7, all_click_with_ctrl=False, double_click=False):
    try:
        image_path = os.path.join(VISION_DIR, image_name)
        if not os.path.exists(image_path):
            log(f"❌ 비전 파일 유실: [{image_path}]")
            return False

        logger.info(f"🔍 [OpenCV 매칭 가동] ➡️ {image_name} (모드: {'다중/새탭' if all_click_with_ctrl else '단일/일반'})")
        screen = ImageGrab.grab()
        screen_np = np.array(screen)
        screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)
        template = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if template is None: 
            return False
        w, h = template.shape[::-1]
        res = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)

        if not all_click_with_ctrl:
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
            logger.info(f"📊 매칭 유사도 분석 결과 ➡️ 최고 점수: {max_val:.4f} (목표값: {confidence_level})")
            if max_val >= confidence_level:
                cx = int(max_loc[0] + w / 2)
                cy = int(max_loc[1] + h / 2)
                pyautogui.moveTo(cx, cy, duration=0.2)
                pyautogui.click()
                if double_click: pyautogui.click()
                #time.sleep(wait_time)
                return True
            else:
                logger.info("📊 매칭된 아이콘이 없습니다")
                return False
        else:
            loc = np.where(res >= confidence_level)
            points = list(zip(*loc[::-1]))
            if not points:
                logger.info("📊 매칭된 아이콘이 없습니다")
                return False
            filtered_points = []
            for pt in points:
                cx = int(pt[0] + w / 2)
                cy = int(pt[1] + h / 2)
                if any(abs(cx - fx) < w and abs(cy - fy) < h for fx, fy in filtered_points): # 동일 아이콘 중복 필터링
                    continue
                filtered_points.append((cx, cy))
            logger.info(f"🎯 발견된 타겟 수: {len(filtered_points)}")
            for cx, cy in filtered_points:
                pyautogui.moveTo(cx, cy, duration=0.2)
                pyautogui.keyDown('ctrl')
                pyautogui.click()
                pyautogui.keyUp('ctrl')
                #time.sleep(wait_time)
            return True
    except Exception as e:
        log(f"⚠️ OpenCV 비전 엔진 크래시: {str(e)}")
        return False


def vision_sync(image_name, confidence_level=0.7):
    try:
        image_path = os.path.join(VISION_DIR, image_name)
        if not os.path.exists(image_path):
            log(f"❌ 비전 파일 유실: [{image_path}]")
            return False
        screen = ImageGrab.grab()
        screen_np = np.array(screen)
        screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)
        
        template = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if template is None: 
            return False
        w, h = template.shape[::-1]
        
        res = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        logger.info(f"📊 매칭 유사도 분석 결과 ➡️ 최고 점수: {max_val:.4f} (목표값: {confidence_level})")
        if max_val >= confidence_level:
            cx = int(max_loc[0] + w / 2)
            cy = int(max_loc[1] + h / 2)
            return True
        else:
            logger.info("📊 임계값을 넘는 매칭 아이콘이 없습니다.")
            return False
    except Exception as e:
        log(f"⚠️ OpenCV 비전 엔진 크래시: {str(e)}")
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
            log(f"시나리오 로드 실패: {e}")
    return merged_scenarios





async def run_macro_step(step, params, loop):
    action = step.get("action")
    if action in ["dblclick", "click", "vision_click"]:
        target_img = step.get("target")
        conf = step.get("confidence", 0.6)
        try:
            success = await loop.run_in_executor(None, click_sync, target_img, conf, False, True if action == "dblclick" else False)
        except Exception as thread_err:
            log(f"⚠️ Executor 스레드 붕괴: {str(thread_err)}")
            success = False
        if not success:
            debug_path = os.path.join(BASE_DIR, "debug_screenshot.png")
            try:
                ImageGrab.grab().save(debug_path)
                log(f"📸 [저장 완료] 중단 시점 스냅샷 ➡️ {debug_path}")
            except:
                pass
            await dashboard(f"❌ 비전 타겟 매칭 실패 [{target_img}] 시퀀스 중단")
            return False
        await dashboard(f"🎯 비전 클릭: [{target_img}]")

    elif action == "click_all":
        target_img = step.get("target")
        conf = step.get("confidence", 0.7)
        success = await loop.run_in_executor(None, click_sync, target_img, conf, True)
        if not success:
            await dashboard(f"⚠️ 다중 매칭 실패 혹은 타겟 없음: [{target_img}]")
            return False
        else:
            await dashboard(f"✅ 모든 [{target_img}] 타겟 새 탭 열기 완료")

    elif action == "click_calc":
        op_sign = params.get("op", "+")
        target_img = OP_IMAGE_MAP.get(op_sign, "calc_plus.png")
        conf = step.get("confidence", 0.55)
        try:
            success = await loop.run_in_executor(None, click_sync, target_img, conf, False)
        except Exception:
            success = False
        if not success:
            debug_path = os.path.join(BASE_DIR, "debug_screenshot.png")
            try: ImageGrab.grab().save(debug_path)
            except: pass
            await dashboard(f"❌ 연산자 비전 매칭 실패 [{target_img}] 시퀀스 중단")
            return False
        await dashboard(f"🎯 연산자 비전 클릭: [{target_img}] ({op_sign})")

    elif action == "check_wait":
        target_img = step.get("target")
        conf = step.get("confidence", 0.7)
        interval = step.get("interval", 0.5)
        limit = step.get("limit", 30)

        await dashboard(f"⏳ 화면 대기 시작: [{target_img}] (최대 {limit}초, 주기 {interval}초)")
        
        elapsed_time = 0.0
        found = False

        while elapsed_time < limit:
            # 동기 비전 함수(여기서는 예시로 vision_sync 사용)를 별도 스레드에서 실행
            # 화면에 타겟 이미지가 검출되면 True를 반환한다고 가정합니다.
            found = await loop.run_in_executor(None, vision_sync, target_img, conf)
            
            if found:
                await dashboard(f"✨ 타겟 발견: [{target_img}] ({elapsed_time:.1f}sec)")
                break
                
            # 지정된 인터벌마다 체크 알림 출력 및 비동기 대기
            await dashboard(f"🔍 탐색 중... ({elapsed_time:.1f}s / {limit}s)")
            await asyncio.sleep(interval)
            elapsed_time += interval

        if not found:
            # 타임아웃 발생 시 스크린샷 저장 후 시퀀스 중단
            debug_path = os.path.join(BASE_DIR, "debug_screenshot.png")
            try:
                ImageGrab.grab().save(debug_path)
                log(f"📸 [타임아웃] 중단 시점 스냅샷 ➡️ {debug_path}")
            except Exception:
                pass
            await dashboard(f"❌ [{target_img}] 지정된 시간 내에 찾지 못함. 시퀀스 중단")
            return False

    elif action == "type":
        text_to_type = step.get("text")
        if "{num1}" in text_to_type: text_to_type = text_to_type.replace("{num1}", params.get("num1", "0"))
        if "{num2}" in text_to_type: text_to_type = text_to_type.replace("{num2}", params.get("num2", "0"))
        pyautogui.write(text_to_type, interval=0.05)
        await dashboard(f"⌨️ 키보드 타이핑: '{text_to_type}'")
    elif action == "press":
        key_to_press = step.get("key")
        pyautogui.press(key_to_press)
        await dashboard(f"⌨️ 단축키 입력: [{key_to_press}]")
    elif action == "scroll":
        clicks = step.get("clicks", -100)
        pyautogui.scroll(clicks)
        await dashboard(f"🖱️ 마우스 스크롤 이동: {clicks}")
    return True


async def run_macro_sequence(macro, params=None):
    if params is None: params = {}
    await dashboard(f"🔥 매크로 시퀀스 ➡️ [{macro.get('description', '')}]")

    for idx, step in enumerate(macro.get("steps", [])):
        loop = asyncio.get_event_loop()
        action = step.get("action")

        if action == "check_branch":
            target_img = step.get("target")
            conf = step.get("confidence", 0.7)
            exists = await loop.run_in_executor(None, vision_sync, target_img, conf)
            branch_steps = []
            if exists:
                await dashboard(f"🔍 조건 체크 [성공]: [{target_img}] 발견. steps_true 실행.")
                branch_steps = step.get("true", [])
            else:
                await dashboard(f"🔍 조건 체크 [실패]: [{target_img}] 미발견. steps_false 실행.")
                branch_steps = step.get("false", [])
            for b_step in branch_steps:
                success = await run_macro_step(b_step, params, loop)
                if not success: return
                await asyncio.sleep(b_step.get("delay", 1.0))
            continue
        success = await run_macro_step(step, params, loop)
        if not success: break
        await asyncio.sleep(step.get("delay", 1.0))
    await dashboard("✅ 시나리오 종료")



@app.post("/api/command")
async def process_macro_routing(request: CommandRequest):
    user_command = request.command
    await dashboard(f"📩 macro /api/command '{user_command}'")

    try:
        rule_hint = rules.pre_analyze_intent(user_command)
        logger.info(f"💡 RULE-HINT 분석 성공: {rule_hint}")
    except Exception as e:
        log(f"🚨 [Rule Pre-Analyze 에러]: {str(e)}")
        return {"status": "error", "message": str(e)}

    all_scenarios = load_all_scenarios()
    scenarios_desc = "".join([f"- '{s_id}': {s_data.get('description', '')}\n" for s_id, s_data in all_scenarios.items()])

    prompt = rules.PROMPT_TEMPLATE.format(
        scenarios_desc=scenarios_desc,
        has_math=rule_hint['has_math'],
        suggested_target=rule_hint['suggested_target']
    )

    logger.info("=[DEBUG] OLLAMA SENDING PROMPT ===================")
    logger.info(f"\n{prompt}")
    logger.info(f"User Command: {user_command}")
    logger.info("=======================================================================")

    try:
        response_data = await ollama_async_client.chat(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user_command}],
            options={"temperature": 0.0, "num_predict": 100},
            format="json"
        )
        response = response_data['message']['content'].strip()
        logger.info("=[DEBUG] OLLAMA RAW RESPONSE ===================")
        logger.info(f"Raw: {repr(response)}")
        logger.info("=======================================================================")

        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        if not json_match:
            log("[PARSING ERROR] 응답에서 JSON 형태를 찾을 수 없습니다.")
            raise ValueError("OLLAMA JSON 응답 파싱 에러")
            
        parsed_intent = json.loads(json_match.group(0))
        logger.info(f"🎯 AI 해석 완료 -> {parsed_intent}")
        
        scenario_id = parsed_intent.get("scenario_id", "unknown")

        if scenario_id != "unknown" and scenario_id in all_scenarios:
            matched_macro = all_scenarios[scenario_id]
            params = {
                "num1": parsed_intent.get("num1"),
                "op": parsed_intent.get("op"),
                "num2": parsed_intent.get("num2")
            }
            asyncio.create_task(run_macro_sequence(matched_macro, params=params))
            await dashboard(f"🤖 AI 분석 결과: {scenario_id}, PARAMETERS: {params}",True)
            return {"status": "success", "message": f"매크로 실행"}
        else:
            await dashboard(f"AI Mapping Fail -> 등록되지 않은 시나리오 ID (결과: {scenario_id})")
            return {"status": "fail", "message": "일치하는 매크로 시나리오가 없습니다."}
            
    except Exception as e:
        log(f"🚨 [Ollama 연산/파싱 중 크래시]: {str(e)}")
        log(traceback.format_exc())
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=4445)