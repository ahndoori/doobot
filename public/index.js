const SERVER_HOST = window.location.host;
//const MACRO_CORE_URL = "http://127.0.0.1:4445/api/command";
const MACRO_CORE_URL = "http://127.0.0.1:4444/api/command";

let logSocket = null;
let mouseSocket = null;
let keySocket = null;

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
    //const btnMacro = document.getElementById("btn-macro");
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
            //updateButtonStatus(btnMacro, data.macro_alive);
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
	const btnMouse=document.getElementById("btn-mouse");
    mouseSocket = new WebSocket(`ws://${SERVER_HOST}/ws/mouse`);

    mouseSocket.onopen = () => {
		log("🚀 MOUSE SOCKET OPENED");
		updateButtonStatus(btnMouse,true);
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
		updateButtonStatus(btnMouse,false);
		log("⚠️ MOUSE SOCKET CLOSED");
        //setTimeout(connectMouseWebSocket,2000);
    };

    mouseSocket.onerror = (err) => {
        log(`👤 MOUSE SOCKET ERROR: ${err}`);
        mouseSocket.close();
    };
}

function connectKeyWebSocket(){
	if(typeof keySocket !== "undefined" && keySocket && 
       (keySocket.readyState === WebSocket.CONNECTING || keySocket.readyState === WebSocket.OPEN)) {
        log("ℹ️ KEY SOCKET IS ALREADY CONNECTED");
        return;
    }
    if (typeof keySocket !== "undefined" && keySocket) keySocket.close();
	const btnKey=document.getElementById("btn-key");
    keySocket = new WebSocket(`ws://${SERVER_HOST}/ws/key`);
    keySocket.onopen = () => {
		log("🚀 KEY SOCKET OPENED");
		updateButtonStatus(btnKey,true);
    };
    keySocket.onmessage = (event) => {
        const data = jsonParseSafe(event.data);
        if(!data) return;
        const keyData = document.getElementById("key-data");
        if (keyData) keyData.textContent = data.source.substr(0,1)+data.value;
    };
    keySocket.onclose = () => {
		updateButtonStatus(btnKey,false);
		log("⚠️ KEY SOCKET CLOSED");
    };
    keySocket.onerror = (err) => {
        log(`👤 KEY SOCKET ERROR: ${err}`);
        keySocket.close();
    };
}




async function sendNaturalCommand() {
    const cmdInput = document.getElementById("cmd-input");
    const commandText = cmdInput.value.trim();
    if (!commandText) return;
    cmdInput.value = "";
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
    //const btnMacro = document.getElementById("btn-macro");
    const btnVoice = document.getElementById("btn-voice");
	const btnMouse = document.getElementById("btn-mouse");
	const btnKey = document.getElementById("btn-key");

    if(cmdInput){
        cmdInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendNaturalCommand();
            }
        });
    }

    if(btnSend) btnSend.addEventListener("click", sendNaturalCommand);
	if(btnVoice) btnVoice.addEventListener("click", /*async*/ () => /*await*/ fetch(`/api/daemon/voice`,{method:'POST'}) );
	if(btnMouse) btnMouse.addEventListener("click", () => connectMouseWebSocket());
	if(btnKey) btnKey.addEventListener("click", () => connectKeyWebSocket());
	//if (btnMacro) btnMacro.addEventListener("click", () => toggleInfrastructure("macro"));
    connectLogWebSocket();
    connectMouseWebSocket();
	connectKeyWebSocket();
});