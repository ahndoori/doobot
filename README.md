## 🤖 Dubot AI Automation Pipeline

사용자의 음성을 인식하고 화면을 분석하여 매크로를 수행하는 반자동 AI 에이전트



---

 **Data Flow Summary**  
 `Vosk` 오디오 스트림 ➔ 텍스트 ➔ `Ollama` 추론 ➔ JSON 매크로 명령 ➔ `EasyOCR` 화면 스캔 ➔ 타겟 X, Y 좌표 추출 ➔ `PyAutoGUI` 마우스 제어 ➔ `TTS` 음성 출력

---

[ 사용자 음성 ]  
▼ (Vosk / Whisper)  
[ 음성 인식 (STT) ] ➔ 오디오를 텍스트 데이터로 변환  
▼ (Ollama / Llama-3)  
[ 자연어 처리 (LLM) ] ➔ 의도 파악 및 Structured JSON 구조화  
▼ (PyAutoGUI / Pillow)  
[ 화면 캡처 ] ➔ 실시간 스크린샷 버퍼 생성  
▼ (EasyOCR / Tesseract / OpenCV)  
[ 비전/한글 인식 ] ➔ 화면 내 텍스트 및 오브젝트 X, Y 절대 좌표 추출  
▼ (PyAutoGUI / ADB)  
[ OS 매크로 작동 ] ➔ 마우스 클릭 및 키보드 제어 완료  
  
  
---

### 1. Speech-to-Text (음성 인식)
* **라이브러리:** `Vosk`, `Whisper`
* **역할:** 로컬 환경에서 가볍고 빠르게 유저의 음성 스트림을 텍스트로 디코딩. 레이턴시 최소화를 위해 온디바이스(On-device) 엔진

### 2. Brain & LLM (명령 판독 및 라우팅)
* **라이브러리:** `Ollama` (`Llama-3` / `EEVE-Korean`), `Pydantic`
* **역할:** 로컬 LLM을 통해 한글 문맥을 분석하고 유저의 실행 의도(Intent) 파악. `Pydantic`을 결합하여 즉시 파싱 가능한 **Structured JSON** 형태로 명령 구조화

### 3. Vision & Optical Recognition (화면 분석)
* **라이브러리:** `EasyOCR`, `Tesseract`, `OpenCV`, `Pillow (PIL)`
* **역할:** `Pillow`로 화면을 캡처한 뒤, `EasyOCR`로 화면 속 한글 텍스트의 Boundary Box와 좌표 추출. 정적 UI 요소는 `OpenCV` 템플릿 매칭으로 보정

### 4. Automation & Macro Engine (OS 제어 및 출력)
* **라이브러리:** `PyAutoGUI`, `Pure-Python-ADB`, `Kokoro-82M`
* **역할:** 추출된 X, Y 좌표를 바탕으로 `PyAutoGUI` 또는 `ADB`가 마우스 클릭 및 키보드 입력 제어, 실행 결과는 경량 로컬 TTS인 `Kokoro-82M`을 통해 음성 피드백 출력
