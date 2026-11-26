let inventoryData = [];


// DISPLAY MESSAGES

function showMessage(message, error = false) {
    const element = document.getElementById("inventoryMessage");
    element.textContent = message;
    element.style.color = error ? "red" : "green";
}


// TABLE HELPERS

function addCell(row, value) {
    const cell = document.createElement("td");
    cell.textContent = value ?? "";
    row.appendChild(cell);
}

function emptyRow(table, columns, message) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");

    cell.colSpan = columns;
    cell.textContent = message;

    row.appendChild(cell);
    table.appendChild(row);
}


// LOAD INVENTORY FROM BACKEND

async function loadInventory() {

    inventoryData = await apiRequest("/inventory");

    const table = document.getElementById("inventoryTable");
    table.replaceChildren();

    inventoryData.forEach(item => {

        const row = document.createElement("tr");

        addCell(row, item.item_id);
        addCell(row, item.name);
        addCell(row, item.quantity);
        addCell(row, item.unit);
        addCell(row, item.reorder_level);

        const status = document.createElement("td");
        status.textContent = item.status;

        status.className =
            item.status === "IN STOCK" ? "good" :
            item.status === "LOW STOCK" ? "warning" : "danger";

        row.appendChild(status);
        table.appendChild(row);
    });

    if (!inventoryData.length) {
        emptyRow(table, 6, "No inventory items found.");
    }

    document.getElementById("totalItems").textContent =
        inventoryData.length;

    document.getElementById("lowCount").textContent =
        inventoryData.filter(x => x.status === "LOW STOCK").length;

    document.getElementById("outCount").textContent =
        inventoryData.filter(x => x.status === "OUT OF STOCK").length;

    populateDropdowns();
}


// POPULATE ITEM DROPDOWNS

function populateDropdowns() {

    ["receiveItem", "removeItem"].forEach(id => {

        const select = document.getElementById(id);
        select.replaceChildren();

        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "Select an item";
        placeholder.disabled = true;
        placeholder.selected = true;

        select.appendChild(placeholder);

        inventoryData.forEach(item => {

            const option = document.createElement("option");

            option.value = item.item_id;
            option.textContent = item.name;

            select.appendChild(option);
        });
    });
}


// ADD INVENTORY ITEM

document.getElementById("addForm")
.addEventListener("submit", async event => {

    event.preventDefault();

    try {

        const body = {
            name: document.getElementById("itemName").value.trim(),
            unit: document.getElementById("itemUnit").value,
            reorder_level: Number(
                document.getElementById("reorderLevel").value
            )
        };

        await apiRequest("/inventory", {
            method: "POST",
            body: JSON.stringify(body)
        });

        event.target.reset();

        showMessage("Inventory item added successfully.");

        await loadInventory();

    } catch (error) {
        showMessage(error.message, true);
    }
});


// RECEIVE STOCK

document.getElementById("receiveForm")
.addEventListener("submit", async event => {

    event.preventDefault();

    try {

        const itemId = document.getElementById("receiveItem").value;

        const body = {
            quantity: Number(
                document.getElementById("receiveQuantity").value
            ),
            expiry_date: document.getElementById("receiveExpiry").value
        };

        await apiRequest(`/inventory/${itemId}/stock`, {
            method: "POST",
            body: JSON.stringify(body)
        });

        event.target.reset();

        showMessage("Stock received successfully.");

        await loadInventory();

    } catch (error) {
        showMessage(error.message, true);
    }
});


// REMOVE STOCK

document.getElementById("removeForm")
.addEventListener("submit", async event => {

    event.preventDefault();

    try {

        const itemId = document.getElementById("removeItem").value;

        const body = {
            quantity: Number(
                document.getElementById("removeQuantity").value
            ),
            reason: document.getElementById("removeReason").value.trim()
        };

        await apiRequest(`/inventory/${itemId}/remove`, {
            method: "POST",
            body: JSON.stringify(body)
        });

        event.target.reset();

        showMessage("Stock removed successfully.");

        await loadInventory();

    } catch (error) {
        showMessage(error.message, true);
    }
});


// LOW STOCK

async function loadLowStock() {

    await loadInventory();

    const table = document.getElementById("lowTable");
    table.replaceChildren();

    const items = inventoryData.filter(item =>
        item.status === "LOW STOCK" ||
        item.status === "OUT OF STOCK"
    );

    items.forEach(item => {

        const row = document.createElement("tr");

        addCell(row, item.name);
        addCell(row, item.quantity);
        addCell(row, item.reorder_level);
        addCell(row, item.status);

        table.appendChild(row);
    });

    if (!items.length) {
        emptyRow(table, 4, "No low-stock items.");
    }
}


// EXPIRY TRACKING


// EXPIRY TRACKING

async function loadExpiry() {

    const items = await apiRequest("/inventory/expiry");

    const table = document.getElementById("expiryTable");
    table.replaceChildren();

    items.forEach(item => {

        const row = document.createElement("tr");

        addCell(row, item.name);
        addCell(row, item.quantity);
        addCell(row, item.expiry_date);
        addCell(row, item.days_left);
        addCell(row, item.status);

        // EXPIRY DATE EDITING

        const editCell = document.createElement("td");

        const dateInput = document.createElement("input");
        dateInput.type = "date";
        dateInput.value = item.expiry_date;
        dateInput.required = true;
        dateInput.setAttribute(
            "aria-label",
            `New expiry date for ${item.name}`
        );

        const saveButton = document.createElement("button");
        saveButton.type = "button";
        saveButton.textContent = "Save";

        saveButton.addEventListener("click", async () => {

            const newExpiry = dateInput.value;

            if (!newExpiry) {
                showMessage("Please select an expiry date.", true);
                return;
            }

            try {

                await apiRequest(
                    `/inventory/lots/${item.lot_id}/expiry`,
                    {
                        method: "PATCH",
                        body: JSON.stringify({
                            expiry_date: newExpiry
                        })
                    }
                );

                showMessage(
                    `${item.name} expiry date updated successfully.`
                );

                // Reload expiry information and days remaining
                await loadExpiry();

            } catch (error) {

                showMessage(error.message, true);

            }
        });

        editCell.appendChild(dateInput);
        editCell.appendChild(saveButton);

        row.appendChild(editCell);

        table.appendChild(row);
    });

    if (!items.length) {
        emptyRow(table, 6, "No expiry records found.");
    }
}



// NAVIGATION

document.querySelectorAll("[data-tab]").forEach(button => {

    button.addEventListener("click", async () => {

        const target = button.dataset.tab;

        document.querySelectorAll(".inventory-tab")
        .forEach(tab => tab.hidden = true);

        document.getElementById(target).hidden = false;

        try {

            if (target === "viewTab") await loadInventory();
            if (target === "lowTab") await loadLowStock();
            if (target === "expiryTab") await loadExpiry();

        } catch (error) {
            showMessage(error.message, true);
        }
    });
});


// REFRESH

document.getElementById("refreshButton")
.addEventListener("click", async () => {

    try {
        await loadInventory();
        showMessage("Inventory refreshed.");
    } catch (error) {
        showMessage(error.message, true);
    }
});


// INITIAL LOAD

const kitchenLogin = document.getElementById("kitchenLogin");
const kitchenLoginForm = document.getElementById("kitchenLoginForm");
const kitchenLoginError = document.getElementById("kitchenLoginError");

function showKitchenLogin() {
    if (!kitchenLogin.open) kitchenLogin.showModal();
}

kitchenLogin.addEventListener("cancel", event => event.preventDefault());
document.addEventListener("inventory-session-ended", showKitchenLogin);
document.addEventListener("DOMContentLoaded", () => {
    if (accessToken) {
        document.querySelector('[data-tab="viewTab"]').click();
    } else {
        showKitchenLogin();
    }
});

kitchenLoginForm.addEventListener("submit", async event => {
    event.preventDefault();
    const submit = kitchenLoginForm.querySelector('button[type="submit"]');
    const { username, password } = kitchenLoginForm.elements;
    kitchenLoginError.textContent = "";
    submit.disabled = true;
    try {
        await signInKitchen(username.value, password.value);
        kitchenLogin.close();
        document.querySelector('[data-tab="viewTab"]').click();
    } catch (error) {
        kitchenLoginError.textContent = error.message;
    } finally {
        password.value = "";
        submit.disabled = false;
    }
});


