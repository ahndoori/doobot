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

infra_context = {
    "macro_process": None,
    "voice_process": None,
    "initialized": False
}

dashboard_history = []
active_connections: List[WebSocket] = []

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