import re

# 1. 관리할 정규표현식 패턴들 한 곳에 모으기
PATTERNS = {
    "math_formula": r'\d+\s*(곱하기|더하기|빼기|나누기|\*|\+|\-|/)\s*\d+',
    "cell_coordinate": r'[a-zA-Z]+\d+',  # A1, B12 같은 엑셀 셀 좌표 패턴
}

def pre_analyze_intent(user_command: str) -> dict:
    """
    사용자 명령어를 LLM에 던지기 전에 규칙 기반으로 1차 분석하여 
    LLM의 프롬프트에 힌트로 주입할 컨텍스트 데이터를 생성합니다.
    """
    # 기본 컨텍스트 상태
    hint_context = {
        "has_math": False,
        "suggested_target": "unknown"
    }
    
    # 1. 수식 존재 여부 체크
    if re.search(PATTERNS["math_formula"], user_command):
        hint_context["has_math"] = True
        
    # 2. 명시적 키워드 및 패턴 매칭을 통한 타겟 앱 추론
    is_excel = "엑셀" in user_command or "excel" in user_command or re.search(PATTERNS["cell_coordinate"], user_command)
    is_calc = "계산기" in user_command or "calc" in user_command

    if is_excel:
        hint_context["suggested_target"] = "excel"
    elif is_calc:
        hint_context["suggested_target"] = "calculator"
    elif hint_context["has_math"]:
        # 앱 언급은 없으나 수식이 있으면 계산기를 기본값으로 제안
        hint_context["suggested_target"] = "calculator"
        
    return hint_context