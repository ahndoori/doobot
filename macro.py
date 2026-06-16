import sys
import logging
import json
import re
import os
import time
import glob
import threading
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
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("Macro-Core")

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

class CommandRequest(BaseModel):
    command: str

def dashboard(msg:str,tts:bool=False):
    try:
        requests.post(WEB_LOG_URL, json={"message": msg}, timeout=0.5)
    except Exception:
        pass
    if tts: 
        threading.Thread(target=tts_out, args=(msg,), daemon=True).start()

def tts_out(text):
    try:
        current_os = platform.system()
        if current_os == "Darwin":
            subprocess.run(["say", text], check=True)
        elif current_os == "Windows":
            try:
                import win32com.client
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                str_text = str(text)
                speaker.Speak(str_text, 0) 
            except ImportError:
                logger.error("❌ tts_out SAPI.SpVoice ImportError")
        else:
            logger.warning(f"⚠️ 지원하지 않는 OS 환경입니다: {current_os}")
    except Exception as e:
        logger.error(f"❌ tts_out Exception {str(e)}")

def click_sync(step,image_name, confidence_level=0.7, all_click_with_ctrl=False, double_click=False):
    logger.info(f"➡️ click_sync {step}")
    try:
        image_path = os.path.join(VISION_DIR, image_name)
        if not os.path.exists(image_path):
            logger.error(f"❌ 비전 파일 유실: [{image_path}]")
            return False
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
                cx = int(max_loc[0] + w / 2) +step.get("x",0)
                cy = int(max_loc[1] + h / 2) +step.get("y",0)
                pyautogui.moveTo(cx, cy, duration=0.2)
                pyautogui.click()
                if double_click: pyautogui.click()
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
                if any(abs(cx - fx) < w and abs(cy - fy) < h for fx, fy in filtered_points):
                    continue
                filtered_points.append((cx, cy))
            logger.info(f"🎯 발견된 타겟 수: {len(filtered_points)}")
            for cx, cy in filtered_points:
                pyautogui.moveTo(cx, cy, duration=0.2)
                pyautogui.keyDown('ctrl')
                pyautogui.click()
                pyautogui.keyUp('ctrl')
            return True
    except Exception as e:
        logger.error(f"⚠️ OpenCV 비전 엔진 크래시: {str(e)}")
        return False

def vision_sync(image_name, confidence_level=0.7):
    try:
        image_path = os.path.join(VISION_DIR, image_name)
        if not os.path.exists(image_path):
            logger.error(f"❌ 비전 파일 유실: [{image_path}]")
            return False
        screen = ImageGrab.grab()
        screen_np = np.array(screen)
        screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)
        template = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if template is None: 
            return False
        w, h = template.shape[::-1]
        res = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)

        '''
        screen_bin = cv2.adaptiveThreshold(
            screen_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        _, template_bin = cv2.threshold(template, 50, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        res = cv2.matchTemplate(screen_bin, template_bin, cv2.TM_CCOEFF_NORMED)
        '''

        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        logger.info(f"📊 매칭 유사도 분석 결과 ➡️ 최고 점수: {max_val:.4f} (목표값: {confidence_level})")

        if max_val >= confidence_level:
            cx = int(max_loc[0] + w / 2)
            cy = int(max_loc[1] + h / 2)
            #return True
            return (cx, cy)
        else:
            logger.info("📊 임계값을 넘는 매칭 아이콘이 없습니다.")
            return False
    except Exception as e:
        logger.error(f"⛈️ vision_sync Exception {str(e)}")
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


def run_macro_step(step,params):
    logger.info(f"➡️ run_macro_step {step} {params}")
    action = step.get("action")
    if action == "check_youtube_shorts":
        import rules
        return rules.check_youtube_shorts(step)
    elif action == "hover":
        if step.get("target"):
            position=vision_sync(step.get("target"), step.get("confidence", 0.6))
            if position: pyautogui.moveTo(position[0]+step.get("x",0),position[1]+step.get("y",0),duration=0.3)
        else:
            pyautogui.moveTo(step.get("x", 0), step.get("y", 0), duration=0.3)
    elif action in ["dblclick", "click", "vision_click"]:
        target_img = step.get("target")
        conf = step.get("confidence", 0.6)
        try:            
            success = click_sync(step,target_img, conf, False, True if action == "dblclick" else False)
        except Exception as thread_err:
            logger.error(f"⚠️ 매크로 실행 오류: {str(thread_err)}")
            success = False
        if not success:
            debug_path = os.path.join(BASE_DIR, "debug_screenshot.png")
            try:
                ImageGrab.grab().save(debug_path)
                logger.info(f"📸 [저장 완료] 중단 시점 스냅샷 ➡️ {debug_path}")
            except:
                pass
            dashboard(f"❌ 비전 타겟 매칭 실패 [{target_img}] 시퀀스 중단")
            return False
        dashboard(f"🎯 비전 클릭: [{target_img}]")

    elif action == "click_all":
        target_img = step.get("target")
        conf = step.get("confidence", 0.7)
        success = click_sync(step,target_img, conf, True)
        if not success:
            dashboard(f"⚠️ 다중 매칭 실패 혹은 타겟 없음: [{target_img}]")
            return False
        else:
            dashboard(f"✅ 모든 [{target_img}] 타겟 새 탭 열기 완료")

    elif action == "click_calc":
        op_sign = params.get("op", "+")
        target_img = OP_IMAGE_MAP.get(op_sign, "calc_plus.png")
        conf = step.get("confidence", 0.55)
        try:
            success = click_sync(step,target_img, conf, False)
        except Exception:
            success = False
        if not success:
            debug_path = os.path.join(BASE_DIR, "debug_screenshot.png")
            try: ImageGrab.grab().save(debug_path)
            except: pass
            dashboard(f"❌ 연산자 비전 매칭 실패 [{target_img}] 시퀀스 중단")
            return False
        dashboard(f"🎯 연산자 비전 클릭: [{target_img}] ({op_sign})")

    elif action == "check_wait":
        target_img = step.get("target")
        conf = step.get("confidence", 0.7)
        interval = step.get("interval", 0.5)
        limit = step.get("limit", 30)

        dashboard(f"⏳ 화면 대기 시작: [{target_img}] (최대 {limit}초, 주기 {interval}초)")
        
        elapsed_time = 0.0
        found = False

        while elapsed_time < limit:
            found = vision_sync(target_img, conf)
            if found:
                dashboard(f"✨ 타겟 발견: [{target_img}] ({elapsed_time:.1f}sec)")
                break
                
            dashboard(f"🔍 탐색 중... ({elapsed_time:.1f}s / {limit}s)")
            time.sleep(interval)
            elapsed_time += interval

        if not found:
            debug_path = os.path.join(BASE_DIR, "debug_screenshot.png")
            try:
                ImageGrab.grab().save(debug_path)
                logger.info(f"📸 [타임아웃] 중단 시점 스냅샷 ➡️ {debug_path}")
            except Exception:
                pass
            dashboard(f"❌ [{target_img}] 지정된 시간 내에 찾지 못함. 시퀀스 중단")
            return False

    elif action == "type":
        text_to_type = step.get("text")
        if "{num1}" in text_to_type: text_to_type = text_to_type.replace("{num1}", params.get("num1", "0"))
        if "{num2}" in text_to_type: text_to_type = text_to_type.replace("{num2}", params.get("num2", "0"))
        pyautogui.write(text_to_type, interval=0.05)
        dashboard(f"⌨️ 키보드 타이핑: '{text_to_type}'")
    elif action == "press":
        key_to_press = step.get("key")
        pyautogui.press(key_to_press)
        dashboard(f"⌨️ 단축키 입력: [{key_to_press}]")
    elif action == "scroll":
        clicks = step.get("clicks", -100)
        pyautogui.scroll(clicks)
        dashboard(f"🖱️ 마우스 스크롤 이동: {clicks}")
    return True


def run_macro_sequence(macro, params=None):
    if params is None: params = {}
    dashboard(f"🔥 매크로 시퀀스 ➡️ [{macro.get('description', '')}]")
    for idx, step in enumerate(macro.get("steps", [])):
        action = step.get("action")
        if action == "check_branch":
            target_img = step.get("target")
            conf = step.get("confidence", 0.7)
            result = vision_sync(target_img, conf)
            if not result and step.get("target2"): result = vision_sync(step.get("target2"), conf)
            branch_steps = []
            if result:
                dashboard(f"🔍 check_branch success {target_img}")
                branch_steps = step.get("true",[])
            else:
                dashboard(f"🔍 check_branch failure {target_img}")
                branch_steps = step.get("false",[])
            for b_step in branch_steps:
                success = run_macro_step(b_step, params)
                if not success: return
                time.sleep(b_step.get("delay", 1.0))
            continue
        success = run_macro_step(step, params)
        if not success: break
        time.sleep(step.get("delay", 1.0))
    if macro.get('loop'):
        run_macro_sequence(macro, params)
    else:
        dashboard("✅ 시나리오 종료")


macro = FastAPI(title="Macro Core")
macro.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@macro.post("/api/command")
def macro_api_command(request: CommandRequest):
    user_command = request.command
    dashboard(f"📩 macro /api/command '{user_command}'")

    try:
        rule_hint = rules.pre_analyze_intent(user_command)
        logger.info(f"💡 RULE-HINT 분석 성공: {rule_hint}")
    except Exception as e:
        logger.error(f"⛈️ [Rule Pre-Analyze 에러]: {str(e)}")
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
    try:
        response_data = ollama.chat(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user_command}],
            options={"temperature": 0.0, "num_predict": 100},
            format="json"
        )
        response = response_data['message']['content'].strip()
        logger.info("=[DEBUG] OLLAMA RAW RESPONSE ===================")
        logger.info(f"Raw: {repr(response)}")

        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        if not json_match:
            logger.error("[PARSING ERROR] 응답에서 JSON 형태를 찾을 수 없습니다.")
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
            threading.Thread(target=run_macro_sequence, args=(matched_macro, params), daemon=True).start()
            
            dashboard(f"🤖 AI 분석 결과: {scenario_id}, PARAMETERS: {params}", True)
            return {"status": "success", "message": f"매크로 실행"}
        else:
            dashboard(f"AI Mapping Fail -> 등록되지 않은 시나리오 ID (결과: {scenario_id})")
            return {"status": "fail", "message": "일치하는 매크로 시나리오가 없습니다."}
    except Exception as e:
        logger.error(f"⛈️ [Ollama 연산/파싱 중 크래시]: {str(e)}")
        return {"status": "error", "message": str(e)}