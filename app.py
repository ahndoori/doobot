import logging
import os
import time
import subprocess
import threading
import sys
import asyncio
import pyautogui
import pywinctl as pwc
import ollama
import re
import json
import contextlib
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

import macro
import hotkey

logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(message)s")
logger=logging.getLogger("WebCore")
#app=FastAPI(title="Automation Console")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(BASE_DIR, "public"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "templates"), exist_ok=True)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
IS_WINDOWS = sys.platform.startswith("win")
VENV_PYTHON = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe") if IS_WINDOWS else os.path.join(BASE_DIR, ".venv", "bin", "python")

infra_context = {
    "macro_process": None,
    "voice_process": None,
    "initialized": False
}

dashboard_history = []
active_connections: List[WebSocket] = []

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    hotkey_thread = threading.Thread(target=start_hotkey_listener, daemon=True)
    hotkey_thread.start()
    yield

app = FastAPI(title="Automation Console",lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/public", StaticFiles(directory=os.path.join(BASE_DIR, "public")), name="public")

async def add_web_log_and_broadcast(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted_log = f"[{timestamp}] {message}"
    print(formatted_log)
    dashboard_history.append(formatted_log)
    if len(dashboard_history) > 100:
        dashboard_history.pop(0)
    for connection in active_connections:
        try:
            await connection.send_json({"type": "new_log", "log": formatted_log})
        except Exception:
            pass

async def broadcast_infra_status():
    macro_alive = (
        infra_context["macro_process"] is not None 
        and infra_context["macro_process"].is_alive()
    )
    voice_alive = (
        infra_context["voice_process"] is not None 
        and infra_context["voice_process"].poll() is None
    )
    for connection in active_connections:
        try:
            await connection.send_json({
                "type": "infra_status",
                "macro_alive": macro_alive,
                "voice_alive": voice_alive
            })
        except Exception:
            pass

def spawn_daemon(target):
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    if target == "macro":
        def run_uvicorn():
            try:
                import uvicorn
                import macro
                uvicorn.run(macro.macro, host="127.0.0.1", port=4445, log_level="info")
            except Exception as e:
                print(f"⛈️ spawn_daemon fastapi_macro Exception {e}")
        proc_thread = threading.Thread(target=run_uvicorn, daemon=True)
        proc_thread.start()
        infra_context["macro_process"] = proc_thread
        
    elif target == "voice":
        proc = subprocess.Popen(
            [VENV_PYTHON, "-u", "voice_listener.py"],
            cwd=BASE_DIR, 
            env=env
        )
        infra_context["voice_process"] = proc

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.post("/api/push-log")
async def fastapi_api_push_log(payload: dict):
    await add_web_log_and_broadcast(payload.get("message", ""))
    return {"status": "ok"}

@app.post("/api/damon/macro")
async def api_demon_macro(target: str):
    key = "macro_process"
    proc = infra_context.get(key)
    if proc is not None and proc.is_alive():
        infra_context[key] = None
        await add_web_log_and_broadcast("🛬 stop demon LLM/Macro")
    else:
        await add_web_log_and_broadcast("🛫 start demon LLM/Macro")
        spawn_daemon("macro")
        await asyncio.sleep(0.5)
    await broadcast_infra_status()
    return {"status": "ok"}

@app.post("/api/damon/voice")
async def api_demon_voice(target: str):
    key = "voice_process"
    proc = infra_context.get(key)
    if proc is not None and proc.poll() is None:
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=1.0) 
            except Exception:
                proc.kill()
        infra_context[key] = None
        await add_web_log_and_broadcast("🛬 stop demon VoiceListener")
    else:
        await add_web_log_and_broadcast("🛫 start demon VoiceListener")
        spawn_daemon("voice")
        await asyncio.sleep(0.5)
    await broadcast_infra_status()
    return {"status": "ok"}

@app.post("/api/infra/toggle/{target}")
async def toggle_infrastructure_status(target: str):
    if target not in ["macro", "voice"]:
        return {"status": "error", "message": "잘못된 타겟 컴포넌트"}
    key = f"{target}_process"
    proc = infra_context[key]
    if target == "macro":
        is_alive = proc is not None and proc.is_alive()
    else:
        is_alive = proc is not None and proc.poll() is None
    if is_alive:
        if target == "voice" and proc is not None:
            proc.terminate()
            proc.wait()
        infra_context[key] = None
        await add_web_log_and_broadcast(f"🛬 stop demon {target}")
    else:
        await add_web_log_and_broadcast(f"🛫 start demon {target}")
        spawn_daemon(target)
        await asyncio.sleep(0.5)

    await broadcast_infra_status()
    return {"status": "ok"}

@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        await websocket.send_json({"type": "init_logs", "logs": dashboard_history})
        await broadcast_infra_status()
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)

@app.websocket("/ws/mouse")
async def websocket_mouse_tracker(websocket: WebSocket):
    await websocket.accept()
    logger.info("☀️ /ws/mouse")
    
    last_x, last_y = -1, -1
    win_title = "알 수 없는 창"
    win_left, win_top = 0, 0
    last_win_check_time = 0 
    
    try:
        while True:
            current_time = time.time()
            
            # 0.5초마다 활성화된 창 체크
            if current_time - last_win_check_time > 0.5:
                # pywinctl은 맥에서도 현재 활성화된 창을 잘 가져옵니다.
                active_win = pwc.getActiveWindow()
                if active_win is not None:
                    # pywinctl은 title 속성 대신 title 변수나 메서드를 지원
                    win_title = active_win.title if hasattr(active_win, 'title') else "알 수 없는 창"
                    # 크로스플랫폼 매칭을 위해 위치 정보 가져오기
                    win_left = active_win.left
                    win_top = active_win.top
                last_win_check_time = current_time
            
            abs_x, abs_y = pyautogui.position()
            
            if abs_x == last_x and abs_y == last_y:
                await asyncio.sleep(0.03)
                continue
                
            last_x, last_y = abs_x, abs_y
            rel_x = abs_x - win_left
            rel_y = abs_y - win_top
            
            data = {
                "window_title": win_title,
                "coords": f"{rel_x}x{rel_y}",
                "abs_coords": f"{abs_x}x{abs_y}"
            }
            await websocket.send_json(data)
            await asyncio.sleep(0.03)
            
    except WebSocketDisconnect:
        logger.info("except WebSocketDisconnect")
    except Exception as e:
        logger.error(f"⛈️ websocket_mouse_tracker Exception {e}")

@app.on_event("shutdown")
def cleanup_zombie_processes():
    if infra_context["voice_process"] is not None:
        proc = infra_context["voice_process"]
        if proc.poll() is None:
            logger.info("☀️ cleanup_zombie_processes: terminating voice_process")
            proc.terminate()












is_running_macro = False
is_processing_hotkey = False
app_threading_lock = threading.Lock()

def start_hotkey_listener():
    try:
        hotkey.register_hotkey_c_s_q(combination="ctrl+shift+q", callback=handler_hotkey_c_s_q)
        logger.info("🔑 단축키(ctrl+shift+q) 등록 완료")
    except Exception as e:
        logger.error(f"단축키 리스너 실행 중 오류 발생: {e}")


def handler_hotkey_c_s_q():
    global is_running_macro, is_processing_hotkey
    print('handler_hotkey_c_s_q')
    with app_threading_lock:
        if is_processing_hotkey:
            return
        is_processing_hotkey = True
        
    try:
        if is_running_macro:
            is_running_macro = False
            logger.info("🚨 [App 승인] 구동 중인 매크로 확인. 엔진 강제 종료 프로세스 가동.")
            macro.kill()
            macro.dashboard("🛑 사용자에 의해 매크로 강제 종료 요청됨")
            
        else:
            if hasattr(macro, 'last_executed_scenario') and macro.last_executed_scenario:
                macro_data = macro.last_executed_scenario.get("macro")
                param_data = macro.last_executed_scenario.get("params")
                
                macro.dashboard(f"⌨️ REQUEST RUN LAST SCENARIO: {macro_data.get('description','')}")
                is_running_macro = True
                
                threading.Thread(
                    target=macro.run_macro_sequence, 
                    args=(macro_data, param_data), 
                    daemon=True
                ).start()
            else:
                macro.dashboard("⌨️ REQUEST RUN, NO LAST SCENARIO")
    finally:
        with app_threading_lock:
            is_processing_hotkey = False




def callback_finish_macro():
    global is_running_macro
    with app_threading_lock:
        is_running_macro = False
    macro.dashboard("✅ END MACRO THREAD")

class CommandRequest(BaseModel):
    command: str

@app.post("/api/command")
def api_command(request: CommandRequest):
    global is_running_macro
    user_command = request.command
    macro.dashboard(f"📩 macro /api/command '{user_command}'")

    try:
        import rules
        rule_hint = rules.pre_analyze_intent(user_command)
    except Exception as e:
        logger.error(f"⛈️ pre_analyze_intent Exception {str(e)}")
        return {"status": "error", "message": str(e)}

    all_scenarios = macro.load_all_scenarios()
    scenarios_desc = "".join([f"- '{s_id}': {s_data.get('description', '')}\n" for s_id, s_data in all_scenarios.items()])
    
    prompt = rules.PROMPT_TEMPLATE.format(
        scenarios_desc=scenarios_desc,
        has_math=rule_hint['has_math'],
        suggested_target=rule_hint['suggested_target']
    )

    try:
        response_data = ollama.chat(
            model=macro.MODEL_NAME,
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user_command}],
            options={"temperature": 0.0, "num_predict": 100},
            format="json"
        )
        response = response_data['message']['content'].strip()
        json_match = re.search(r"\{.*\}", response, re.DOTALL)
        if not json_match: raise ValueError("OLLAMA JSON 응답 파싱 에러")
        
        parsed_intent = json.loads(json_match.group(0))
        scenario_id = parsed_intent.get("scenario_id", "unknown")

        if scenario_id != "unknown" and scenario_id in all_scenarios:
            matched_macro = all_scenarios[scenario_id]
            params = {
                "num1": parsed_intent.get("num1"),
                "op": parsed_intent.get("op"),
                "num2": parsed_intent.get("num2")
            }

            with app_threading_lock:
                if is_running_macro:
                    macro.dashboard("⚠️ 이미 다른 매크로가 실행 중입니다.")
                    return {"status": "fail", "message": "이미 실행 중"}
                is_running_macro = True
                macro.last_executed_scenario = {"macro": matched_macro, "params": params}

            macro.start(matched_macro, params, callback_on_finish=callback_finish_macro)
            macro.dashboard(f"🤖 AI분석: {scenario_id}, PARAMETERS: {params}")
            return {"status": "success", "message": f"매크로 실행"}
            
        else:
            macro.dashboard(f"AI Mapping Fail -> 등록되지 않은 시나리오 ID (결과: {scenario_id})")
            return {"status": "fail", "message": "일치하는 매크로 시나리오가 없습니다."}
            
    except Exception as e:
        logger.error(f"⛈️ [Ollama 연산/파싱 중 크래시]: {str(e)}")
        return {"status": "error", "message": str(e)}
