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
            #[VENV_UVICORN, "macro:app", "--port", "4445"],
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
    
    key = f"{target}_process"
    proc = infra_context[key]
    is_alive = proc is not None and proc.poll() is None

    if is_alive:
        proc.terminate()
        try:
            proc.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            proc.kill()
        infra_context[key] = None
        await add_web_log_and_broadcast(f"🛑 [User Action] {target} 데몬을 중단합니다")
    else:
        await add_web_log_and_broadcast(f"⚡ [User Action] {target} 데몬을 기동합니다")
        spawn_daemon(target)
        await asyncio.sleep(0.5)
        
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
    
    # 리소스 최적화를 위한 상태 저장 변수들
    last_x, last_y = -1, -1
    active_win = None
    win_title = "알 수 없는 창"
    win_left, win_top = 0, 0
    
    # 창 정보 갱신 타이머 (매번 조회하지 않고 0.5초에 한 번만 갱신)
    last_win_check_time = 0 
    
    try:
        while True:
            current_time = time.time()
            
            # 1. [최적화] 활성화된 창 정보는 0.5초마다 한 번씩만 새로고침
            if current_time - last_win_check_time > 0.5:
                active_win = gw.getActiveWindow()
                if active_win is not None and active_win.title:
                    win_title = active_win.title
                    win_left = active_win.left
                    win_top = active_win.top
                last_win_check_time = current_time
            
            # 2. 현재 마우스 절대 좌표 구하기 (이 연산은 매우 가볍습니다)
            abs_x, abs_y = pyautogui.position()
            
            # 3. [최적화] 마우스 위치가 이전과 '동일'하면 아무것도 하지 않고 패스!
            if abs_x == last_x and abs_y == last_y:
                await asyncio.sleep(0.03) # 0.03초 쉬고 다시 체크 (약 30FPS)
                continue
            
            # 마우스가 움직였다면 이전 좌표 업데이트
            last_x, last_y = abs_x, abs_y
            
            # 4. 상대 좌표 계산
            rel_x = abs_x - win_left
            rel_y = abs_y - win_top
            
            # 5. 전송 데이터 조립 및 전송
            data = {
                "window_title": win_title,
                "coords": f"{rel_x}x{rel_y}",
                "abs_coords": f"{abs_x}x{abs_y}"
            }
            await websocket.send_json(data)
            
            # 대기 시간 조정 (0.03초 = 초당 최대 33번 전송, 체감상 완전히 실시간)
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