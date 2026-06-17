import threading
import logging
from pynput import keyboard  # pynput의 keyboard 모듈 임포트

logger = logging.getLogger("Macro-Hotkey")

def init_hotkeys():
    # ⚠️ 순환 참조(Circular Import) 방지를 위해 함수 내부에서 import 합니다.
    import macro 

    def handle_hotkey_trigger():
        # macro 모듈 객체의 속성을 직접 제어합니다.
        with macro.threading_lock:
            if macro.is_running:
                macro.dashboard("⌨️ REQUEST STOP")
                macro.stop_requested = True
            else:
                if macro.last_executed_scenario:
                    macro_data = macro.last_executed_scenario.get("macro")
                    param_data = macro.last_executed_scenario.get("params")
                    
                    macro.dashboard(f"⌨️ REQUEST RUN LAST SCENARIO: {macro_data.get('description','')}")
                    macro.is_running = True
                    macro.stop_requested = False
                    
                    threading.Thread(
                        target=macro.run_macro_sequence, 
                        args=(macro_data, param_data), 
                        daemon=True
                    ).start()
                else:
                    macro.dashboard("⌨️ REQUEST RUN, NO LAST SCENARIO")

    # 1. 단축키와 실행할 함수를 딕셔너리로 매핑합니다. (pynput 포맷에 맞춤)
    # pynput에서는 조합키를 '<ctrl>+<shift>+q' 와 같은 형태로 표현합니다.
    hotkey_map = {
        '<ctrl>+<shift>+q': handle_hotkey_trigger
    }

    # 2. 리스너를 생성하고 백그라운드 스레드로 시작합니다.
    listener = keyboard.GlobalHotKeys(hotkey_map)
    listener.start()  # non-blocking 방식으로 백그라운드에서 계속 대기함

    logger.info("⌨️ 단축키 매핑 완료: [Ctrl+Shift+Q] -> hotkey.py 완전 분리 (pynput)")