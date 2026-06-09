# server.py
import subprocess
import time
import sys
import os
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:
    VENV_PYTHON = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
    VENV_UVICORN = os.path.join(BASE_DIR, ".venv", "Scripts", "uvicorn.exe")
else:
    VENV_PYTHON = os.path.join(BASE_DIR, ".venv", "bin", "python")
    VENV_UVICORN = os.path.join(BASE_DIR, ".venv", "bin", "uvicorn")

print("=========================================================")
print(f"🔥 [Framework Launcher] 크로스오버 멀티 프로세싱 엔진 시동 (OS: {sys.platform})")
print("=========================================================")

processes = []

def log_stream_piper(pipe, prefix):
    """하위 프로세스의 터미널 출력을 실시간으로 탈취해 메인 터미널에 프린트하는 워커"""
    try:
        with pipe:
            for line in iter(pipe.readline, ''):
                if line:
                    print(f"[{prefix}] {line.strip()}")
    except Exception:
        pass

try:
    # 1. Web UI Dashboard Hub Server (Port: 4444)
    print("📦 [1/3] 웹 대시보드 허브 서버 가동 [Port 4444]...")
    app_proc = subprocess.Popen(
        [VENV_UVICORN, "app:app", "--port", "4444", "--reload"],
        cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8"
    )
    processes.append(app_proc)
    threading.Thread(target=log_stream_piper, args=(app_proc.stdout, "Web-Hub"), daemon=True).start()

    time.sleep(1.5)

    # 2. Macro & Ollama Core Engine (Port: 4445)
    print("🤖 [2/3] 매크로 & 로컬 LLM 코어 엔진 가동 [Port 4445]...")
    macro_proc = subprocess.Popen(
        [VENV_UVICORN, "macro:app", "--port", "4445"],
        cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8"
    )
    processes.append(macro_proc)
    threading.Thread(target=log_stream_piper, args=(macro_proc.stdout, "Macro-Core"), daemon=True).start()

    time.sleep(1.5)

    # 3. Voice Listener Daemon Client
    print("🎤 [3/3] 백그라운드 오디오 음성 모니터링 데몬 가동...")
    voice_proc = subprocess.Popen(
        [VENV_PYTHON, "voice_listener.py"],
        cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8"
    )
    processes.append(voice_proc)
    threading.Thread(target=log_stream_piper, args=(voice_proc.stdout, "Voice-Client"), daemon=True).start()

    print("\n🚀 [All Components Online] 인프라 정렬 완료.")
    print("🔗 대시보드 웹 주소: http://localhost:4444")
    print("🛑 종료: Ctrl + C\n")

    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("\n🛑 종료 시그널 감지. 모든 좀비 프로세스 자원 회수 진입...")
    for proc in processes:
        if proc.poll() is None:
            proc.terminate()
    print("✨ 자원 릴리즈 완료.")