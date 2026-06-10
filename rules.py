import re

# JSON 형식을 확실히 지키도록 가이드라인과 예시(Few-Shot)를 대폭 보강했습니다.
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