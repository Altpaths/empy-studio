const token = new URLSearchParams(location.search).get("token") || "";
let state = null;
let language = "fa";
let poller = null;

const t = {
  fa: {
    subtitle: "توسعه‌ی پروژه با ایجنت‌های هماهنگ", project: "پروژه‌ها", import: "مسیر پوشه یا ZIP پروژه",
    importButton: "واردکردن پروژه", folder: "انتخاب پوشه", zip: "انتخاب ZIP", tasks: "تیکت جدید", taskHint: "درخواست را مثل توضیح به یک همکار بنویسید…",
    plan: "تحلیل و ساخت برنامه", start: "شروع اجرا", accept: "تأیید تغییرات", revert: "بازگردانی تغییرات", export: "خروجی ZIP پروژه",
    newProject: "پروژه‌ی دیگر", noProject: "هنوز پروژه‌ای ثبت نشده است.", noTask: "هنوز تیکتی ثبت نشده است.", engine: "وضعیت Codex",
    ready: "آماده", unavailable: "آماده نیست", files: "فایل مرتبط", tokens: "سقف توکن", run: "در حال اجرا…", cancel: "توقف اجرا", cancelled: "اجرا لغو شد", failed: "اجرا متوقف شد", backToTicket: "بازگشت به تیکت", continueTicket: "ادامه و اصلاح تیکت", result: "نتیجه و بررسی", resume: "ادامه تیکت",
    benchmark: "بنچمارک محلی", runBenchmark: "اجرای بنچمارک", full: "تخمین کامل", bounded: "تخمین محدود", saved: "صرفه‌جویی", brain: "Project Brain", report: "گزارش اجرای Agentها", agent: "Agent", duration: "زمان اجرا", summary: "خلاصه", usage: "مصرف Token", actual: "مصرف واقعی", estimate: "تخمین محلی", notReported: "گزارش نشده", verification: "Verification", verificationDiagnostics: "تشخیص‌های Verification", verificationFailures: "خطاهای Verification", review: "Review", pending: "در انتظار تصمیم", evidence: "Evidence", filesChanged: "فایل تغییرکرده", exportReady: "آماده خروجی", noReport: "گزارش اجرا هنوز موجود نیست", noDiagnostic: "جزئیات تشخیصی ثبت نشده است.", refresh: "به‌روزرسانی وضعیت", openCodex: "بازکردن Codex", engineHelp: "برای اجرای واقعی، Codex باید نصب و احراز هویت شده باشد.", fieldRequired: "درخواست Ticket را وارد کنید.", schedule: "زمان‌بندی", parallel: "موازی", serial: "ترتیبی",
  },
  en: {
    subtitle: "Coordinated project development with bounded agents", project: "Projects", import: "Project folder or ZIP path",
    importButton: "Import project", folder: "Choose folder", zip: "Choose ZIP", tasks: "New ticket", taskHint: "Describe the work as you would to a teammate…",
    plan: "Analyze and build plan", start: "Start run", accept: "Accept changes", revert: "Restore changes", export: "Export project ZIP",
    newProject: "Another project", noProject: "No projects have been registered.", noTask: "No tickets have been registered.", engine: "Codex status",
    ready: "Ready", unavailable: "Not ready", files: "Context files", tokens: "Token cap", run: "Running…", cancel: "Stop run", cancelled: "Run cancelled", failed: "Run stopped", backToTicket: "Back to ticket", continueTicket: "Continue and fix ticket", result: "Result and review", resume: "Resume ticket",
    benchmark: "Local benchmark", runBenchmark: "Run benchmark", full: "Full estimate", bounded: "Bounded estimate", saved: "Saved", brain: "Project Brain", report: "Agent run report", agent: "Agent", duration: "Duration", summary: "Summary", usage: "Token usage", actual: "Actual usage", estimate: "Local estimate", notReported: "Not reported", verification: "Verification", verificationDiagnostics: "Verification diagnostics", verificationFailures: "Verification failures", review: "Review", pending: "Pending decisions", evidence: "Evidence", filesChanged: "Changed files", exportReady: "Export ready", noReport: "Run report is not available yet", noDiagnostic: "No diagnostic details were recorded.", refresh: "Refresh status", openCodex: "Open Codex", engineHelp: "Codex must be installed and authenticated for a real run.", fieldRequired: "Enter a ticket request.", schedule: "Schedule", parallel: "Parallel", serial: "Serial",
  },
};
function text() { return t[language]; }
function escapeHtml(value = "") { return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c])); }
function localizeMessage(value = "") {
  if (language === "fa") return value;
  const messages = {
    "پروژه در یک کپی ایزوله ذخیره شد.": "The project was saved in an isolated copy.",
    "تیکت قبلی بازیابی شد.": "The previous ticket was restored.",
    "تیکت انتخاب شد.": "The ticket was selected.",
    "برنامه و مالکیت فایل‌ها آماده شد.": "The plan and file ownership are ready.",
    "بنچمارک محلی بدون فراخوانی Provider اجرا شد.": "The local benchmark ran without calling a provider.",
    "نتیجه برای Review آماده است.": "The result is ready for review.",
    "یافته‌های شکست قبلی حفظ شد؛ تیکت اصلاحی را وارد کنید.": "Previous failure findings were preserved; enter a corrective ticket.",
    "اجرا لغو شد.": "The run was cancelled.",
    "اجرا متوقف شد.": "The run stopped.",
    "درخواست توقف اجرا ثبت شد.": "The stop request was recorded.",
    "تصمیم روی تغییرات ثبت شد.": "The change decision was recorded.",
    "فایل ZIP تک‌ریشه و قابل استخراج آماده شد.": "A verified single-root ZIP is ready.",
  };
  return messages[value] || value;
}
async function api(path, body = null) {
  const options = { headers: { "X-Empy-Token": token } };
  if (body !== null) { options.method = "POST"; options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}
async function uploadRaw(path, file, headers = {}) {
  const response = await fetch(path, { method: "POST", headers: { "X-Empy-Token": token, ...headers }, body: file });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Upload failed");
  return data;
}
async function uploadFolder(files) {
  if (!files.length) return api("/api/state");
  const started = await api("/api/upload-folder/start", {});
  const uploadId = started.upload_id;
  try {
    for (const file of files) {
      await uploadRaw("/api/upload-folder/file", file, {
        "X-Empy-Upload-Id": uploadId,
        "X-Empy-Relative-Path": encodeURIComponent(file.webkitRelativePath || file.name),
      });
    }
    return api("/api/upload-folder/finish", { upload_id: uploadId });
  } catch (error) {
    await api("/api/upload-folder/cancel", { upload_id: uploadId }).catch(() => {});
    throw error;
  }
}
function banner() {
  document.querySelector("#subtitle").textContent = text().subtitle;
  document.querySelector("#language").textContent = language === "fa" ? "English" : "فارسی";
  document.querySelector("#language").setAttribute("aria-pressed", language === "en" ? "true" : "false");
  document.documentElement.lang = language;
  document.documentElement.dir = language === "fa" ? "rtl" : "ltr";
  const notice = document.querySelector("#notice");
  notice.textContent = localizeMessage(state?.error || ""); notice.classList.toggle("hidden", !state?.error);
  const message = document.querySelector("#message");
  message.textContent = localizeMessage(state?.message || ""); message.classList.toggle("hidden", !state?.message || state?.error);
}
function projectList() {
  const projects = state.projects || [];
  return projects.length ? projects.map(project => `<button type="button" class="project ${project.id === state.active_project?.id ? "active" : ""}" data-action="select-project" data-project-id="${escapeHtml(project.id)}"><strong>${escapeHtml(project.name)}</strong><small>${escapeHtml(project.type)} · ${project.tasks.length} ${language === "fa" ? "تیکت" : "tickets"}</small></button>`).join("") : `<p class="muted">${text().noProject}</p>`;
}
function renderProject() {
  const engine = state.engine || {};
  return `<div class="grid"><div class="card"><h1>${text().project}</h1><p class="muted">${language === "fa" ? "Empy یک کپی ایزوله می‌سازد و اصل پروژه را تغییر نمی‌دهد." : "Empy creates an isolated copy and never changes the original project."}</p><label class="field-label" for="path">${text().import}</label><input id="path" aria-label="${text().import}" placeholder="${text().import}"><div class="actions"><button type="button" class="primary" data-action="import-path">${text().importButton}</button><button type="button" class="secondary" data-action="choose-folder">${text().folder}</button><button type="button" class="secondary" data-action="choose-zip">${text().zip}</button></div></div><div class="card"><h2>${text().project}</h2><div class="project-list">${projectList()}</div><div class="engine"><div class="row"><strong>${text().engine}: ${engine.ready ? text().ready : text().unavailable}</strong><span class="status-pill ${engine.ready ? "completed" : "failed"}">${engine.ready ? text().ready : text().unavailable}</span></div><small>${escapeHtml(engine.message || "")}</small>${engine.remediation ? `<small class="engine-help">${escapeHtml(engine.remediation)}</small>` : `<small class="engine-help">${text().engineHelp}</small>`}<div class="actions"><button type="button" class="secondary" data-action="refresh-engine">${text().refresh}</button><button type="button" class="secondary" data-action="open-engine">${text().openCodex}</button></div></div></div></div>`;
}
function renderTask() {
  const tasks = state.tasks || [];
  return `<div class="card"><div class="row"><div><h1>${text().tasks}</h1><p class="muted">${escapeHtml(state.active_project?.name || "")}</p></div><button type="button" class="secondary" data-action="reset-project">${text().newProject}</button></div><label class="field-label" for="tasks">${text().tasks}</label><textarea id="tasks" aria-label="${text().tasks}" placeholder="${text().taskHint}"></textarea><div class="actions"><button type="button" class="primary" data-action="build-plan">${text().plan}</button></div><h2>${language === "fa" ? "تاریخچه تیکت‌ها" : "Ticket history"}</h2><div class="task-list">${tasks.length ? tasks.map(task => `<button type="button" class="task ${task.id === state.active_task_id ? "active" : ""}" data-action="select-task" data-task-id="${escapeHtml(task.id)}"><strong>${escapeHtml(task.title)}</strong><small>${escapeHtml(task.status)} · ${text().resume}</small></button>`).join("") : `<p class="muted">${text().noTask}</p>`}</div></div>`;
}
function renderPlan() {
  const plan = state.plan || {}; const nodes = plan.nodes || [];
  return `<div class="card"><h1>${language === "fa" ? "برنامه آماده است" : "Plan is ready"}</h1><div class="stats"><div><small>${text().files}</small><strong>${plan.selected_files || 0}</strong></div><div><small>${text().tokens}</small><strong>${Number(plan.token_limit || 0).toLocaleString()}</strong></div><div><small>${language === "fa" ? "ایجنت" : "agents"}</small><strong>${plan.agents || 0}</strong></div></div>${renderBenchmark()}<div class="node-list">${nodes.map(node => `<div class="node"><span>${escapeHtml(node.role)}</span><strong>${escapeHtml(node.title)}</strong><small>${node.owned_files?.length || 0} ${text().files}</small></div>`).join("")}</div><div class="actions"><button type="button" class="primary" data-action="start-run" ${state.engine?.ready ? "" : "disabled"}>${text().start}</button><button type="button" class="secondary" data-action="run-benchmark">${text().runBenchmark}</button><button type="button" class="secondary" data-action="go-task">${language === "fa" ? "ویرایش تیکت" : "Edit ticket"}</button></div></div>`;
}
function renderBenchmark() {
  const brain = state.brain || {}; const budget = state.budget || {}; const benchmark = state.benchmark || null; const usage = state.provider_usage || {};
  const rows = benchmark ? `<div><small>${text().full}</small><strong>${Number(benchmark.full_context_estimate_tokens || 0).toLocaleString()}</strong></div><div><small>${text().bounded}</small><strong>${Number(benchmark.bounded_context_estimate_tokens || budget.estimated_context_tokens || 0).toLocaleString()}</strong></div><div><small>${text().saved}</small><strong>${Number(benchmark.saved_tokens || 0).toLocaleString()} · ${Number(benchmark.savings_percentage || 0).toLocaleString()}%</strong></div>` : `<div><small>${text().brain}</small><strong>${Number(brain.file_count || 0).toLocaleString()}</strong></div><div><small>${text().bounded}</small><strong>${Number(budget.estimated_context_tokens || 0).toLocaleString()}</strong></div><div><small>${language === "fa" ? "مصرف واقعی" : "Actual usage"}</small><strong>${usage.available ? Number(usage.total_tokens || 0).toLocaleString() : "—"}</strong></div>`;
  return `<section class="benchmark"><div class="row"><div><h2>${text().benchmark}</h2><p class="muted">${language === "fa" ? "تخمین محلی و بدون Provider؛ فقط مسیرهای نسبی امن نمایش داده می‌شود." : "Local provider-free estimate; only safe relative paths are shown."}</p></div><small>${escapeHtml((benchmark?.source_estimate || budget.source || state.estimate_source || ""))}</small></div><div class="stats">${rows}</div></section>`;
}
function formatDuration(value) {
  if (value === null || value === undefined) return "—";
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return "—";
  return `${seconds.toLocaleString(undefined, {maximumFractionDigits: 2})}s`;
}
function statusLabel(value) {
  const labels = language === "fa" ? {completed:"کامل شد", failed:"ناموفق", cancelled:"لغو شد", timed_out:"پایان زمان", unavailable:"در دسترس نیست", skipped:"رد شد", running:"در حال اجرا", waiting:"در انتظار", not_run:"اجرا نشده"} : {completed:"Completed", failed:"Failed", cancelled:"Cancelled", timed_out:"Timed out", unavailable:"Unavailable", skipped:"Skipped", running:"Running", waiting:"Waiting", not_run:"Not run"};
  return labels[value] || value || "—";
}
function renderUsage(usage) {
  if (!usage) return `<span class="usage unavailable">${text().notReported}</span>`;
  if (!usage.available) return `<span class="usage unavailable">${text().notReported} · ${escapeHtml(usage.source || "not_reported")}</span>`;
  return `<span class="usage">${text().actual}: ${Number(usage.total_tokens || 0).toLocaleString()} · ${escapeHtml(usage.source || "provider")}</span>`;
}
function renderRunReport() {
  const report = state.run_report;
  if (!report) return `<section class="report"><h2>${text().report}</h2><p class="muted">${text().noReport}</p></section>`;
  const usage = report.usage || {};
  const estimates = report.estimates || {};
  const nodes = (report.nodes || []).map(node => {
    const evidence = node.evidence ? Object.values(node.evidence).filter(Boolean).join(" · ") : "";
    return `<article class="report-node"><div class="row"><div><strong>${escapeHtml(node.title || node.id)}</strong><small>${escapeHtml(node.agent_id || "")} · ${escapeHtml(node.role || "")}</small></div><span class="status-pill ${escapeHtml(node.status || "waiting")}">${escapeHtml(statusLabel(node.status))}</span></div><div class="report-meta"><span>${text().duration}: ${formatDuration(node.duration_seconds)}</span><span>${text().filesChanged}: ${(node.changed_files || []).length}</span><span>${text().usage}: ${renderUsage(node.usage)}</span></div><p class="muted report-summary">${escapeHtml(node.summary || "")}</p>${node.error ? `<p class="report-error">${escapeHtml(node.error)}</p>` : ""}${evidence ? `<small class="evidence">${text().evidence}: ${escapeHtml(evidence)}</small>` : ""}</article>`;
  }).join("");
  const estimate = estimates.bounded_context_tokens === null || estimates.bounded_context_tokens === undefined ? "—" : Number(estimates.bounded_context_tokens).toLocaleString();
  const savings = estimates.savings_percentage === null || estimates.savings_percentage === undefined ? "—" : `${Number(estimates.savings_percentage).toLocaleString()}%`;
  const verification = report.verification || {};
  const diagnostics = (verification.diagnostics || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
  const failures = (verification.failures || []).map(item => `<article class="report-error"><strong>${escapeHtml(item.label || item.check_id || "Verification check")}</strong><small>${escapeHtml(item.category || "")}${item.returncode === undefined ? "" : ` · exit ${escapeHtml(item.returncode)}`}</small><p>${escapeHtml(item.detail || text().noDiagnostic)}</p></article>`).join("");
  const verificationDetails = `${diagnostics ? `<section class="verification-details"><h3>${text().verificationDiagnostics}</h3><ul>${diagnostics}</ul></section>` : ""}${failures ? `<section class="verification-details"><h3>${text().verificationFailures}</h3>${failures}</section>` : ""}`;
  const review = report.review || {};
  const exported = report.export || {};
  const schedule = report.schedule || [];
  const scheduleText = schedule.length ? schedule.map(item => `${text().schedule} ${item.wave}: ${item.mode === "parallel" ? text().parallel : text().serial} · ${(item.node_ids || []).length}`).join(" · ") : text().notReported;
  return `<section class="report"><div class="row"><div><h2>${text().report}</h2><p class="muted">${escapeHtml(report.provider || "")} · ${escapeHtml(statusLabel(report.status))}</p></div><strong>${formatDuration(report.duration_seconds)}</strong></div><div class="report-stats"><div><small>${text().actual}</small><strong>${usage.available ? Number(usage.total_tokens || 0).toLocaleString() : "—"}</strong><span>${usage.available ? escapeHtml(usage.source || "provider") : text().notReported}</span></div><div><small>${text().estimate}</small><strong>${estimate}</strong><span>${text().bounded}</span></div><div><small>${text().saved}</small><strong>${savings}</strong><span>${text().benchmark}</span></div><div><small>${text().verification}</small><strong>${escapeHtml(statusLabel(verification.status))}</strong><span>${verification.passed_checks || 0}/${verification.total_checks || 0}</span></div><div><small>${text().review}</small><strong>${review.pending || 0}</strong><span>${text().pending}</span></div><div><small>${text().exportReady}</small><strong>${exported.verified ? "✓" : "—"}</strong><span>${exported.file_count || 0} ${text().files}</span></div></div><p class="muted report-schedule">${escapeHtml(scheduleText)}</p>${verificationDetails}<div class="report-node-list">${nodes || `<p class="muted">${text().noReport}</p>`}</div></section>`;
}
function renderRun() {
  const nodes = state.plan?.nodes || [];
  const title = state.running ? text().run : state.run_status === "cancelled" ? text().cancelled : text().failed;
  const error = state.run_error ? `<p class="muted">${escapeHtml(state.run_error)}</p>` : "";
  const action = state.running
    ? `<button type="button" class="danger" data-action="cancel-run">${text().cancel}</button>`
    : `<button type="button" class="primary" data-action="resume-ticket">${text().continueTicket}</button>`;
  return `<div class="card"><h1>${title}</h1>${error}<div class="node-list">${nodes.map(node => `<div class="node ${node.status}"><span>${escapeHtml(node.status)}</span><strong>${escapeHtml(node.title)}</strong></div>`).join("")}</div><pre class="log">${(state.logs || []).map(item => `[${escapeHtml(item.time)}] ${escapeHtml(item.text)}`).join("\n")}</pre><div class="actions">${action}</div></div>`;
}
function renderResult() {
  const review = state.review || {files:[], pending_count:0}; const verification = state.verification || {};
  const continuation = verification.finalized_at ? "" : `<button type="button" class="primary" data-action="resume-ticket">${text().continueTicket}</button>`;
  return `<div class="card"><h1>${text().result}</h1>${renderRunReport()}<div class="quality ${verification.finalized_at ? "pass" : "fail"}">${verification.finalized_at ? "✓" : "!"} ${escapeHtml(verification.status || "unknown")}</div><div class="file-list">${(review.files || []).map(file => `<div class="file"><strong>${escapeHtml(file.relative_path)}</strong><small>${escapeHtml(file.decision)}</small><pre>${escapeHtml(file.diff_text || "")}</pre></div>`).join("") || `<p class="muted">${language === "fa" ? "تغییری ثبت نشده است." : "No changes recorded."}</p>`}</div><div class="actions">${continuation}<button type="button" class="primary" data-action="decide" data-decision="accept" ${review.pending_count ? "" : "disabled"}>${text().accept}</button><button type="button" class="danger" data-action="decide" data-decision="revert" ${review.pending_count ? "" : "disabled"}>${text().revert}</button><button type="button" class="secondary" data-action="export-project" ${review.pending_count || !verification.finalized_at ? "disabled" : ""}>${text().export}</button></div></div>`;
}
function renderSaved() { return `<div class="card center"><h1>✓</h1><h2>${language === "fa" ? "خروجی آماده است" : "Export is ready"}</h2><p class="muted">${escapeHtml(state.export?.archive_path || "")}</p><button type="button" class="secondary" data-action="reset-project">${text().newProject}</button></div>`; }
function render() {
  if (!state) return; language = state.language || language; banner(); let html = "";
  if (state.export) html = renderSaved(); else if (!state.active_project) html = renderProject(); else if (state.phase === "task") html = renderTask(); else if (state.phase === "plan") html = renderPlan(); else if (state.phase === "run") html = renderRun(); else html = renderResult();
  document.querySelector("#screen").innerHTML = html;
  document.querySelector("#screen").setAttribute("aria-busy", "false");
  if (state.running && !poller) poller = setInterval(refresh, 900); if (!state.running && poller) { clearInterval(poller); poller = null; }
}
async function refresh() { try { state = await api("/api/state"); render(); } catch (error) { document.querySelector("#notice").textContent = localizeMessage(error.message); document.querySelector("#notice").classList.remove("hidden"); } }
function loading() { document.querySelector("#screen").setAttribute("aria-busy", "true"); document.querySelector("#screen").innerHTML = `<div class="card center"><div class="spinner" role="progressbar" aria-label="${language === "fa" ? "در حال پردازش" : "Processing"}"></div><p>${language === "fa" ? "لطفاً صبر کنید…" : "Please wait…"}</p></div>`; }
async function runAction(action) {
  loading();
  try { state = await action(); render(); } catch (error) { await refresh(); }
}
async function handleAction(action, target) {
  switch (action) {
    case "import-path": {
      const path = document.querySelector("#path")?.value.trim() || "";
      await runAction(() => api("/api/import", {path}));
      break;
    }
    case "choose-folder": {
      const input = document.querySelector("#folder-upload");
      if (input) { input.value = ""; input.click(); }
      break;
    }
    case "choose-zip": {
      const input = document.querySelector("#zip-upload");
      if (input) { input.value = ""; input.click(); }
      break;
    }
    case "refresh-engine": await runAction(() => api("/api/refresh-engine", {})); break;
    case "open-engine": await runAction(() => api("/api/open-engine", {})); break;
    case "select-project": await runAction(() => api("/api/project/select", {project_id: target.dataset.projectId})); break;
    case "select-task": await runAction(() => api("/api/task/select", {task_id: target.dataset.taskId})); break;
    case "build-plan": {
      const tasks = document.querySelector("#tasks")?.value.trim() || "";
      if (!tasks) { state = {...state, error: text().fieldRequired}; render(); break; }
      await runAction(() => api("/api/plan", {tasks}));
      break;
    }
    case "run-benchmark": await runAction(() => api("/api/benchmark", {})); break;
    case "start-run": await runAction(() => api("/api/run", {})); break;
    case "cancel-run": await runAction(() => api("/api/cancel", {})); break;
    case "resume-ticket": await runAction(() => api("/api/resume-ticket", {})); break;
    case "decide": await runAction(() => api("/api/decision", {decision: target.dataset.decision})); break;
    case "export-project": await runAction(() => api("/api/export", {})); break;
    case "reset-project": await runAction(() => api("/api/reset", {})); break;
    case "go-task": state.phase = "task"; render(); break;
    default: break;
  }
}
document.querySelector("#screen").addEventListener("click", event => {
  const target = event.target instanceof Element ? event.target.closest("[data-action]") : null;
  if (!target || target.disabled) return;
  event.preventDefault();
  void handleAction(target.dataset.action, target);
});
document.querySelector("#language").addEventListener("click", () => {
  language = language === "fa" ? "en" : "fa";
  void runAction(() => api("/api/language", {language}));
});
document.querySelector("#folder-upload").addEventListener("change", event => {
  const files = Array.from(event.target.files || []);
  void runAction(() => uploadFolder(files));
});
document.querySelector("#zip-upload").addEventListener("change", event => {
  const file = event.target.files?.[0];
  if (!file) return;
  void runAction(() => uploadRaw("/api/upload-zip", file, { "X-Empy-Filename": encodeURIComponent(file.name) }));
});
refresh();
