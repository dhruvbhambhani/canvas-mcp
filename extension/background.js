/**
 * canvas-mcp Chrome extension — background service worker
 *
 * Connects to the local Python server via WebSocket.
 * Proxies Canvas API requests from Python through the browser session,
 * so no personal access token is needed — auth comes from the browser cookies.
 */

const WS_URL = "ws://localhost:3001";
const RECONNECT_DELAY_MS = 3000;
const KEEPALIVE_INTERVAL_MIN = 0.4; // ~24s — keeps service worker alive

let ws = null;
let canvasBaseUrl = "";
let reconnectTimer = null;

// ---------------------------------------------------------------------------
// WebSocket connection
// ---------------------------------------------------------------------------

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  try {
    ws = new WebSocket(WS_URL);
  } catch (e) {
    scheduleReconnect();
    return;
  }

  ws.onopen = async () => {
    clearTimeout(reconnectTimer);
    const url = await getCanvasUrl();
    canvasBaseUrl = url;

    const user = await getCanvasUser(url);
    ws.send(JSON.stringify({ type: "connected", url, user }));

    chrome.storage.local.set({ connected: true, canvasUrl: url, user });
    console.log("[canvas-mcp] Connected to server. Canvas:", url);
  };

  ws.onmessage = async (event) => {
    let req;
    try {
      req = JSON.parse(event.data);
    } catch {
      return;
    }
    const response = await handleRequest(req);
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(response));
    }
  };

  ws.onclose = () => {
    chrome.storage.local.set({ connected: false });
    scheduleReconnect();
  };

  ws.onerror = () => {
    ws.close();
  };
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
}

// ---------------------------------------------------------------------------
// Canvas URL detection
// ---------------------------------------------------------------------------

async function getCanvasUrl() {
  // Check if user has a tab open on Canvas
  const tabs = await chrome.tabs.query({});
  for (const tab of tabs) {
    if (tab.url && isCanvasUrl(tab.url)) {
      return new URL(tab.url).origin;
    }
  }
  // Fallback: check stored value
  const stored = await chrome.storage.local.get("canvasUrl");
  return stored.canvasUrl || "";
}

function isCanvasUrl(url) {
  try {
    const u = new URL(url);
    return (
      u.hostname.endsWith(".instructure.com") ||
      u.hostname === "canvas.tamu.edu"
    );
  } catch {
    return false;
  }
}

async function getCanvasUser(baseUrl) {
  if (!baseUrl) return "";
  try {
    const res = await fetch(`${baseUrl}/api/v1/users/self`, { credentials: "include" });
    if (!res.ok) return "";
    const data = await res.json();
    return data.name || data.login_id || "";
  } catch {
    return "";
  }
}

// ---------------------------------------------------------------------------
// Request handler — proxies Canvas API calls from the Python server
// ---------------------------------------------------------------------------

async function handleRequest(req) {
  const { id, endpoint, params = {}, single = false } = req;

  if (!canvasBaseUrl) {
    canvasBaseUrl = await getCanvasUrl();
  }
  if (!canvasBaseUrl) {
    return { id, data: null, error: "Canvas not open. Open canvas.tamu.edu in this browser." };
  }

  try {
    const data = single
      ? await fetchSingle(canvasBaseUrl, endpoint, params)
      : await fetchAllPages(canvasBaseUrl, endpoint, params);
    return { id, data, error: null };
  } catch (err) {
    return { id, data: null, error: err.message };
  }
}

async function fetchSingle(baseUrl, endpoint, params) {
  const url = buildUrl(baseUrl, endpoint, params);
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error(`Canvas API ${res.status}: ${endpoint}`);
  return res.json();
}

async function fetchAllPages(baseUrl, endpoint, params) {
  const results = [];
  let nextUrl = buildUrl(baseUrl, endpoint, params);

  while (nextUrl) {
    const res = await fetch(nextUrl, { credentials: "include" });
    if (!res.ok) throw new Error(`Canvas API ${res.status}: ${endpoint}`);

    const data = await res.json();

    if (Array.isArray(data)) {
      results.push(...data);
    } else {
      return data; // single-object response (shouldn't happen in paginated mode)
    }

    nextUrl = parseNextLink(res.headers.get("Link"));
  }

  return results;
}

function buildUrl(baseUrl, endpoint, params) {
  const url = new URL(endpoint, baseUrl);
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      value.forEach((v) => url.searchParams.append(key, v));
    } else {
      url.searchParams.set(key, value);
    }
  }
  return url.toString();
}

function parseNextLink(linkHeader) {
  if (!linkHeader) return null;
  for (const part of linkHeader.split(",")) {
    const match = part.match(/<([^>]+)>;\s*rel="next"/);
    if (match) return match[1];
  }
  return null;
}

// ---------------------------------------------------------------------------
// Keepalive — prevents service worker from being killed after 30s idle
// ---------------------------------------------------------------------------

chrome.alarms.create("keepalive", { periodInMinutes: KEEPALIVE_INTERVAL_MIN });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepalive") {
    if (!ws || ws.readyState === WebSocket.CLOSED) {
      connect();
    }
  }
});

// ---------------------------------------------------------------------------
// Listen for messages from popup
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "get_status") {
    sendResponse({
      connected: ws?.readyState === WebSocket.OPEN,
      canvasUrl: canvasBaseUrl,
    });
  }
  if (msg.type === "reconnect") {
    connect();
    sendResponse({ ok: true });
  }
  return true; // keep channel open for async
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

connect();
