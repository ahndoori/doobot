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
import platform
import subprocess
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

import screenshot

is_running = False # 매크로 동작 플래그
stop_requested = False # 단축키 종료 요청 플래그
last_executed_scenario = None # 최근 시나리오
threading_lock = threading.Lock() # 플래그 제어 락

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("Macro-Core")

pyautogui.FAILSAFE = False
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCENARIOS_DIR = os.path.join(BASE_DIR, "scenarios")
MODEL_NAME = "qwen2.5:1.5b"
WEB_LOG_URL = "http://127.0.0.1:4444/api/push-log"
OP_IMAGE_MAP = {
    "+": "calc_plus.png",
    "-": "calc_minus.png",
    "*": "calc_multiply.png",
    "/": "calc_devide.png"
}

macro = FastAPI(title="Macro Core")
macro.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        if not all_click_with_ctrl:
            center_pos=screenshot.match_gray_image(image_name, confidence_level)
            if center_pos is False: return False
            cx = center_pos[0] + step.get("x", 0)
            cy = center_pos[1] + step.get("y", 0)
            logger.info(f'🎯 {cx}x{cy}, {step.get("x",0)}x{step.get("y",0)}')
            pyautogui.moveTo(cx, cy, duration=0.2)
            pyautogui.click()
            if double_click: pyautogui.click()
            return True
        else:
            filtered_points=screenshot.match_gray_image_all(image_name,confidence_level)
            if not filtered_points: return False
            for cx, cy in filtered_points:
                pyautogui.moveTo(cx, cy, duration=0.2)
                pyautogui.keyDown('ctrl')
                pyautogui.click()
                pyautogui.keyUp('ctrl')
            return True
    except Exception as e:
        logger.error(f"⚠️ click_sync Exception {str(e)}")
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
            logger.error(f"load_all_scenarios Exception {e}")
    return merged_scenarios


def run_macro_step(step,params):
    global stop_requested
    logger.info(f"➡️ run_macro_step {step} {params}")
    action = step.get("action")
    if action == "check_youtube_shorts":
        import rules
        return rules.check_youtube_shorts(step,stop_requested=lambda:stop_requested)
    elif action == "hover":
        if step.get("target"):
            position=screenshot.match_gray_image(step.get("target"),step.get("confidence", 0.7))
            if position:
                pyautogui.moveTo(position[0]+step.get("x",0),position[1]+step.get("y",0),duration=0.3)
                return True
            else:
                return False
        else:
            pyautogui.moveTo(step.get("x", 0), step.get("y", 0), duration=0.3)
            return True

    elif action in ["dblclick", "click", "vision_click"]:
        target_img = step.get("target")
        conf = step.get("confidence", 0.6)
        try:            
            result = click_sync(step,target_img, conf, False, True if action == "dblclick" else False)
        except Exception as thread_err:
            result = False
        if not result:
            try:
                dashboard(f"❌ VISION FAILURE CLICK {target_img}")
                ImageGrab.grab().save(os.path.join(BASE_DIR,"debug.png"))
            except Exception:
                pass
            return False
        dashboard(f"🎯 SUCCESS CLICK: {target_img}")
        return True
    elif action == "click_all":
        target_img = step.get("target")
        conf = step.get("confidence", 0.7)
        result = click_sync(step,target_img, conf, True)
        if not result:
            dashboard(f"⚠️ 다중매칭 실패 혹은 타겟 없음: [{target_img}]")
            return False
        else:
            dashboard(f"✅ 모든 [{target_img}] 타겟 새 탭 열기 완료")

    elif action == "click_calc":
        op_sign = params.get("op", "+")
        target_img = OP_IMAGE_MAP.get(op_sign, "calc_plus.png")
        conf = step.get("confidence", 0.55)
        try:
            result = click_sync(step,target_img, conf, False)
        except Exception:
            result = False
        if not result:
            try:
                dashboard(f"❌ VISION FAILURE CLICK-CALC {target_img}")
                ImageGrab.grab().save(os.path.join(BASE_DIR,"debug.png"))
            except Exception:
                pass
            return False
        dashboard(f"🎯 SUCCESS CLICK-CALC [{target_img}] ({op_sign})")
        return True
    elif action == "check_wait":
        target_img = step.get("target")
        interval = step.get("interval", 0.5)
        limit = step.get("limit", 30)
        dashboard(f"⏳ 화면 대기 시작: [{target_img}] (최대 {limit}초, 주기 {interval}초)")
        elapsed_time = 0.0
        result = False
        while elapsed_time < limit:
            if stop_requested: return False
            result=screenshot.match_gray_image(target_img,step.get("confidence", 0.7))
            if result:
                dashboard(f"✨ 타겟 발견: [{target_img}] ({elapsed_time:.1f}sec)")
                break
            dashboard(f"🔍 탐색 중... ({elapsed_time:.1f}s / {limit}s)")
            time.sleep(interval)
            elapsed_time += interval
        if not result:
            pyautogui.screenshot().save(os.path.join(BASE_DIR,"debug.png"))
            dashboard(f"❌ VISION FAILURE CHECK-WAIT {target_img}")
            return False
    elif action == "type":
        text_to_type = step.get("text")
        if "{num1}" in text_to_type: text_to_type = text_to_type.replace("{num1}", params.get("num1", "0"))
        if "{num2}" in text_to_type: text_to_type = text_to_type.replace("{num2}", params.get("num2", "0"))
        pyautogui.write(text_to_type, interval=0.05)
        dashboard(f"⌨️ KEY TYPING: '{text_to_type}'")
    elif action == "press":
        key_to_press = step.get("key")
        pyautogui.press(key_to_press)
        dashboard(f"⌨️ KEY PRESS: [{key_to_press}]")
    elif action == "scroll":
        clicks = step.get("clicks", -100)
        pyautogui.scroll(clicks)
        dashboard(f"⌨️ SCROLL {clicks}")
    return True


def run_macro_sequence(macro, params=None):
    global is_running, stop_requested
    if params is None: params = {}
    dashboard(f"🔥 매크로 시퀀스 ➡️ [{macro.get('description', '')}]")
    logger.info(macro)
    
    try:
        while True:
            step_failed = False

            for idx, step in enumerate(macro.get("steps", [])):
                if stop_requested: break
                if step.get("action") == "check_branch":
                    target_img = step.get("target")
                    result=screenshot.match_gray_image(target_img,step.get("confidence", 0.7))
                    if not result and step.get("target2"): result=screenshot.match_gray_image(step.get("target2"),step.get("confidence", 0.7))
                    branch_steps = []
                    if result:
                        dashboard(f"🔍 check_branch success {target_img}")
                        branch_steps = step.get("true",[])
                    else:
                        dashboard(f"🔍 check_branch failure {target_img}")
                        branch_steps = step.get("false",[])
                    for b_step in branch_steps:
                        if stop_requested: break
                        if not run_macro_step(b_step, params):
                            step_failed=True
                            break
                        time.sleep(b_step.get("delay", 1.0))
                    
                    if step_failed or stop_requested: break ## STOP
                    continue

                if not run_macro_step(step, params):
                    step_failed=True
                    break

                time.sleep(step.get("delay", 1.0))

            if stop_requested or step_failed: break ## STOP
            if not macro.get('loop'): break ## STOP

    finally:
        with threading_lock:
            is_running = False
            stop_requested = False
        dashboard("✅ 시나리오 종료")


def start(matched_macro, params, callback_on_finish):
    global stop_requested
    with threading_lock:
        stop_requested = False

    def thread_wrapper():
        try:
            run_macro_sequence(matched_macro, params)
        finally:
            callback_on_finish()

    threading.Thread(target=thread_wrapper,daemon=True).start()

def kill():
    global stop_requested
    with threading_lock:
        stop_requested = True










'''
import hotkey

hotkey.init_hotkeys()

class CommandRequest(BaseModel):
    command: str

@macro.post("/api/command")
def macro_api_command(request: CommandRequest):
    user_command = request.command
    dashboard(f"📩 macro /api/command '{user_command}'")

    try:
        rule_hint = rules.pre_analyze_intent(user_command)
        logger.info(f"💡 RULE-HINT 분석 성공: {rule_hint}")
    except Exception as e:
        logger.error(f"⛈️ pre_analyze_intent Exception {str(e)}")
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

            global last_executed_scenario, is_running, stop_requested
            with threading_lock:
                if is_running:
                    dashboard("⚠️ 이미 다른 매크로가 실행 중입니다.")
                    return {"status": "fail", "message": "이미 실행 중"}
                is_running = True
                stop_requested = False
                last_executed_scenario = {"macro": matched_macro, "params": params}

            threading.Thread(target=run_macro_sequence, args=(matched_macro, params), daemon=True).start()
            
            dashboard(f"🤖 AI분석: {scenario_id}, PARAMETERS: {params}")
            return {"status": "success", "message": f"매크로 실행"}
        else:
            dashboard(f"AI Mapping Fail -> 등록되지 않은 시나리오 ID (결과: {scenario_id})")
            return {"status": "fail", "message": "일치하는 매크로 시나리오가 없습니다."}
    except Exception as e:
        logger.error(f"⛈️ [Ollama 연산/파싱 중 크래시]: {str(e)}")
        return {"status": "error", "message": str(e)}
'''