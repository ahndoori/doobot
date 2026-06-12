import logging
import os
import time
import subprocess
import threading
import sys
import asyncio
import pyautogui
import pygetwindow as gw
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

is_macro_running = False
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("WebCore")
app = FastAPI(title="Automation Console")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(BASE_DIR, "public"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "templates"), exist_ok=True)
app.mount("/public", StaticFiles(directory=os.path.join(BASE_DIR, "public")), name="public")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
IS_WINDOWS = sys.platform.startswith("win")
VENV_PYTHON = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe") if IS_WINDOWS else os.path.join(BASE_DIR, ".venv", "bin", "python")
VENV_UVICORN = os.path.join(BASE_DIR, ".venv", "Scripts", "uvicorn.exe") if IS_WINDOWS else os.path.join(BASE_DIR, ".venv", "bin", "uvicorn")

infra_context = {
    "macro_process": None,
    "voice_process": None,
    "initialized": False
}

web_logs = []
active_connections: List[WebSocket] = []

class LogPayload(BaseModel):
    message: str

async def add_web_log_and_broadcast(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted_log = f"[{timestamp}] {message}"
    print(formatted_log)
    web_logs.append(formatted_log)
    if len(web_logs) > 100:
        web_logs.pop(0)
    for connection in active_connections:
        try:
            await connection.send_json({"type": "new_log", "log": formatted_log})
        except Exception:
            pass

async def broadcast_infra_status():
    macro_alive = infra_context["macro_process"] is not None and infra_context["macro_process"].poll() is None
    voice_alive = infra_context["voice_process"] is not None and infra_context["voice_process"].poll() is None
    
    for connection in active_connections:
        try:
            await connection.send_json({
                "type": "infra_status",
                "macro_alive": macro_alive,
                "voice_alive": voice_alive
            })
        except Exception:
            pass

def log_stream_piper(pipe, prefix):
    try:
        with pipe:
            for line in iter(pipe.readline, ''):
                if line:
                    print(f"[{prefix}] {line.strip()}", flush=True)
    except Exception:
        pass

def spawn_daemon(target):
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    if target == "macro":
        proc = subprocess.Popen(
            [VENV_PYTHON, "-u", "-m", "uvicorn", "macro:app", "--port", "4445", "--log-level", "info"],
            cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8"
        )
        infra_context["macro_process"] = proc
        threading.Thread(target=log_stream_piper, args=(proc.stdout, "Macro-Core"), daemon=True).start()
        
    elif target == "voice":
        proc = subprocess.Popen(
            [VENV_PYTHON, "-u", "voice_listener.py"],
            cwd=BASE_DIR, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True, 
            encoding="utf-8",
            env=env
        )
        infra_context["voice_process"] = proc
        threading.Thread(target=log_stream_piper, args=(proc.stdout, "Voice-Client"), daemon=True).start()

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.post("/api/push-log")
async def push_log_endpoint(payload: LogPayload):
    await add_web_log_and_broadcast(payload.message)
    return {"status": "ok"}

@app.post("/api/infra/toggle/{target}")
async def toggle_infrastructure_status(target: str):
    if target not in ["macro", "voice"]:
        return {"status": "error", "message": "잘못된 타겟 컴포넌트"}
    
    if target == "macro":
        from app import macro_event  # (만약 app.py에 선언된 신호등을 가져온다면)
        
        if macro_event.is_set():  # is_macro_running 대신 신호등 확인
            macro_event.clear()   # 신호등 끄기 (중지 명령)
            await add_web_log_and_broadcast("🛑 [User Action] 매크로 중단 신호를 보냅니다.")
        else:
            macro_event.set()     # 신호등 켜기 (시작 명령)
            await add_web_log_and_broadcast("⚡ [User Action] 매크로 시작 신호를 보냅니다.")
            
        await broadcast_infra_status()
        return {"status": "ok"}


@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        await websocket.send_json({"type": "init_logs", "logs": web_logs})
        await broadcast_infra_status()
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)

@app.websocket("/ws/mouse-tracker")
async def websocket_mouse_tracker(websocket: WebSocket):
    await websocket.accept()
    logger.info("🔌 [Doobot] 마우스 트래커 웹소켓 연결 성공")
    
    last_x, last_y = -1, -1
    active_win = None
    win_title = "알 수 없는 창"
    win_left, win_top = 0, 0
    last_win_check_time = 0 
    
    try:
        while True:
            current_time = time.time()
            
            if current_time - last_win_check_time > 0.5:
                active_win = gw.getActiveWindow()
                if active_win is not None and active_win.title:
                    win_title = active_win.title
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
        logger.info("🔌 [Doobot] 마우스 트래커 웹소켓 연결 종료")
    except Exception as e:
        logger.error(f"❌ 트래커 오류: {e}")

@app.on_event("shutdown")
def cleanup_zombie_processes():
    for key in ["macro_process", "voice_process"]:
        proc = infra_context[key]
        if proc and proc.poll() is None:
            proc.terminate()