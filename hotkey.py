import logging
from pynput import keyboard

logger = logging.getLogger("Macro-Hotkey")

def register_hotkey_c_s_q(combination="ctrl+shift+q", callback=None):
    if callback is None:
        logger.warning("⚠️ 실행할 함수가 지정되지 않아 핫키를 등록하지 않습니다.")
        return

    parsed_key = combination
    if not parsed_key.startswith('<'):
        parsed_key = "+".join([f"<{k.strip()}>" if len(k.strip()) > 1 else k.strip() for k in combination.split("+")])

    hotkey_map = {
        parsed_key: callback
    }

    listener = keyboard.GlobalHotKeys(hotkey_map)
    listener.start()  

    logger.info(f"⌨️ 단축키 매핑 완료: [{combination}] -> 백그라운드 리스너 가동")