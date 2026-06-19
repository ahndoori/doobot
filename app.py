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
import pynput
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

import macro
import input

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_PROCESS = 'voice_process'
#os.makedirs(os.path.join(BASE_DIR, "public"), exist_ok=True)
#os.makedirs(os.path.join(BASE_DIR, "templates"), exist_ok=True)

is_running_macro = False
is_processing_hotkey = False
app_threading_lock = threading.Lock()
logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(message)s")
logger=logging.getLogger("WebCore")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
VENV_PYTHON = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe") if sys.platform.startswith("win") else os.path.join(BASE_DIR, ".venv", "bin", "python")
infra_context = {
    "macro_process": None,
    VOICE_PROCESS: None,
    "initialized": False
}

dashboard_history = []
active_connections: List[WebSocket] = []

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    ctx = {
        "lock": app_threading_lock,
        "macro": macro,  # 전역 macro 객체
        "is_running_macro": lambda: is_running_macro,
        "is_processing_hotkey": lambda: is_processing_hotkey,
        "set_running_macro": _set_running_macro,
        "set_processing_hotkey": _set_processing_hotkey
    }
    try:
        input.register_hotkey(combination="ctrl+shift+q", ctx=ctx)
        logger.info("🔑 단축키 시스템 연동 및 핸들러 이관 완료")
    except Exception as e:
        logger.error(f"단축키 리스너 실행 중 오류 발생: {e}")
    yield

def _set_running_macro(val: bool):
    global is_running_macro
    is_running_macro = val

def _set_processing_hotkey(val: bool):
    global is_processing_hotkey
    is_processing_hotkey = val

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
        infra_context[VOICE_PROCESS] is not None 
        and infra_context[VOICE_PROCESS].poll() is None
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

@app.get("/",response_class=HTMLResponse)
async def fastapi_root(request:Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.on_event("shutdown")
def fastapi_shutdown():
    if infra_context[VOICE_PROCESS] is not None:
        proc = infra_context[VOICE_PROCESS]
        if proc.poll() is None:
            logger.info("☀️ cleanup_zombie_processes: terminating voice_process")
            proc.terminate()

@app.post("/api/push-log")
async def fastapi_push_log(payload: dict):
    await add_web_log_and_broadcast(payload.get("message", ""))
    return {"status": "ok"}

@app.post("/api/daemon/voice")
async def fastapi_daemon_voice():
    proc = infra_context.get(VOICE_PROCESS)
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=1.0) 
        except subprocess.TimeoutExpired:
            logger.warning("⚠️ VoiceListener가 terminate 요청에 응답안함, KILL")
            proc.kill()
            proc.wait()
        except Exception as e:
            logger.error(f"⛈️ VoiceListener 종료 중 예외 발생: {e}")
        finally:
            if hasattr(proc, 'close'):
                proc.close()
        infra_context[VOICE_PROCESS] = None
        await add_web_log_and_broadcast("🛬 stop daemon VoiceListener")
    else:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [VENV_PYTHON, "-u", "voice.py"],
            cwd=BASE_DIR, 
            env=env
        )
        infra_context[VOICE_PROCESS] = proc
        await add_web_log_and_broadcast("🛫 start daemon VoiceListener")
        await asyncio.sleep(0.5)
    await broadcast_infra_status()
    return {"status": "ok"}

@app.websocket("/ws/dashboard")
async def fastapi_ws_endpoint(websocket: WebSocket):
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
async def fastapi_ws_mouse(websocket: WebSocket):
    await websocket.accept()
    logger.info("☀️ /ws/mouse")
    last_x, last_y = -1, -1
    win_title="UNKNOWN"
    win_left, win_top = 0, 0
    last_win_check_time = 0 
    try:
        while True:
            current_time = time.time()
            if current_time - last_win_check_time > 0.5:
                active_win = pwc.getActiveWindow()
                if active_win is not None:
                    win_title = active_win.title if hasattr(active_win, 'title') else "UNKNOWN"
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



@app.websocket("/ws/key")
async def fastapi_ws_key(websocket: WebSocket):
    """
    키보드 입력과 마우스 클릭(좌/우클릭) 이벤트를 하나의 웹소켓으로 통합 전송합니다.
    (마우스 커서 움직임은 추적하지 않아 부하가 매우 적습니다.)
    """
    await websocket.accept()
    logger.info("☀️ /ws/key (키보드 + 마우스 클릭) 연결 성공")
    
    # 두 리스너의 이벤트를 한 곳으로 모을 통합 비동기 큐
    loop = asyncio.get_running_loop()
    event_queue = asyncio.Queue()

    # 1. 키보드 입력 콜백
    def on_press(key):
        try:
            key_data = key.char if hasattr(key, 'char') and key.char is not None else str(key)
        except Exception:
            key_data = str(key)
            
        data = {"source":"","action": "pressed", "value": key_data}
        loop.call_soon_threadsafe(event_queue.put_nowait, data)
    def on_click(x, y, button, pressed):
        button_name = button.name if hasattr(button, 'name') else str(button)
        data = {
            "source": "m",
            "action": "pressed" if pressed else "released",
            "value": button_name,
            "abs_coords": f"{x}x{y}"
        }
        loop.call_soon_threadsafe(event_queue.put_nowait, data)
    key_listener = pynput.keyboard.Listener(on_press=on_press)
    mouse_listener = pynput.mouse.Listener(on_click=on_click)
    key_listener.start()
    mouse_listener.start()
    try:
        #win_title = "UNKNOWN"
        #win_left, win_top = 0, 0
        while True:
            event_data = await event_queue.get()

            '''
            active_win = pwc.getActiveWindow()
            if active_win is not None:
                win_title = active_win.title if hasattr(active_win, 'title') else "UNKNOWN"
                win_left = active_win.left
                win_top = active_win.top
            '''

            # 공통 데이터 포맷 가공
            payload = {
                "type": "input_event",
                "source": event_data["source"],
                "action": event_data["action"],
                "value": event_data["value"],
                #"window_title": win_title
            }
            '''
            if event_data["source"] == "m":
                abs_x, abs_y = map(int, event_data["abs_coords"].split('x'))
                rel_x = abs_x - win_left
                rel_y = abs_y - win_top
                payload["coords"] = f"{rel_x}x{rel_y}"
                payload["abs_coords"] = event_data["abs_coords"]
            '''
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        logger.info("❌ /ws/key 웹소켓 연결 종료")
    except Exception as e:
        logger.error(f"⛈️ websocket_combined_tracker 예외 발생: {e}")
    finally:
        # 6. 종료 시 두 리스너 스레드 모두 깔끔하게 클로징
        key_listener.stop()
        mouse_listener.stop()




def callback_finish_macro():
    global is_running_macro
    with app_threading_lock:
        is_running_macro = False
    macro.dashboard("✅ END MACRO THREAD")

class CommandRequest(BaseModel):
    command: str

@app.post("/api/command")
def fastapi_command(request: CommandRequest):
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
