import sys
import logging
import re
import os
import time
import cv2
import numpy as np
import pyautogui
from PIL import ImageGrab

logger = logging.getLogger("Macro-Core.Rules")

PROMPT_TEMPLATE = (
    "You are a strict Windows automation router and parameter extractor.\n"
    "Your ONLY job is to output a raw JSON object based on the user's command and rules.\n\n"
    
    "Available Scenario IDs:\n{scenarios_desc}- 'unknown': when no scenario matches.\n\n"
    
    "RULE ENGINE HINTS (CRITICAL):\n"
    "- Is there a mathematical formula detected?: {has_math}\n"
    "- Recommended Target Application based on rules: {suggested_target}\n"
    "-> Rely heavily on the Recommended Target Application when picking the scenario_id.\n\n"
    
    "PARAMETER EXTRACTION RULES:\n"
    "- If a math operation or calculation is requested, extract 'num1', 'op', and 'num2'.\n"
    "- Normalize 'op' strictly to: '+', '-', '*', '/'. (Convert 'x', 'X', or '곱하기' to '*')\n\n"
    
    "EXAMPLE RESPONSE:\n"
    "User: 계산기로 33x22 계산\n"
    "{{\n"
    "  \"scenario_id\": \"windows_calc\",\n"
    "  \"delay_seconds\": 0,\n"
    "  \"num1\": \"33\",\n"
    "  \"op\": \"*\",\n"
    "  \"num2\": \"22\"\n"
    "}}\n\n"
    
    "CRITICAL RULE: Do NOT wrap the response in ```json ```. Do NOT include any introduction or conversational text.\n"
    "Output ONLY the valid raw JSON string matching this structure:\n"
    "{{\n"
    "  \"scenario_id\": \"string\",\n"
    "  \"delay_seconds\": 0,\n"
    "  \"num1\": \"string or null\",\n"
    "  \"op\": \"string or null\",\n"
    "  \"num2\": \"string or null\"\n"
    "}}\n"
)

PATTERNS = {
    "math_formula": r'\d+\s*(곱하기|더하기|빼기|나누기|\*|\+|\-|/|[xX])\s*\d+',
    "cell_coordinate": r'\b[a-zA-Z]+\d+\b',
}

def pre_analyze_intent(user_command: str) -> dict:
    hint_context = {"has_math": False, "suggested_target": "unknown"}
    if re.search(PATTERNS["math_formula"], user_command):
        hint_context["has_math"] = True
        
    is_excel_keyword = "엑셀" in user_command or "excel" in user_command or re.search(PATTERNS["cell_coordinate"], user_command)
    is_calc_keyword = "계산기" in user_command or "calc" in user_command

    if is_excel_keyword:
        hint_context["suggested_target"] = "excel"
    elif is_calc_keyword:
        hint_context["suggested_target"] = "calculator"
    elif hint_context["has_math"]:
        hint_context["suggested_target"] = "calculator"

    return hint_context


def check_youtube_shorts(step) -> bool:
    current_x, current_y = pyautogui.position()
    start_y = current_y - 3
    end_y = current_y + 3
    
    start_x = current_x - 500  
    end_x = current_x
    
    max_red_count = 0
    consecutive_drop_count = 0
    interval = step.get("delay", 0.5)
    
    timeout = 90
    start_time = time.time()

    last_red_count = -1
    no_change_count = 0
    
    while time.time() - start_time < timeout:
        screen = ImageGrab.grab()
        screen_np = np.array(screen)
        
        # 화면 경계 체크 안전장치
        if end_y >= screen_np.shape[0] or start_x < 0:
            return False
            
        current_red_count = 0
        
        # 2. X축을 돌면서 지정된 Y축 범위(두께) 전체를 스캔합니다.
        for x in range(start_x, end_x):
            if x >= screen_np.shape[1]:
                continue
                
            # 해당 X 좌표에서 위아래 두께 공간에 빨간색 선이 걸쳐져 있는지 확인
            is_red_pixel_found = False
            for y in range(start_y, end_y):
                pixel = screen_np[y, x][:3]
                c1, g, c2 = pixel[0], pixel[1], pixel[2]
                
                # RGB/BGR 채널 오차 방어: 첫 번째나 세 번째 채널 중 하나가 강한 원색 빨강인 경우
                if (c1 > 180 or c2 > 180) and g < 50:
                    is_red_pixel_found = True
                    break # 이 열(X)에는 빨간색이 존재하므로 브레이크
            
            if is_red_pixel_found:
                current_red_count += 1
                
        # SHAKE MOUSE (바가 사라졌을 때 방어)
        if current_red_count == 0 and max_red_count > 15:
            pyautogui.moveTo(current_x - 10, current_y, duration=0.05)
            pyautogui.moveTo(current_x, current_y, duration=0.05)
            time.sleep(interval)
            continue
            
        if current_red_count > 0 and current_red_count == last_red_count:
            # 영상이 다 안 끝났는데(current_red_count가 max_red_count보다 작음) 값이 멈췄을 때만 정지로 인정할지, 
            # 혹은 끝까지 찼는데 다음으로 안 넘어가고 버벅일 때도 포함할지 안전하게 체크
            no_change_count += 1
            if no_change_count >= 5:
                print("⚠️ 재생 멈춤(일시정지/버퍼링) 감지 ➡️ 스페이스바 입력")
                pyautogui.moveTo(current_x,current_y-100, duration=0.5)
                pyautogui.click()
                pyautogui.moveTo(current_x,current_y,duration=0.5)
                no_change_count = 0  # 카운트 초기화
        else:
            no_change_count = 0
        last_red_count = current_red_count

        print('Y',start_y, 'RED',current_red_count, 'MAX', max_red_count)

        if current_red_count > max_red_count:
            max_red_count = current_red_count
            consecutive_drop_count = 0

        elif current_red_count < (max_red_count - 30) and max_red_count > 50:
            consecutive_drop_count += 1
            if consecutive_drop_count >= 2:
                print("✨ 루프 감지 완료! 다음 비디오로 이동합니다.")
                return True
                
        time.sleep(interval)
        
    return False