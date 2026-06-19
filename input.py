import logging
import threading
from pynput import keyboard

logger = logging.getLogger("Macro-Hotkey")

def register_hotkey(combination="ctrl+shift+q", ctx=None):
    """
    단축키 리스너를 등록합니다.
    ctx: app.py의 전역 변수 및 상태 제어용 객체들을 담은 딕셔너리
    """
    if ctx is None:
        logger.warning("⚠️ 컨텍스트(ctx)가 지정되지 않아 핫키를 등록하지 않습니다.")
        return

    parsed_key = combination
    if not parsed_key.startswith('<'):
        parsed_key = "+".join([f"<{k.strip()}>" if len(k.strip()) > 1 else k.strip() for k in combination.split("+")])

    # 핫키 맵핑 시, 래핑된 핸들러를 연결
    hotkey_map = {
        parsed_key: lambda: handler_hotkey_c_s_q(ctx)
    }

    listener = keyboard.GlobalHotKeys(hotkey_map)
    listener.start()  
    logger.info(f"⌨️ 단축키 매핑 완료: [{combination}] -> 백그라운드 리스너 가동")


def handler_hotkey_c_s_q(ctx):
    """app.py에서 이관된 단축키 핵심 제어 로직"""
    print('handler_hotkey_c_s_q')
    
    lock = ctx["lock"]
    macro = ctx["macro"]
    
    # 중복 실행 방지 락 체크
    with lock:
        if ctx["is_processing_hotkey"]():
            return
        ctx["set_processing_hotkey"](True)
        
    try:
        if ctx["is_running_macro"]():
            ctx["set_running_macro"](False)
            logger.info("🚨 [App 승인] 구동 중인 매크로 확인. 엔진 강제 종료 프로세스 가동.")
            macro.kill()
            macro.dashboard("🛑 사용자에 의해 매크로 강제 종료 요청됨")
            
        else:
            if hasattr(macro, 'last_executed_scenario') and macro.last_executed_scenario:
                macro_data = macro.last_executed_scenario.get("macro")
                param_data = macro.last_executed_scenario.get("params")
                
                macro.dashboard(f"⌨️ REQUEST RUN LAST SCENARIO: {macro_data.get('description','')}")
                ctx["set_running_macro"](True)
                
                threading.Thread(
                    target=macro.run_macro_sequence, 
                    args=(macro_data, param_data), 
                    daemon=True
                ).start()
            else:
                macro.dashboard("⌨️ REQUEST RUN, NO LAST SCENARIO")
    finally:
        with lock:
            ctx["set_processing_hotkey"](False)