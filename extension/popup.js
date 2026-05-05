const dot        = document.getElementById("dot");
const statusText = document.getElementById("status-text");
const detail     = document.getElementById("detail");
const reconnBtn  = document.getElementById("reconnect-btn");

function setConnected(canvasUrl) {
  dot.className = "dot dot--connected";
  statusText.textContent = "Connected";
  detail.textContent = canvasUrl || "";
  detail.classList.toggle("hidden", !canvasUrl);
}

function setDisconnected() {
  dot.className = "dot dot--disconnected";
  statusText.textContent = "Not connected";
  detail.classList.add("hidden");
}

function setChecking() {
  dot.className = "dot dot--connecting";
  statusText.textContent = "Checking...";
  detail.classList.add("hidden");
}

async function refresh() {
  setChecking();
  chrome.runtime.sendMessage({ type: "get_status" }, (res) => {
    if (chrome.runtime.lastError || !res) {
      setDisconnected();
      return;
    }
    if (res.connected) {
      setConnected(res.canvasUrl);
    } else {
      setDisconnected();
    }
  });
}

reconnBtn.addEventListener("click", () => {
  setChecking();
  chrome.runtime.sendMessage({ type: "reconnect" }, () => {
    setTimeout(refresh, 1500);
  });
});

refresh();
