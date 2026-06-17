// [설정] 서버 주소 정의
const SERVER_HOST = window.location.host;
const MACRO_CORE_URL = "http://127.0.0.1:4445/api/command";

// 웹소켓 인스턴스를 보관할 전역 변수 (재연결을 위해 let 사용)
let logSocket = null;
let mouseSocket = null;

function log(msg) {
	const logBox = document.getElementById("log-box");
    const timestamp = new Date().toLocaleString('en-CA', { hour12: false }).replace(',', '');
    const logLine = document.createElement("div");
    logLine.textContent = `[${timestamp}] ${msg}`;
    logBox.appendChild(logLine);
    scrollDown(logBox);
}

function connectLogWebSocket() {
    const logBox = document.getElementById("log-box");
    const btnMacro = document.getElementById("btn-macro");
    const btnVoice = document.getElementById("btn-voice");

	if (typeof logSocket !== "undefined" && logSocket && 
       (logSocket.readyState === WebSocket.CONNECTING || logSocket.readyState === WebSocket.OPEN)) {
        log("ℹ️ DASHBOARD SOCKET IS ALREADY CONNECTED");
        return;
    }
    if (typeof logSocket !== "undefined" && logSocket) logSocket.close();

    logSocket = new WebSocket(`ws://${SERVER_HOST}/ws/dashboard`);
    logSocket.onopen = () => {
        log("🚀 DASHBOARD SOCKET OPENED");
    };

    logSocket.onmessage = (event) => {
        const data = jsonParseSafe(event.data);
        if (!data) return;

        if (data.type === "init_logs") {
            logBox.innerHTML = data.logs.map(log => `<div>${log}</div>`).join("");
            scrollDown(logBox);
        } else if (data.type === "new_log") {
            const logLine = document.createElement("div");
            logLine.textContent = data.log;
            logBox.appendChild(logLine);
            scrollDown(logBox);
        } else if (data.type === "infra_status") {
            updateButtonStatus(btnMacro, data.macro_alive);
            updateButtonStatus(btnVoice, data.voice_alive);
        }
    };

    logSocket.onclose = () => {
        log("⚠️ DASHBOARD SOCKET CLOSED");
        setTimeout(connectLogWebSocket,3000);
    };
    logSocket.onerror = (err) => {
		log(`👤 DASHBOARD SOCKET ERROR: ${err}`);
        logSocket.close();
    };
}

function connectMouseWebSocket(){
	if(typeof mouseSocket !== "undefined" && mouseSocket && 
       (mouseSocket.readyState === WebSocket.CONNECTING || mouseSocket.readyState === WebSocket.OPEN)) {
        log("ℹ️ MOUSE SOCKET IS ALREADY CONNECTED");
        return;
    }
    if (typeof mouseSocket !== "undefined" && mouseSocket) mouseSocket.close();

    //const statusEl = document.getElementById("connection-status");
	const btnTracker=document.getElementById("btn-tracker");
    mouseSocket = new WebSocket(`ws://${SERVER_HOST}/ws/mouse`);

    mouseSocket.onopen = () => {
		log("🚀 MOUSE SOCKET OPENED");
		updateButtonStatus(btnTracker,true);
    };

    mouseSocket.onmessage = (event) => {
        const data = jsonParseSafe(event.data);
        if (!data) return;
        const winTitle = document.getElementById("window-title");
        const relCoords = document.getElementById("relative-coords");
        const absCoords = document.getElementById("absolute-coords");
        if (winTitle) winTitle.textContent = data.window_title;
        if (relCoords) relCoords.textContent = data.coords;
        if (absCoords) absCoords.textContent = data.abs_coords;
    };

    mouseSocket.onclose = () => {
		updateButtonStatus(btnTracker,false);
		log("⚠️ MOUSE SOCKET CLOSED");
        //setTimeout(connectMouseWebSocket, 2000);
    };

    mouseSocket.onerror = (err) => {
        log(`👤 MOUSE SOCKET ERROR: ${err}`);
        mouseSocket.close();
    };
}

/**
 * 3. 매크로 코어 명령 전송 함수
 */
async function sendNaturalCommand() {
    const cmdInput = document.getElementById("cmd-input");
    const commandText = cmdInput.value.trim();
    
    if (!commandText) return;
    cmdInput.value = "";
    
    //log(`👤 [User Input] ➡️ ${commandText}`);
    
    try {
        const response = await fetch(MACRO_CORE_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command: commandText })
        });
        const result = await response.json();
        if (result.status !== "success") {
            log(`⚠️ [Macro Link] 코어 응답 실패: ${result.message}`);
        }
    } catch (err) {
        log(`❌ [Network Error] 매크로 코어(4445) 서버가 꺼져있거나 통신이 불가능합니다.`);
    }
}

async function toggleInfrastructure(target) {
    try {
        await fetch(`/api/infra/toggle/${target}`, { method: "POST" });
    } catch (err) {
        console.error("인프라 토글 통신 실패:", err);
    }
}

function updateButtonStatus(button, isAlive) {
    if (!button) return;
    const indicator = button.querySelector('span');
    if (!indicator) return;
    if (isAlive) {
        indicator.classList.remove("led-red");
        indicator.classList.add("led-green");
    } else {
        indicator.classList.remove("led-green");
        indicator.classList.add("led-red");
    }
}

function jsonParseSafe(text) {
    try { return JSON.parse(text); } catch (e) { return null; }
}

function scrollDown(element) {
    if (element) element.scrollTop = element.scrollHeight;
}

window.addEventListener("DOMContentLoaded", () => {
    const cmdInput = document.getElementById("cmd-input");
    const btnSend = document.getElementById("btn-send");
    const btnMacro = document.getElementById("btn-macro");
    const btnVoice = document.getElementById("btn-voice");
	const btnTracker = document.getElementById("btn-tracker");

    if (cmdInput) {
        cmdInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendNaturalCommand();
            }
        });
    }

    if (btnSend) btnSend.addEventListener("click", sendNaturalCommand);
    if (btnMacro) btnMacro.addEventListener("click", () => toggleInfrastructure("macro"));
    if (btnVoice) btnVoice.addEventListener("click", () => toggleInfrastructure("voice"));
	if (btnTracker) btnTracker.addEventListener("click", () => connectMouseWebSocket());

    connectLogWebSocket();
    connectMouseWebSocket();
});