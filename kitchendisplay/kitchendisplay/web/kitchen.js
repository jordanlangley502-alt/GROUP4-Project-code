"use strict";

// Kitchen Display (Feature 2). Talks to the shared backend on the same origin:
//   GET   /orders?sequence=oldest      confirmed orders in the sequence they were placed (SR-2.1)
//   PATCH /orders/{id}/status          Confirmed -> Making -> Ready (SR-2.2)
//   WS    /ws/changes                  pushes order changes so the screen never needs a refresh
// Order data (including staff-typed special requests) is only ever written into the page as plain text.

const TOKEN_KEY = "jamrock_kitchen_token";
const USER_KEY = "jamrock_kitchen_user";
const READY_LIMIT = 8; // newest Ready orders kept on screen
const POLL_MS = 2000; // fallback refresh while the live connection is down
const WARN_MINUTES = 10;
const LATE_MINUTES = 20;

const NEXT = {
  Confirmed: { status: "Making", label: "Start making" },
  Making: { status: "Ready", label: "Mark ready" },
};
const STATUSES = ["Confirmed", "Making", "Ready"];

const loginView = document.querySelector("#login-view");
const loginForm = document.querySelector("#login-form");
const loginError = document.querySelector("#login-error");
const appView = document.querySelector("#app-view");
const errorBanner = document.querySelector("#error-banner");
const errorMessage = document.querySelector("#message");
const connection = document.querySelector("#connection");
const connectionText = document.querySelector("#connection-text");
const columns = Object.fromEntries(
  STATUSES.map(status => [
    status,
    {
      list: document.querySelector(`#list-${status.toLowerCase()}`),
      count: document.querySelector(`#count-${status.toLowerCase()}`),
      empty: document.querySelector(`#empty-${status.toLowerCase()}`),
    },
  ])
);

let orders = [];
const views = new Map(); // order_id -> ticket DOM references
const pending = new Set(); // order ids with a status change in flight
let knownIds = new Set();
let firstLoad = true;
let socket = null;
let live = false;
let loading = false;
let reloadQueued = false;
let loadFailed = false;
let pollTicks = 0;
let reconnectTimer;
let pollTimer;
let ageTimer;

const token = () => sessionStorage.getItem(TOKEN_KEY);

function setError(message) {
  errorMessage.textContent = message;
  errorBanner.hidden = !message;
}

function setLive(value) {
  live = value;
  connection.classList.toggle("is-offline", !value);
  connectionText.textContent = value ? "Live" : "Refreshing every 2 s";
}

function errorText(data, fallback) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(item => item.msg).join(" ");
  return fallback;
}

async function api(path, options = {}, isLogin = false) {
  const headers = new Headers(options.headers || {});
  if (token()) headers.set("Authorization", `Bearer ${token()}`);
  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch {
    throw new Error("Cannot reach the server. Retrying...");
  }
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (response.status === 401 && !isLogin) {
    showLogin("Your session has expired. Please sign in again.");
    throw new Error("Session expired.");
  }
  if (!response.ok) throw new Error(errorText(data, "The request could not be completed."));
  return data;
}

/* ---------- sign in / out ---------- */

function stopLive() {
  clearTimeout(reconnectTimer);
  clearInterval(pollTimer);
  clearInterval(ageTimer);
  if (socket) {
    const old = socket;
    socket = null; // tells onclose this was intentional
    old.close();
  }
  setLive(false);
}

function showLogin(message = "") {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
  stopLive();
  orders = [];
  views.clear();
  pending.clear();
  knownIds = new Set();
  firstLoad = true;
  for (const status of STATUSES) {
    columns[status].list.replaceChildren();
    columns[status].count.textContent = "0";
    columns[status].empty.hidden = false;
  }
  setError("");
  appView.hidden = true;
  loginView.hidden = false;
  loginError.textContent = message;
  loginError.hidden = !message;
  window.setTimeout(() => document.querySelector("#username").focus(), 0);
}

function showBoard(user) {
  loginView.hidden = true;
  appView.hidden = false;
  document.querySelector("#kitchen-name").textContent = user.display_name || user.username || "Kitchen";
  setError("");
  stopLive();
  connectSocket();
  loadOrders();
  pollTicks = 0;
  pollTimer = setInterval(() => {
    pollTicks += 1;
    // Live connection: a slow safety refresh. No connection: refresh fast so nothing is missed.
    if (!live || pollTicks % 10 === 0) loadOrders();
  }, POLL_MS);
  ageTimer = setInterval(updateAges, 1000);
}

loginForm.addEventListener("submit", async event => {
  event.preventDefault();
  const submit = document.querySelector("#sign-in");
  loginError.hidden = true;
  submit.disabled = true;
  submit.textContent = "Signing in...";
  try {
    const data = await api(
      "/auth/login",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: document.querySelector("#username").value.trim(),
          password: document.querySelector("#password").value,
        }),
      },
      true
    );
    if (!data.access_token || !data.user) throw new Error("Sign in failed. Please try again.");
    if (data.user.role !== "Kitchen") {
      // Do not keep a session for the wrong role.
      await fetch("/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${data.access_token}` } }).catch(() => {});
      throw new Error("Please sign in with a kitchen account.");
    }
    sessionStorage.setItem(TOKEN_KEY, data.access_token);
    sessionStorage.setItem(USER_KEY, JSON.stringify(data.user));
    document.querySelector("#password").value = "";
    showBoard(data.user);
  } catch (error) {
    loginError.textContent = error.message || "Sign in failed. Please try again.";
    loginError.hidden = false;
  } finally {
    submit.disabled = false;
    submit.textContent = "Sign in";
  }
});

document.querySelector("#logout").addEventListener("click", async () => {
  try {
    await api("/auth/logout", { method: "POST" });
  } catch {
    // Sign out on this screen even if the server could not be reached.
  }
  showLogin("You have been signed out.");
});

document.querySelector("#dismiss-error").addEventListener("click", () => setError(""));

/* ---------- live connection ---------- */

function connectSocket() {
  clearTimeout(reconnectTimer);
  if (!token()) return;
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${scheme}//${location.host}/ws/changes`);
  socket = ws;
  ws.onopen = () => ws.send(JSON.stringify({ token: token() }));
  ws.onmessage = event => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    if (message.type === "resync") {
      // Sent on every (re)connection: reload so orders placed while disconnected appear.
      setLive(true);
      loadOrders();
    } else if (message.type === "changed" && message.topic === "orders") {
      loadOrders();
    }
  };
  ws.onclose = event => {
    if (socket !== ws) return;
    setLive(false);
    if (!token()) return;
    if (event.code === 1008) {
      // Rejected: expired session (api() returns to sign-in on 401) or a blocked origin (polling covers it).
      api("/auth/me").catch(() => {});
    }
    reconnectTimer = setTimeout(connectSocket, event.code === 1008 ? 10000 : 1000);
  };
}

/* ---------- loading and rendering ---------- */

async function loadOrders() {
  if (loading) {
    reloadQueued = true;
    return;
  }
  loading = true;
  try {
    do {
      reloadQueued = false;
      const data = await api("/orders?sequence=oldest");
      if (!token()) return; // signed out while the request was in flight
      orders = data;
      if (loadFailed) {
        loadFailed = false;
        setError("");
      }
      render();
    } while (reloadQueued);
  } catch (error) {
    if (token()) {
      loadFailed = true;
      setError(error.message);
    }
  } finally {
    loading = false;
  }
}

function appendText(parent, tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  parent.appendChild(element);
  return element;
}

function createTicket(order) {
  const card = document.createElement("article");
  card.className = "ticket";

  const top = document.createElement("div");
  top.className = "ticket-top";
  const number = appendText(top, "strong", "ticket-number", "");
  const type = appendText(top, "span", "type-badge", "");

  const meta = document.createElement("div");
  meta.className = "ticket-meta";
  const placed = appendText(meta, "span", "ticket-placed", "");
  const age = appendText(meta, "span", "ticket-age", "");

  const list = document.createElement("ul");
  list.className = "ticket-items";

  const action = document.createElement("button");
  action.type = "button";
  action.className = "button button-primary ticket-action";
  const done = document.createElement("p");
  done.className = "ticket-done";
  done.textContent = "Ready for pickup";

  card.append(top, meta, list, action, done);
  const view = { card, number, type, placed, age, list, action, done, itemsKey: null, order };
  action.addEventListener("click", () => advance(view));
  return view;
}

function placedTime(order) {
  const stamp = Date.parse(order.placed_at);
  return Number.isNaN(stamp) ? null : stamp;
}

function updateTicket(view, order) {
  view.order = order;
  view.card.dataset.status = order.status;
  view.number.textContent = `#${order.order_id}`;
  view.type.textContent = order.order_type;
  const stamp = placedTime(order);
  view.placed.textContent = stamp === null ? "" : new Date(stamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  const items = order.items || [];
  const key = JSON.stringify(items.map(item => [item.item_name, item.quantity, item.special_request]));
  if (key !== view.itemsKey) {
    view.itemsKey = key;
    view.list.replaceChildren(
      ...items.map(item => {
        const row = document.createElement("li");
        row.className = "ticket-item";
        appendText(row, "span", "item-qty", `${item.quantity}×`);
        appendText(row, "span", "item-name", item.item_name);
        if (item.special_request && item.special_request.trim()) {
          appendText(row, "p", "item-request", `Request: ${item.special_request.trim()}`);
        }
        return row;
      })
    );
  }

  const next = NEXT[order.status];
  const busy = pending.has(order.order_id);
  view.action.hidden = !next;
  view.done.hidden = Boolean(next);
  if (next) {
    view.action.textContent = busy ? "Updating..." : next.label;
    view.action.disabled = busy;
    view.action.classList.toggle("to-ready", next.status === "Ready");
  }
}

function render() {
  const buckets = { Confirmed: [], Making: [], Ready: [] };
  for (const order of orders) {
    if (buckets[order.status]) buckets[order.status].push(order); // already oldest first from the server
  }
  buckets.Ready = buckets.Ready.slice(-READY_LIMIT).reverse(); // newest Ready first

  const freshIds = firstLoad
    ? new Set()
    : new Set(buckets.Confirmed.filter(order => !knownIds.has(order.order_id)).map(order => order.order_id));

  const seen = new Set();
  for (const status of STATUSES) {
    const cards = buckets[status].map(order => {
      seen.add(order.order_id);
      let view = views.get(order.order_id);
      if (!view) {
        view = createTicket(order);
        views.set(order.order_id, view);
      }
      updateTicket(view, order);
      if (freshIds.has(order.order_id)) {
        view.card.classList.add("is-new");
        window.setTimeout(() => view.card.classList.remove("is-new"), 1800);
      }
      return view.card;
    });
    columns[status].list.replaceChildren(...cards);
    columns[status].count.textContent = String(cards.length);
    columns[status].empty.hidden = cards.length > 0;
  }
  for (const [id, view] of views) {
    if (!seen.has(id)) {
      view.card.remove();
      views.delete(id);
    }
  }
  knownIds = new Set(orders.map(order => order.order_id));
  firstLoad = false;
  updateAges();
}

function updateAges() {
  const now = Date.now();
  for (const view of views.values()) {
    const stamp = placedTime(view.order);
    const waiting = view.order.status !== "Ready" && stamp !== null;
    const minutes = waiting ? Math.max(0, Math.floor((now - stamp) / 60000)) : 0;
    view.age.textContent = !waiting ? "" : minutes < 1 ? "just now" : `${minutes} min`;
    view.card.classList.toggle("age-warn", waiting && minutes >= WARN_MINUTES && minutes < LATE_MINUTES);
    view.card.classList.toggle("age-late", waiting && minutes >= LATE_MINUTES);
  }
}

/* ---------- status changes ---------- */

async function advance(view) {
  const order = view.order;
  const next = NEXT[order.status];
  if (!next || pending.has(order.order_id)) return;
  pending.add(order.order_id);
  updateTicket(view, order);
  try {
    await api(`/orders/${order.order_id}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: next.status }),
    });
    setError("");
  } catch (error) {
    if (token()) {
      setError(
        /transition/i.test(error.message)
          ? "That order was already updated on another screen. The board has been refreshed."
          : error.message
      );
    }
  } finally {
    pending.delete(order.order_id);
  }
  await loadOrders(); // always show what the server now holds
}

/* ---------- start ---------- */

async function loadInitialUser() {
  if (!token()) {
    loginView.hidden = false;
    return;
  }
  try {
    const user = await api("/auth/me");
    if (user.role !== "Kitchen") {
      showLogin("Please sign in with a kitchen account.");
      return;
    }
    showBoard(user);
  } catch (error) {
    if (token()) showLogin(error.message);
  }
}

setLive(false);
loadInitialUser();
