// Shared helpers
function mockToast(msg) {
  alert(msg);
}

// CUSTOMER
function searchCustomer() {
  const q = document.getElementById("custSearch").value.trim();
  const out = document.getElementById("custResults");
  if (!q) {
    out.textContent = "Please enter a query.";
    return;
  }
  out.textContent = `Search made for: "${q}". (Hook this to your API)`;
}

// CLIENT
const clientProjects = [];
function addClientProject() {
  const name = document.getElementById("clientProjectName").value.trim();
  const due = document.getElementById("clientDue").value;
  if (!name) return mockToast("Please enter a project name.");
  clientProjects.push({ name, due });
  renderClientProjects();
  document.getElementById("clientProjectName").value = "";
  document.getElementById("clientDue").value = "";
}
function renderClientProjects() {
  const ul = document.getElementById("clientProjectList");
  ul.innerHTML = "";
  clientProjects.forEach((p, i) => {
    const li = document.createElement("li");
    li.className = "list-group-item d-flex justify-content-between align-items-center";
    li.innerHTML = `
      <span><strong>${p.name}</strong>${p.due ? ` · <span class="text-muted">Due: ${p.due}</span>` : ""}</span>
      <button class="btn btn-sm btn-outline-secondary" onclick="removeClientProject(${i})">Remove</button>
    `;
    ul.appendChild(li);
  });
}
function removeClientProject(i) {
  clientProjects.splice(i, 1);
  renderClientProjects();
}

// ADMIN
function resetCache() {
  const log = document.getElementById("adminLog");
  log.textContent = "Cache cleared at " + new Date().toLocaleString();
}
