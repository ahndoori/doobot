const logBox = document.getElementById("log-box");
const cmdInput = document.getElementById("cmd-input");
const btnSend = document.getElementById("btn-send");

const btnMacro = document.getElementById("btn-macro");
const btnVoice = document.getElementById("btn-voice");

const ws = new WebSocket(`ws://${window.location.host}/ws/logs`);

ws.onmessage = (event) => {
    const data = jsonParseSafe(event.data);
    if (!data) return;
console.log(data);

    if (data.type === "init_logs") {
        logBox.innerHTML = data.logs.map(log => `<div>${log}</div>`).join("");
        scrollDown();
    } else if (data.type === "new_log") {
        const logLine = document.createElement("div");
        logLine.textContent = data.log;
        logBox.appendChild(logLine);
        scrollDown();
    } else if (data.type === "infra_status") {
        updateButtonStatus(btnMacro, data.macro_alive);
        updateButtonStatus(btnVoice, data.voice_alive);
    }
};

function updateButtonStatus(button, isAlive) {
    if (isAlive) {
        button.querySelector('span').classList.remove("led-red");
        button.querySelector('span').classList.add("led-green");
    } else {
        button.querySelector('span').classList.remove("led-green");
        button.querySelector('span').classList.add("led-red");
    }
}

cmdInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendNaturalCommand();
    }
});

btnSend.addEventListener("click", sendNaturalCommand);

async function sendNaturalCommand() {
    const commandText = cmdInput.value.trim();
    if (!commandText) return;
    cmdInput.value = "";
    appendLocalLog(`👤 [User Input] ➡️ ${commandText}`);
    try {
        const response = await fetch("http://127.0.0.1:4445/api/command", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command: commandText })
        });
        const result = await response.json();
        if (result.status !== "success") {
            appendLocalLog(`⚠️ [Macro Link] 코어 응답 실패: ${result.message}`);
        }
    } catch (err) {
        appendLocalLog(`❌ [Network Error] 매크로 코어(4445) 서버가 꺼져있거나 통신이 불가능합니다.`);
    }
}


btnMacro.addEventListener("click", () => toggleInfrastructure("macro"));
btnVoice.addEventListener("click", () => toggleInfrastructure("voice"));

async function toggleInfrastructure(target) {
    try {
        await fetch(`/api/infra/toggle/${target}`, { method: "POST" });
    } catch (err) {
        console.error("인프라 토글 통신 실패:", err);
    }
}

function appendLocalLog(msg) {
    const timestamp = new Date().toLocaleTimeString();
    const logLine = document.createElement("div");
    logLine.textContent = `[${timestamp}] ${msg}`;
    logBox.appendChild(logLine);
    scrollDown();
}

function jsonParseSafe(text) {
    try { return JSON.parse(text); } catch (e) { return null; }
}

function scrollDown() {
    logBox.scrollTop = logBox.scrollHeight;
}