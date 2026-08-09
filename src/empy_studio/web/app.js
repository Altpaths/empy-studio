const token = new URLSearchParams(location.search).get("token") || "";
let state = null;
let language = "fa";
let poller = null;

const t = {
  fa: {
    subtitle: "توسعه‌ی پروژه با ایجنت‌های هماهنگ", project: "پروژه‌ها", import: "مسیر پوشه یا ZIP پروژه",
    importButton: "واردکردن پروژه", folder: "انتخاب پوشه", tasks: "تیکت جدید", taskHint: "درخواست را مثل توضیح به یک همکار بنویسید…",
    plan: "تحلیل و ساخت برنامه", start: "شروع اجرا", accept: "تأیید تغییرات", revert: "بازگردانی تغییرات", export: "خروجی ZIP پروژه",
    newProject: "پروژه‌ی دیگر", noProject: "هنوز پروژه‌ای ثبت نشده است.", noTask: "هنوز تیکتی ثبت نشده است.", engine: "وضعیت Codex",
    ready: "آماده", unavailable: "آماده نیست", files: "فایل مرتبط", tokens: "سقف توکن", run: "در حال اجرا…", result: "نتیجه و بررسی",
  },
  en: {
    subtitle: "Coordinated project development with bounded agents", project: "Projects", import: "Project folder or ZIP path",
    importButton: "Import project", folder: "Choose folder", tasks: "New ticket", taskHint: "Describe the work as you would to a teammate…",
    plan: "Analyze and build plan", start: "Start run", accept: "Accept changes", revert: "Restore changes", export: "Export project ZIP",
    newProject: "Another project", noProject: "No projects have been registered.", noTask: "No tickets have been registered.", engine: "Codex status",
    ready: "Ready", unavailable: "Not ready", files: "Context files", tokens: "Token cap", run: "Running…", result: "Result and review",
  },
};
function text() { return t[language]; }
function escapeHtml(value = "") { return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c])); }
async function api(path, body = null) {
  const options = { headers: { "X-Empy-Token": token } };
  if (body !== null) { options.method = "POST"; options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}
function banner() {
  document.querySelector("#subtitle").textContent = text().subtitle;
  document.querySelector("#language").textContent = language === "fa" ? "English" : "فارسی";
  document.documentElement.lang = language;
  document.documentElement.dir = language === "fa" ? "rtl" : "ltr";
  const notice = document.querySelector("#notice");
  notice.textContent = state?.error || ""; notice.classList.toggle("hidden", !state?.error);
  const message = document.querySelector("#message");
  message.textContent = state?.message || ""; message.classList.toggle("hidden", !state?.message || state?.error);
}
function projectList() {
  const projects = state.projects || [];
  return projects.length ? projects.map(project => `<button class="project ${project.id === state.active_project?.id ? "active" : ""}" onclick="selectProject('${escapeHtml(project.id)}')"><strong>${escapeHtml(project.name)}</strong><small>${escapeHtml(project.type)} · ${project.tasks.length} ${language === "fa" ? "تیکت" : "tickets"}</small></button>`).join("") : `<p class="muted">${text().noProject}</p>`;
}
function renderProject() {
  const engine = state.engine || {};
  return `<div class="grid"><div class="card"><h1>${text().project}</h1><p class="muted">${language === "fa" ? "Empy یک کپی ایزوله می‌سازد و اصل پروژه را تغییر نمی‌دهد." : "Empy creates an isolated copy and never changes the original project."}</p><input id="path" placeholder="${text().import}"><div class="actions"><button class="primary" onclick="importPath()">${text().importButton}</button><button class="secondary" onclick="chooseFolder()">${text().folder}</button></div></div><div class="card"><h2>${text().project}</h2><div class="project-list">${projectList()}</div><div class="engine"><strong>${text().engine}: ${engine.ready ? text().ready : text().unavailable}</strong><small>${escapeHtml(engine.message || "")}</small></div></div></div>`;
}
function renderTask() {
  const tasks = state.tasks || [];
  return `<div class="card"><div class="row"><div><h1>${text().tasks}</h1><p class="muted">${escapeHtml(state.active_project?.name || "")}</p></div><button class="secondary" onclick="resetProject()">${text().newProject}</button></div><textarea id="tasks" placeholder="${text().taskHint}"></textarea><div class="actions"><button class="primary" onclick="buildPlan()">${text().plan}</button></div><h2>${language === "fa" ? "تاریخچه تیکت‌ها" : "Ticket history"}</h2><div class="task-list">${tasks.length ? tasks.map(task => `<div class="task"><strong>${escapeHtml(task.title)}</strong><small>${escapeHtml(task.status)}</small></div>`).join("") : `<p class="muted">${text().noTask}</p>`}</div></div>`;
}
function renderPlan() {
  const plan = state.plan || {}; const nodes = plan.nodes || [];
  return `<div class="card"><h1>${language === "fa" ? "برنامه آماده است" : "Plan is ready"}</h1><div class="stats"><div><small>${text().files}</small><strong>${plan.selected_files || 0}</strong></div><div><small>${text().tokens}</small><strong>${Number(plan.token_limit || 0).toLocaleString()}</strong></div><div><small>${language === "fa" ? "ایجنت" : "agents"}</small><strong>${plan.agents || 0}</strong></div></div><div class="node-list">${nodes.map(node => `<div class="node"><span>${escapeHtml(node.role)}</span><strong>${escapeHtml(node.title)}</strong><small>${node.owned_files?.length || 0} ${text().files}</small></div>`).join("")}</div><div class="actions"><button class="primary" onclick="startRun()" ${state.engine?.ready ? "" : "disabled"}>${text().start}</button><button class="secondary" onclick="goTask()">${language === "fa" ? "ویرایش تیکت" : "Edit ticket"}</button></div></div>`;
}
function renderRun() {
  const nodes = state.plan?.nodes || []; return `<div class="card"><h1>${text().run}</h1><div class="node-list">${nodes.map(node => `<div class="node ${node.status}"><span>${escapeHtml(node.status)}</span><strong>${escapeHtml(node.title)}</strong></div>`).join("")}</div><pre class="log">${(state.logs || []).map(item => `[${escapeHtml(item.time)}] ${escapeHtml(item.text)}`).join("\n")}</pre></div>`;
}
function renderResult() {
  const review = state.review || {files:[], pending_count:0}; const verification = state.verification || {};
  return `<div class="card"><h1>${text().result}</h1><div class="quality ${verification.finalized_at ? "pass" : "fail"}">${verification.finalized_at ? "✓" : "!"} ${escapeHtml(verification.status || "unknown")}</div><div class="file-list">${(review.files || []).map(file => `<div class="file"><strong>${escapeHtml(file.relative_path)}</strong><small>${escapeHtml(file.decision)}</small><pre>${escapeHtml(file.diff_text || "")}</pre></div>`).join("") || `<p class="muted">${language === "fa" ? "تغییری ثبت نشده است." : "No changes recorded."}</p>`}</div><div class="actions"><button class="primary" onclick="decide('accept')">${text().accept}</button><button class="danger" onclick="decide('revert')">${text().revert}</button><button class="secondary" onclick="exportProject()" ${review.pending_count || !verification.finalized_at ? "disabled" : ""}>${text().export}</button></div></div>`;
}
function renderSaved() { return `<div class="card center"><h1>✓</h1><h2>${language === "fa" ? "خروجی آماده است" : "Export is ready"}</h2><p class="muted">${escapeHtml(state.export?.archive_path || "")}</p><button class="secondary" onclick="resetProject()">${text().newProject}</button></div>`; }
function render() {
  if (!state) return; language = state.language || language; banner(); let html = "";
  if (state.export) html = renderSaved(); else if (!state.active_project) html = renderProject(); else if (state.phase === "task") html = renderTask(); else if (state.phase === "plan") html = renderPlan(); else if (state.phase === "run") html = renderRun(); else html = renderResult();
  document.querySelector("#screen").innerHTML = html;
  if (state.running && !poller) poller = setInterval(refresh, 900); if (!state.running && poller) { clearInterval(poller); poller = null; }
}
async function refresh() { try { state = await api("/api/state"); render(); } catch (error) { document.querySelector("#notice").textContent = error.message; document.querySelector("#notice").classList.remove("hidden"); } }
function loading() { document.querySelector("#screen").innerHTML = `<div class="card center"><div class="spinner"></div><p>${language === "fa" ? "لطفاً صبر کنید…" : "Please wait…"}</p></div>`; }
window.importPath = async () => { loading(); try { state = await api("/api/import", {path: document.querySelector("#path").value}); render(); } catch (error) { await refresh(); } };
window.chooseFolder = async () => { loading(); try { state = await api("/api/select-folder", {}); render(); } catch (error) { await refresh(); } };
window.selectProject = async id => { loading(); try { state = await api("/api/project/select", {project_id:id}); render(); } catch (error) { await refresh(); } };
window.buildPlan = async () => { loading(); try { state = await api("/api/plan", {tasks: document.querySelector("#tasks").value}); render(); } catch (error) { await refresh(); } };
window.startRun = async () => { loading(); try { state = await api("/api/run", {}); render(); } catch (error) { await refresh(); } };
window.decide = async decision => { loading(); try { state = await api("/api/decision", {decision}); render(); } catch (error) { await refresh(); } };
window.exportProject = async () => { loading(); try { state = await api("/api/export", {}); render(); } catch (error) { await refresh(); } };
window.goTask = () => { state.phase = "task"; render(); };
window.resetProject = async () => { loading(); try { state = await api("/api/reset", {}); render(); } catch (error) { await refresh(); } };
document.querySelector("#language").onclick = async () => { language = language === "fa" ? "en" : "fa"; try { state = await api("/api/language", {language}); render(); } catch (error) { await refresh(); } };
refresh();
