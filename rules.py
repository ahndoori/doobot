import sys
import logging
import re
import os
import time
import cv2
import numpy as np
import pyautogui
import screenshot
from PIL import Image, ImageGrab

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


def check_youtube_shorts(step,stop_requested=None) -> bool:
    current_x, current_y = pyautogui.position()
    pyautogui.screenshot().save(os.path.join(os.path.dirname(os.path.abspath(__file__)),"debug.png"))
    print(current_x, current_y)
    
    start_y = current_y - 5
    end_y = current_y + 5
    start_x = current_x - 450
    end_x = current_x
    
    max_red_count = 0
    consecutive_drop_count = 0
    interval = step.get("delay", 0.5)
    
    timeout = 90
    start_time = time.time()

    last_red_count = -1
    no_change_count = 0
    
    # 디버깅: 스캔 시작 전 한 번만 이미지를 캡처하여 저장
    context_np = screenshot.screen_array()
    if 0 <= start_y < context_np.shape[0] and 0 <= end_y < context_np.shape[0] and \
    0 <= start_x < context_np.shape[1] and 0 <= end_x < context_np.shape[1]:
        crop_np = context_np[start_y:end_y, start_x:end_x]
        if crop_np.size > 0:
            Image.fromarray(crop_np).save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug2.png"))
        else:
            print("⚠️ 디버깅 크롭 이미지 크기가 0입니다.")
    else:
         print(f"⚠️ 디버깅 크롭 좌표가 이미지 범위를 벗어났습니다: Y({start_y}:{end_y}), X({start_x}:{end_x}), Shape({context_np.shape})")

    while time.time() - start_time < timeout:
        if stop_requested and stop_requested(): return False
        screen_np = screenshot.screen_array(resample=Image.Resampling.NEAREST)

        if end_y >= screen_np.shape[0] or start_x < 0:
            return False
        current_red_count = 0
        for x in range(start_x, end_x):
            if x >= screen_np.shape[1]:
                continue
            is_red_pixel_found = False
            for y in range(start_y, end_y):
                pixel = screen_np[y, x][:3]
                r, g, b = pixel[0], pixel[1], pixel[2]
                if r > 120 and (int(r) - int(g) > 40) and (int(r) - int(b) > 30):
                    is_red_pixel_found = True
                    break
                #c1, g, c2 = pixel[0], pixel[1], pixel[2]
                #if (c1 > 180 or c2 > 180) and g < 50:
                #    is_red_pixel_found = True
                #    break # 이 열(X)에는 빨간색이 존재하므로 브레이크
            
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
