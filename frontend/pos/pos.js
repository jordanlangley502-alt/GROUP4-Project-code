const cart = new Map();
let idempotencyKey;
let recentNodes = new Map();
let refreshTimer;

const loginView = document.querySelector("#login-view");
const loginForm = document.querySelector("#login-form");
const loginError = document.querySelector("#login-error");
const appView = document.querySelector("#app-view");
const menuEl = document.querySelector("#menu");
const cartEl = document.querySelector("#cart");
const totalEl = document.querySelector("#total");
const confirmButton = document.querySelector("#confirm");
const deliveryFields = document.querySelector("#delivery-fields");
const addressInput = document.querySelector("#delivery-address");
const phoneInput = document.querySelector("#customer-phone");
const recentPanel = document.querySelector("#recent-orders");
const errorBanner = document.querySelector("#error-banner");
const errorMessage = document.querySelector("#message");

function newIdempotencyKey() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(byte => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

idempotencyKey = newIdempotencyKey();

function money(value) {
  return `J$ ${Number(value).toLocaleString("en-JM", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })}`;
}

function setError(message) {
  errorMessage.textContent = message;
  errorBanner.hidden = !message;
}

function clearSession() {
  sessionStorage.removeItem("jamrock_token");
  sessionStorage.removeItem("jamrock_user");
  window.clearInterval(refreshTimer);
  refreshTimer = undefined;
  cart.clear();
  idempotencyKey = newIdempotencyKey();
  if (document.querySelector("#receipt-dialog").open) {
    document.querySelector("#receipt-dialog").close();
  }
  document.querySelector('input[name="orderType"][value="dine_in"]').checked = true;
  updateOrderType();
  renderCart();
  setError("");
}

function showLogin(message = "") {
  clearSession();
  appView.hidden = true;
  loginView.hidden = false;
  loginError.textContent = message;
  loginError.hidden = !message;
  window.setTimeout(() => document.querySelector("#username").focus(), 0);
}

function showRegister(user) {
  loginView.hidden = true;
  appView.hidden = false;
  document.querySelector("#cashier-name").textContent =
    user.display_name || user.username || "Cashier";
  setError("");
  refreshRegister();
  window.clearInterval(refreshTimer);
  refreshTimer = window.setInterval(() => {
    if (!appView.hidden) {
      loadRecentOrders().catch(error => {
        if (sessionStorage.getItem("jamrock_token")) setError(error.message);
      });
    }
  }, 3000);
}

function errorText(data, fallback) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(item => item.msg).join(" ");
  return fallback;
}

async function apiRequest(path, options = {}, isLogin = false) {
  const token = sessionStorage.getItem("jamrock_token");
  const headers = new Headers(options.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...options, headers });
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

loginForm.addEventListener("submit", async event => {
  event.preventDefault();
  const submit = document.querySelector("#sign-in");
  loginError.hidden = true;
  submit.disabled = true;
  submit.textContent = "Signing in...";
  try {
    const data = await apiRequest("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: document.querySelector("#username").value.trim(),
        password: document.querySelector("#password").value
      })
    }, true);
    if (!data.access_token || !data.user) throw new Error("Sign in failed. Please try again.");
    if (data.user.role !== "Cashier") throw new Error("Please sign in with a cashier account.");
    sessionStorage.setItem("jamrock_token", data.access_token);
    sessionStorage.setItem("jamrock_user", JSON.stringify(data.user));
    document.querySelector("#password").value = "";
    showRegister(data.user);
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
    await apiRequest("/auth/logout", { method: "POST" });
    showLogin("You have been signed out.");
  } catch {
    if (sessionStorage.getItem("jamrock_token")) setError("Could not sign out. Please try again.");
  }
});

async function refreshRegister() {
  await loadMenu().catch(error => {
    if (sessionStorage.getItem("jamrock_token")) {
      document.querySelector("#menu-error").textContent = error.message;
      document.querySelector("#menu-error").hidden = false;
    }
  });
  await loadRecentOrders().catch(error => {
    if (sessionStorage.getItem("jamrock_token")) setError(error.message);
  });
}

async function loadMenu() {
  const items = await apiRequest("/api/menu");
  document.querySelector("#menu-error").hidden = true;
  document.querySelector("#menu-count").textContent = `${items.length} items`;
  menuEl.replaceChildren();
  if (items.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No menu items are available right now.";
    menuEl.appendChild(empty);
    return;
  }
  items.forEach(item => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "menu-card";
    button.disabled = item.is_available === false;
    if (button.disabled) button.classList.add("unavailable");

    const name = document.createElement("span");
    name.className = "menu-card-name";
    name.textContent = item.name;
    const price = document.createElement("span");
    price.className = "menu-card-price";
    price.textContent = button.disabled ? "Unavailable" : money(item.unit_price);
    button.append(name, price);
    button.addEventListener("click", () => {
      addToCart(item);
      button.classList.remove("added");
      void button.offsetWidth;
      button.classList.add("added");
    });
    menuEl.appendChild(button);
  });
}

function addToCart(item) {
  const line = cart.get(item.menu_item_id);
  if (line) line.quantity += 1;
  else cart.set(item.menu_item_id, { ...item, quantity: 1, special_request: "" });
  setError("");
  renderCart();
}

function renderCart() {
  cartEl.replaceChildren();
  if (cart.size === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-cart";
    const symbol = document.createElement("span");
    symbol.className = "empty-cart-symbol";
    symbol.setAttribute("aria-hidden", "true");
    symbol.textContent = "＋";
    const message = document.createElement("strong");
    message.textContent = "Tap a menu item to start an order";
    empty.append(symbol, message);
    cartEl.appendChild(empty);
  }

  let quantityTotal = 0;
  for (const [id, line] of cart) {
    quantityTotal += line.quantity;
    const wrapper = document.createElement("article");
    wrapper.className = "cart-line";

    const top = document.createElement("div");
    top.className = "cart-line-top";
    const itemInfo = document.createElement("div");
    const name = document.createElement("div");
    name.className = "cart-line-name";
    name.textContent = line.name;
    const unitPrice = document.createElement("div");
    unitPrice.className = "cart-line-unit";
    unitPrice.textContent = `${money(line.unit_price)} each`;
    itemInfo.append(name, unitPrice);
    const subtotal = document.createElement("span");
    subtotal.className = "cart-line-subtotal";
    subtotal.textContent = money(line.unit_price * line.quantity);
    top.append(itemInfo, subtotal);

    const controls = document.createElement("div");
    controls.className = "cart-line-controls";
    const minus = document.createElement("button");
    minus.type = "button";
    minus.className = "stepper";
    minus.textContent = "−";
    minus.setAttribute("aria-label", `Remove one ${line.name}`);
    minus.addEventListener("click", () => {
      line.quantity -= 1;
      if (line.quantity <= 0) cart.delete(id);
      renderCart();
    });
    const count = document.createElement("span");
    count.className = "quantity-value";
    count.textContent = String(line.quantity);
    count.setAttribute("aria-label", `Quantity ${line.quantity}`);
    const plus = document.createElement("button");
    plus.type = "button";
    plus.className = "stepper";
    plus.textContent = "+";
    plus.setAttribute("aria-label", `Add one ${line.name}`);
    plus.addEventListener("click", () => {
      line.quantity += 1;
      renderCart();
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-item";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove ${line.name} from order`);
    remove.addEventListener("click", () => {
      cart.delete(id);
      renderCart();
    });
    controls.append(minus, count, plus, remove);

    const request = document.createElement("input");
    request.type = "text";
    request.className = "cart-request";
    request.placeholder = "Special request, e.g. no pepper";
    request.setAttribute("aria-label", `Special request for ${line.name}`);
    request.value = line.special_request;
    request.addEventListener("input", () => { line.special_request = request.value; });
    wrapper.append(top, controls, request);
    cartEl.appendChild(wrapper);
  }

  const total = [...cart.values()].reduce(
    (sum, line) => sum + Number(line.unit_price) * line.quantity,
    0
  );
  totalEl.textContent = money(total);
  document.querySelector("#cart-count").textContent =
    `${quantityTotal} ${quantityTotal === 1 ? "item" : "items"}`;
  confirmButton.disabled = cart.size === 0 || confirmButton.dataset.pending === "true";
}

function updateOrderType() {
  const deliverySelected =
    document.querySelector('input[name="orderType"]:checked').value === "delivery";
  deliveryFields.classList.toggle("visible", deliverySelected);
  deliveryFields.setAttribute("aria-hidden", String(!deliverySelected));
  deliveryFields.inert = !deliverySelected;
}
document.querySelectorAll('input[name="orderType"]').forEach(input => {
  input.addEventListener("change", updateOrderType);
});
updateOrderType();

document.querySelector("#dismiss-error").addEventListener("click", () => setError(""));

confirmButton.addEventListener("click", async () => {
  if (cart.size === 0 || confirmButton.dataset.pending === "true") return;
  setError("");
  const orderType = document.querySelector('input[name="orderType"]:checked').value;
  const body = {
    order_type: orderType,
    line_items: [...cart.values()].map(line => ({
      menu_item_id: line.menu_item_id,
      quantity: line.quantity,
      special_request: line.special_request
    })),
    idempotency_key: idempotencyKey
  };
  if (orderType === "delivery") {
    body.delivery_address = addressInput.value;
    body.customer_phone = phoneInput.value;
  }

  confirmButton.dataset.pending = "true";
  confirmButton.disabled = true;
  confirmButton.textContent = "Placing order...";
  try {
    const order = await apiRequest("/api/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    showReceipt(order);
    cart.clear();
    addressInput.value = "";
    phoneInput.value = "";
    idempotencyKey = newIdempotencyKey();
    renderCart();
    await loadRecentOrders();
  } catch (error) {
    if (sessionStorage.getItem("jamrock_token")) setError(error.message);
  } finally {
    confirmButton.dataset.pending = "false";
    confirmButton.textContent = "Confirm Order";
    confirmButton.disabled = cart.size === 0;
  }
});

function appendText(parent, tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = value;
  parent.appendChild(element);
  return element;
}

function showReceipt(order) {
  document.querySelector("#success-number").textContent = `Order #${order.order_id}`;
  document.querySelector("#success-total").textContent = money(order.total);
  const receipt = document.querySelector("#receipt");
  receipt.replaceChildren();
  appendText(receipt, "h1", "", "Jamrock Bitez");
  appendText(receipt, "p", "receipt-meta", `Order #${order.order_id} · ${new Date(order.placed_at).toLocaleString()}`);
  order.line_items.forEach(line => {
    const row = document.createElement("div");
    row.className = "receipt-line";
    const detail = document.createElement("div");
    appendText(detail, "span", "", `${line.quantity} × ${line.name}`);
    if (line.special_request) {
      appendText(detail, "p", "receipt-request", `Request: ${line.special_request}`);
    }
    appendText(row, "span", "", money(line.subtotal));
    row.prepend(detail);
    receipt.appendChild(row);
  });
  appendText(receipt, "p", "receipt-total", `Total: ${money(order.total)}`);
  document.querySelector("#receipt-dialog").showModal();
}

document.querySelector("#print-receipt").addEventListener("click", () => window.print());
document.querySelector("#new-order").addEventListener("click", () => {
  document.querySelector("#receipt-dialog").close();
  document.querySelector('input[name="orderType"][value="dine_in"]').checked = true;
  updateOrderType();
  setError("");
  menuEl.querySelector("button:not(:disabled)")?.focus();
});

function orderTypeLabel(type) {
  return ({ dine_in: "Dine-in", takeout: "Takeout", delivery: "Delivery" })[type] || type;
}

function statusClass(status) {
  return ({ Confirmed: "status-confirmed", Making: "status-making", Ready: "status-ready" })[status] || "";
}

function createRecentCard() {
  const card = document.createElement("article");
  card.className = "recent-card";
  const top = document.createElement("div");
  top.className = "recent-card-top";
  const number = document.createElement("strong");
  number.className = "recent-order-number";
  const type = document.createElement("span");
  type.className = "type-badge";
  top.append(number, type);
  const bottom = document.createElement("div");
  bottom.className = "recent-card-bottom";
  const total = document.createElement("span");
  total.className = "recent-total";
  const status = document.createElement("span");
  status.className = "status-pill";
  bottom.append(total, status);
  card.append(top, bottom);
  return { card, number, type, total, status };
}

async function loadRecentOrders() {
  const orders = await apiRequest("/api/orders");
  document.querySelector("#recent-empty")?.remove();
  const seen = new Set();
  orders.forEach((order, index) => {
    const key = String(order.order_id);
    seen.add(key);
    let view = recentNodes.get(key);
    if (!view) {
      view = createRecentCard();
      recentNodes.set(key, view);
    }
    view.number.textContent = `Order #${order.order_id}`;
    view.type.textContent = orderTypeLabel(order.order_type);
    view.total.textContent = money(order.total);
    view.status.textContent = order.status;
    view.status.className = `status-pill ${statusClass(order.status)}`;
    const nodeAtPosition = recentPanel.children[index];
    if (nodeAtPosition !== view.card) recentPanel.insertBefore(view.card, nodeAtPosition || null);
  });
  for (const [key, view] of recentNodes) {
    if (!seen.has(key)) {
      view.card.remove();
      recentNodes.delete(key);
    }
  }
  if (orders.length === 0 && !document.querySelector("#recent-empty")) {
    const empty = document.createElement("p");
    empty.id = "recent-empty";
    empty.className = "recent-empty";
    empty.textContent = "No orders yet. Confirmed orders will show here.";
    recentPanel.appendChild(empty);
  }
}

async function loadInitialUser() {
  const token = sessionStorage.getItem("jamrock_token");
  if (!token) {
    loginView.hidden = false;
    return;
  }
  try {
    // Revalidate the saved session so an expired token returns to the sign-in card.
    const user = await apiRequest("/auth/me");
    if (user.role !== "Cashier") {
      showLogin("Please sign in with a cashier account.");
      return;
    }
    sessionStorage.setItem("jamrock_user", JSON.stringify(user));
    showRegister(user);
  } catch (error) {
    if (sessionStorage.getItem("jamrock_token")) showLogin(error.message);
  }
}

loadInitialUser();
