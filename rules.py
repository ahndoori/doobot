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


def BACKUP_check_youtube_shorts(step,stop_requested=None) -> bool:
    current_x, current_y = pyautogui.position()
    start_y = current_y - 6
    end_y = current_y + 6
    start_x = current_x - 500
    #start_x = 0
    end_x = current_x
    
    max_red_count = 0
    consecutive_drop_count = 0
    interval = step.get("delay", 0.5)
    
    timeout = 90
    start_time = time.time()

    last_red_count = -1
    no_change_count = 0
    
    while time.time() - start_time < timeout:
        if stop_requested and stop_requested(): return False
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

        if current_red_count == last_red_count: #current_red_count > 0 and
            no_change_count += 1
            if no_change_count >= 5:
                print("✨ STOP DETECTED")
                pyautogui.moveTo(current_x-50,current_y-150, duration=0.5)
                pyautogui.click()
                pyautogui.moveTo(current_x,current_y,duration=0.5)
                no_change_count = 0
        else:
            no_change_count = 0
        last_red_count = current_red_count

        print('YOUTUBE SHORTS PROGRESS Y:',start_y, ', PREV-RED:', max_red_count, ', CURRENT-RED:',current_red_count)

        if current_red_count > max_red_count:
            max_red_count = current_red_count
            consecutive_drop_count = 0

        elif current_red_count < (max_red_count - 30) and max_red_count > 50:
            consecutive_drop_count += 1
            if consecutive_drop_count >= 2:
                print("✨ LOOP DETECTED")
                return True

        time.sleep(interval)        
    return False

def check_youtube_shorts(step, stop_requested=None) -> bool:
    # 1. 마우스의 현재 순수한 '논리 좌표'를 백업해 둡니다. (마우스 이동용)
    logical_x, logical_y = pyautogui.position()
    
    # 2. 맥북 해상도 배율을 구합니다. (보통 2.0)
    screen_w, screen_h = pyautogui.size()
    temp_screen = np.array(ImageGrab.grab()) # 혹은 pyautogui.screenshot()
    SCALE_X = temp_screen.shape[1] / screen_w
    SCALE_Y = temp_screen.shape[0] / screen_h
    
    # 3. 픽셀 배열(screen_np)을 지칭할 때는 2배 튀겨진 '물리 좌표'를 사용합니다.
    # logical_y가 792라면, current_y는 실제 빨간 바가 위치한 물리 픽셀인 1584가 됩니다.
    current_x = int(logical_x * SCALE_X)
    current_y = int(logical_y * SCALE_Y)

    # 4. 물리 좌표 기준으로 상하 두께 오프셋 지정 (물리 픽셀 기준이므로 두께도 6픽셀 정도로 넉넉히)
    start_y = current_y - 6
    end_y = current_y + 6
    
    # 5. 왼쪽으로 500픽셀 검사하는 것도 물리 픽셀 기준으로 2배 늘려줍니다 (500 * 2 = 1000픽셀)
    scan_width = int(500 * SCALE_X)
    start_x = current_x - scan_width
    end_x = current_x
    
    max_red_count = 0
    consecutive_drop_count = 0
    interval = step.get("delay", 0.5)
    
    timeout = 90
    start_time = time.time()

    last_red_count = -1
    no_change_count = 0
    
    while time.time() - start_time < timeout:
        if stop_requested and stop_requested(): return False
        
        # 캡처본 가져오기
        screen = ImageGrab.grab()
        screen_np = np.array(screen)
        
        # 화면 경계 체크 안전장치 (물리 해상도 크기 기준)
        if end_y >= screen_np.shape[0] or start_x < 0:
            return False
            
        current_red_count = 0
        
        # X축 돌면서 물리 픽셀 레이어 스캔
        for x in range(start_x, end_x):
            if x >= screen_np.shape[1]:
                continue
                
            is_red_pixel_found = False
            for y in range(start_y, end_y):
                pixel = screen_np[y, x][:3]
                
                # RGB / BGR 둘 다 커버하는 무적 필터 (첫 번째나 세 번째가 빨갛고, 초록은 없어야 함)
                c1, g, c2 = pixel[0], pixel[1], pixel[2]
                if (c1 > 170 or c2 > 170) and g < 60:
                    is_red_pixel_found = True
                    break 
            
            if is_red_pixel_found:
                current_red_count += 1

        # 멈춤 감지 시 동작 구역
        if current_red_count == last_red_count: 
            no_change_count += 1
            if no_change_count >= 5:
                print("✨ STOP DETECTED")
                # 🎯 마우스 이동은 철저하게 보정 전 오리지널 'logical' 좌표계 기준으로 명령!
                pyautogui.moveTo(logical_x - 50, logical_y - 150, duration=0.5)
                pyautogui.click()
                pyautogui.moveTo(logical_x, logical_y, duration=0.5)
                no_change_count = 0
        else:
            no_change_count = 0
        last_red_count = current_red_count

        # 792층이 아니라 진짜 픽셀이 있는 1584층(예시)이 찍히는 것을 로그로 확인 가능합니다.
        print('YOUTUBE SHORTS PROGRESS Y:', start_y, ', PREV-RED:', max_red_count, ', CURRENT-RED:', current_red_count)

        if current_red_count > max_red_count:
            max_red_count = current_red_count
            consecutive_drop_count = 0

        # 드롭 판정 기준수치도 물리 픽셀 카운트에 맞게 배율 반영
        drop_threshold = int(30 * SCALE_X)
        min_red_threshold = int(50 * SCALE_X)

        if current_red_count < (max_red_count - drop_threshold) and max_red_count > min_red_threshold:
            consecutive_drop_count += 1
            if consecutive_drop_count >= 2:
                print("✨ LOOP DETECTED")
                return True

        time.sleep(interval)        
    return False