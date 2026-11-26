
const API_URL = "http://127.0.0.1:8000";
const SESSION_KEY = "jamrock.inventory.kitchenToken";
let accessToken = sessionStorage.getItem(SESSION_KEY);

async function signInKitchen(username, password) {
    const session = await apiRequest("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password })
    });
    if (session.user?.role !== "Kitchen") {
        throw new Error("Sign in with a Kitchen account.");
    }
    accessToken = session.access_token;
    sessionStorage.setItem(SESSION_KEY, accessToken);
}

async function apiRequest(endpoint, options = {}) {
    const requestToken = endpoint === "/auth/login" ? null : accessToken;

    const response = await fetch(`${API_URL}${endpoint}`, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...options.headers,
            ...(requestToken ? { Authorization: `Bearer ${requestToken}` } : {})
        }
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
        if (response.status === 401 && endpoint !== "/auth/login" && requestToken === accessToken) {
            accessToken = null;
            sessionStorage.removeItem(SESSION_KEY);
            document.dispatchEvent(new Event("inventory-session-ended"));
        }
        throw new Error(data.detail || "Request failed.");
    }

    return data;
}
