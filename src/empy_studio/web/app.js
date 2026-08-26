const token = new URLSearchParams(location.search).get("token") || "";
let state = null;
let language = "fa";
let poller = null;
let taskDraft = "";
let taskDraftProjectId = null;

const t = {
  fa: {
    subtitle: "توسعه‌ی پروژه با ایجنت‌های هماهنگ", project: "پروژه‌ها", import: "مسیر پوشه یا ZIP پروژه",
    importButton: "واردکردن پروژه", folder: "انتخاب پوشه", zip: "انتخاب ZIP", tasks: "تیکت جدید", taskHint: "درخواست را مثل توضیح به یک همکار بنویسید…",
    importReview: "بررسی واردسازی پروژه", importedFiles: "فایل قابل‌استفاده", excludedItems: "مورد کنارگذاشته‌شده", importContinue: "فایل اصلی تغییر نکرده است؛ وابستگی‌های موجود برای Verification در کپی ایزوله حفظ شده‌اند و فقط از ZIP نهایی حذف می‌شوند.", importReady: "پروژه آماده‌ی ادامه است", importPartial: "برخی موارد از واردسازی کنار گذاشته شدند؛ دسته‌بندی زیر را بررسی کنید.", verificationReady: "Verification پیش از اجرای Agent آماده است", verificationNeedsAttention: "Empy وابستگی واقعی را قبل از اجرا در کپی ایزوله آماده می‌کند", verificationChecks: "بررسی‌های قابل اجرا", verificationDiagnostics: "علت توقف پیش از اجرا",
    plan: "تحلیل و ساخت برنامه", start: "شروع اجرا", accept: "تأیید تغییرات", revert: "بازگردانی تغییرات", export: "خروجی ZIP پروژه",
    newProject: "پروژه‌ی دیگر", startHere: "از اینجا شروع کنید", projectStartHint: "برای شروع یک پروژه انتخاب کنید یا فایل جدید وارد کنید.", chooseProject: "انتخاب پروژه", reimportProject: "ورود دوبارهٔ پروژه", projectUnavailable: "مسیر این پروژه دیگر وجود ندارد؛ پوشه یا ZIP را دوباره وارد کنید.", noProject: "هنوز پروژه‌ای در این workspace ذخیره نشده است.", noTask: "هنوز تیکتی ثبت نشده است.", engine: "وضعیت Codex",
    ready: "آماده", unavailable: "آماده نیست", files: "فایل مرتبط", tokens: "سقف توکن", run: "در حال اجرا…", cancel: "توقف اجرا", cancelled: "اجرا لغو شد", failed: "اجرا متوقف شد", retryDependency: "تلاش دوباره برای آماده‌سازی وابستگی", dependencyPreparing: "Empy وابستگی‌های واقعی را در کپی ایزوله آماده می‌کند؛ این پوشه وارد ZIP نمی‌شود.", backToTicket: "بازگشت به تیکت", continueTicket: "ادامه و اصلاح تیکت", autoRepair: "اصلاح خودکار و اجرای دوباره", recoverAndContinue: "پاک‌سازی امن و ادامه", manualRepair: "نوشتن تیکت اصلاحی", result: "نتیجه و بررسی", resume: "ادامه تیکت",
    benchmark: "بنچمارک محلی", runBenchmark: "اجرای بنچمارک", full: "تخمین کامل", bounded: "تخمین محدود", saved: "صرفه‌جویی", brain: "Project Brain", report: "گزارش اجرای Agentها", agent: "Agent", duration: "زمان اجرا", summary: "خلاصه", usage: "مصرف Token", actual: "مصرف واقعی", fresh: "مصرف تازه", newTokens: "کار جدید", cached: "Cache", estimate: "تخمین محلی", notReported: "گزارش نشده", verification: "Verification", verificationDiagnostics: "تشخیص‌های Verification", verificationFailures: "خطاهای Verification", review: "Review", pending: "در انتظار تصمیم", evidence: "Evidence", filesChanged: "فایل تغییرکرده", exportReady: "آماده خروجی", readyForExport: "آماده تولید ZIP", releaseGate: "گیت انتشار", blocked: "مسدود", exported: "خروجی تولید شد", reviewPending: "در انتظار تأیید تغییرات", reviewPendingAction: "بررسی‌ها موفق شد؛ فقط تغییرات زیر منتظر تأیید شماست. برای ادامه روی «تأیید تغییرات» بزنید. بعد از تأیید، دکمهٔ «خروجی ZIP پروژه» فعال می‌شود.", verificationBlocked: "Verification ناموفق است", gateReason: "علت توقف", download: "دانلود ZIP", exportManifest: "دانلود فهرست فایل‌ها", exportChecksum: "دانلود checksum", sha256: "SHA-256", changedFilesList: "فایل‌های داخل ZIP", extractionRoot: "ریشهٔ استخراج", revealExport: "نمایش محل فایل", deltaDownloadHint: "این ZIP فقط فایل‌های تغییرکرده را دارد. آن را داخل ریشهٔ دامنه/پروژه در DirectAdmin، یعنی پوشه‌ای که public_html داخل آن است، بارگذاری و همان‌جا Extract کنید؛ فایل‌ها خودکار در مسیر درست می‌نشینند.", noReviewChanges: "تغییری برای تأیید یا بازگردانی وجود ندارد.", noReport: "گزارش اجرا هنوز موجود نیست", noDiagnostic: "جزئیات تشخیصی ثبت نشده است.", nextStep: "قدم بعدی", technicalDetails: "جزئیات فنی (اختیاری)", failureFinding: "یافتهٔ قطعی", requiredAction: "اقدام لازم", failureEvidence: "مسیر evidence", suggestedTicket: "تیکت اصلاحی پیشنهادی", refresh: "به‌روزرسانی وضعیت", openCodex: "بازکردن Codex", engineHelp: "برای اجرای واقعی، Codex باید نصب و احراز هویت شده باشد.", fieldRequired: "درخواست Ticket را وارد کنید.", schedule: "زمان‌بندی", parallel: "موازی", serial: "ترتیبی",
  },
  en: {
    subtitle: "Coordinated project development with bounded agents", project: "Projects", import: "Project folder or ZIP path",
    importButton: "Import project", folder: "Choose folder", zip: "Choose ZIP", tasks: "New ticket", taskHint: "Describe the work as you would to a teammate…",
    importReview: "Project import review", importedFiles: "usable files", excludedItems: "excluded items", importContinue: "The original project was not changed; dependencies already present are preserved for Verification in the isolated copy and excluded only from the final ZIP.", importReady: "Project is ready to continue", importPartial: "Some items were excluded from import; review the categories below.", verificationReady: "Verification is ready before the Agent run", verificationNeedsAttention: "Empy will prepare real dependencies in the isolated copy before running", verificationChecks: "Runnable checks", verificationDiagnostics: "Pre-run blocker",
    plan: "Analyze and build plan", start: "Start run", accept: "Accept changes", revert: "Restore changes", export: "Export project ZIP",
    newProject: "Another project", startHere: "Start here", projectStartHint: "Choose a project or import a new file to get started.", chooseProject: "Choose project", reimportProject: "Re-import project", projectUnavailable: "This project's path is no longer available; choose its folder or ZIP again.", noProject: "No project has been saved in this workspace yet.", noTask: "No tickets have been registered.", engine: "Codex status",
    ready: "Ready", unavailable: "Not ready", files: "Context files", tokens: "Token cap", run: "Running…", cancel: "Stop run", cancelled: "Run cancelled", failed: "Run stopped", retryDependency: "Retry dependency preparation", dependencyPreparing: "Empy prepares real dependencies in the isolated copy; that folder is excluded from the ZIP.", backToTicket: "Back to ticket", continueTicket: "Continue and fix ticket", autoRepair: "Automatically repair and rerun", recoverAndContinue: "Safely reset and continue", manualRepair: "Write a corrective ticket", result: "Result and review", resume: "Resume ticket",
    benchmark: "Local benchmark", runBenchmark: "Run benchmark", full: "Full estimate", bounded: "Bounded estimate", saved: "Saved", brain: "Project Brain", report: "Agent run report", agent: "Agent", duration: "Duration", summary: "Summary", usage: "Token usage", actual: "Actual usage", fresh: "Fresh input", newTokens: "New work", cached: "Cache", estimate: "Local estimate", notReported: "Not reported", verification: "Verification", verificationDiagnostics: "Verification diagnostics", verificationFailures: "Verification failures", review: "Review", pending: "Pending decisions", evidence: "Evidence", filesChanged: "Changed files", exportReady: "Export status", readyForExport: "Ready to create ZIP", releaseGate: "Release gate", blocked: "Blocked", exported: "Export created", reviewPending: "Waiting for change approval", reviewPendingAction: "Verification passed. The listed changes are waiting for your approval. Select Approve changes to continue; the project ZIP becomes available afterwards.", verificationBlocked: "Verification failed", gateReason: "Why export stopped", download: "Download ZIP", exportManifest: "Download file manifest", exportChecksum: "Download checksum", sha256: "SHA-256", changedFilesList: "Files in the ZIP", extractionRoot: "Extraction root", revealExport: "Show file location", deltaDownloadHint: "This ZIP contains changed files only. Upload it into the DirectAdmin domain/project root—the folder that contains public_html—and extract it there; every file will land in its project-relative path.", noReviewChanges: "There are no file changes to accept or restore.", noReport: "Run report is not available yet", noDiagnostic: "No diagnostic details were recorded.", nextStep: "Next step", technicalDetails: "Technical details (optional)", failureFinding: "Confirmed finding", requiredAction: "Required action", failureEvidence: "Evidence path", suggestedTicket: "Suggested corrective ticket", refresh: "Refresh status", openCodex: "Open Codex", engineHelp: "Codex must be installed and authenticated for a real run.", fieldRequired: "Enter a ticket request.", schedule: "Schedule", parallel: "Parallel", serial: "Serial",
  },
};
function text() { return t[language]; }
function escapeHtml(value = "") { return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c])); }
function localizeMessage(value = "") {
  if (value.includes("no writable files for writing roles") || value.includes("no writable files") || value.includes("فایل قابل‌ویرایش") || value.includes("فایل قابل ویرایش") || value.includes("فایل امن و قابل‌ویرایشی") || value.includes("فایل امن و قابل ویرایشی")) {
    return language === "fa"
      ? "این تیکت به فایل قابل‌ویرایش وصل نشد؛ Empy باید فهرست فایل‌های پروژه را دوباره بسازد یا فایل لازم را به‌عنوان هدف امن ایجاد کند. فایل اصلی تغییر نکرده است."
      : "This ticket was not connected to a writable file; Empy must rebuild the project index or create the required file as a safe target. The original project was not changed.";
  }
  if (value.includes("Codex execution requires a clean Git worktree") || value.includes("Commit or restore these paths first")) {
    const marker = "Commit or restore these paths first:";
    const paths = value.includes(marker) ? value.slice(value.indexOf(marker) + marker.length).trim() : "";
    if (language === "fa") {
      return `اجرای مرحلهٔ بعدی متوقف شد چون تلاش قبلی در کپی ایزوله تغییر تأییدنشده دارد${paths ? ` (${paths})` : ""}. فایل اصلی شما تغییر نکرده است؛ Empy می‌تواند این تلاش را امن نگه دارد، کپی ایزوله را به آخرین مبنای تأییدشده برگرداند و ادامه دهد.`;
    }
    return `The next step was paused because the previous attempt left unreviewed changes in the isolated copy${paths ? ` (${paths})` : ""}. Your original project is unchanged; Empy can preserve that attempt, reset only the isolated copy to the last accepted baseline, and continue.`;
  }
  if (value.includes("could not safely preserve the previous isolated changes") || value.includes("isolated workspace is still not clean")) {
    return language === "fa"
      ? "Empy نتوانست تغییرات تلاش قبلی را امن نگه دارد؛ اجرای جدید شروع نشد و فایل اصلی شما تغییر نکرده است. پروژه را دوباره وارد کنید تا یک کپی ایزولهٔ تمیز ساخته شود."
      : "Empy could not safely preserve the previous isolated changes, so it did not start another run and did not change your original project. Re-import the project to create a clean isolated copy.";
  }
  if (value.startsWith("Local link validation failed:")) {
    return language === "fa"
      ? "یک لینک داخلی در فایل تغییرکرده معتبر نیست: " + value.slice("Local link validation failed:".length).trim()
      : value;
  }
  if (value.includes("vendor/autoload.php is missing")) {
    return language === "fa"
      ? "وابستگی‌های Composer هنوز در کپی ایزوله آماده نیست؛ Empy قبل از اجرای Agent آن‌ها را با lockfile واقعی آماده می‌کند."
      : value;
  }
  if (
    value.includes("Dependency preparation blocked")
    || value.includes("Composer is not installed")
    || value.includes("composer.lock is missing")
    || value.includes("package-lock.json is missing")
  ) {
    return language === "fa"
      ? "Empy نتوانست وابستگی واقعی پروژه را آماده کند: " + value.replace("Dependency preparation blocked Verification:", "").trim()
      : value;
  }
  const faMessages = {
    "No changed project files are available for a delta ZIP.": "هیچ فایل تغییرکرده‌ای برای ساخت ZIP وجود ندارد؛ خروجی ناقص ساخته نشد.",
    "The project has deleted file(s); restore them before creating a ZIP.": "پروژه فایل حذف‌شده دارد؛ برای ساخت ZIP ابتدا فایل را برگردانید.",
    "Empy baseline snapshot is missing; re-import the project.": "نسخهٔ پایهٔ پروژه پیدا نشد؛ پروژه را دوباره وارد کنید.",
    "Verification has not run.": "Verification هنوز اجرا نشده است؛ بدون اجرای آن ZIP ساخته نمی‌شود.",
    "Verification has not passed and been finalized.": "Verification موفق و نهایی نشده است؛ ابتدا تست ناموفق را اصلاح و دوباره اجرا کنید.",
    "Review has not been created.": "بررسی تغییرات هنوز ساخته نشده است.",
    "Review has not completed.": "بررسی تغییرات هنوز کامل نشده است.",
    "The agent run did not complete successfully.": "اجرای Agent کامل نشده است؛ قبل از خروجی باید اجرای کامل داشته باشید.",
  };
  const pending = value.match(/^(\d+) changed file\(s\) still need a review decision\.$/);
  if (pending && language === "fa") {
    return `${pending[1]} فایل تغییرکرده هنوز نیاز به تأیید شما دارد؛ ابتدا «تأیید تغییرات» را بزنید.`;
  }
  if (language === "fa") return faMessages[value] || value;
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
    "فایل ZIP فقط شامل فایل‌های تغییرکرده آماده شد.": "A verified change-only deployment ZIP is ready.",
    "خروجی قدیمی کامل بود؛ برای جلوگیری از تحویل ناقص، ZIP تغییرات را دوباره تولید کنید.": "The previous archive was a full legacy export; create the change-only ZIP again before delivery.",
    "هیچ فایل تغییرکرده‌ای برای ساخت ZIP وجود ندارد؛ خروجی ناقص ساخته نشد.": "There are no changed project files for a delta ZIP; no incomplete archive was created.",
    "پروژه فایل حذف‌شده دارد؛ برای ساخت ZIP ابتدا فایل را برگردانید.": "The project has deleted files; restore them before creating a ZIP.",
    "نسخهٔ پایهٔ پروژه برای مقایسه پیدا نشد؛ پروژه را دوباره وارد کنید.": "The project's baseline snapshot is missing; re-import the project.",
    "Verification ناموفق بود؛ یافته‌ها را اصلاح و تیکت را ادامه دهید.": "Verification failed; fix the findings and continue the ticket.",
  };
  const imported = value.match(/^پروژه در یک کپی ایزوله وارد شد؛ (\d+) فایل قابل‌استفاده کپی شد و (\d+) مورد کنارگذاشته‌شده/);
  if (imported) return `Project imported into an isolated copy. ${imported[1]} usable file(s) copied; ${imported[2]} excluded item(s) are explained below.`;
  return messages[value] || value;
}
function importStatusMessage(report) {
  if (!report) return "";
  const readiness = report.verification_readiness || {};
  const diagnostics = readiness.diagnostics || [];
  if (readiness.status === "needs_attention" && diagnostics.length) {
    return language === "fa"
      ? "واردسازی کامل شد؛ Empy پیش از مصرف توکن این پیش‌نیاز را در کپی ایزوله آماده می‌کند: " + diagnostics[0]
      : "Import completed; Empy will prepare this prerequisite in the isolated copy before spending tokens: " + diagnostics[0];
  }
  if (!report.skipped_files) return "";
  if (language === "fa") return `پروژه در یک کپی ایزوله وارد شد؛ ${Number(report.copied_files || 0).toLocaleString()} فایل قابل‌استفاده کپی شد و ${Number(report.skipped_files || 0).toLocaleString()} مورد کنارگذاشته‌شده در بررسی واردسازی توضیح داده شده است.`;
  return `Project imported into an isolated copy. ${Number(report.copied_files || 0).toLocaleString()} usable file(s) copied; ${Number(report.skipped_files || 0).toLocaleString()} excluded item(s) are explained below.`;
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
  notice.textContent = localizeMessage(state?.error || "");
  // A failure context is the authoritative, actionable explanation. Keep a
  // second global banner hidden so the same error is not shown twice.
  notice.classList.toggle("hidden", !state?.error || Boolean(state?.failure_context));
  const message = document.querySelector("#message");
  message.textContent = importStatusMessage(state?.import_report) || localizeMessage(state?.message || "");
  message.className = "message " + (state?.message_level || "info");
  message.classList.toggle("hidden", !state?.message || state?.error);
}
function projectList() {
  const projects = state.projects || [];
  if (!projects.length) {
    return `<p class="muted project-list-empty">${text().noProject}</p>`;
  }
  return projects.map(project => {
    const available = project.available !== false;
    if (!available) {
      return `<div class="project unavailable"><strong>${escapeHtml(project.name)}</strong><small>${text().projectUnavailable}</small><div class="actions"><button type="button" class="secondary" data-action="choose-zip">${text().reimportProject}</button></div></div>`;
    }
    return `<button type="button" class="project ${project.id === state.active_project?.id ? "active" : ""}" data-action="select-project" data-project-id="${escapeHtml(project.id)}"><strong>${escapeHtml(project.name)}</strong><small>${escapeHtml(project.type)} · ${project.tasks.length} ${language === "fa" ? "تیکت" : "tickets"}</small></button>`;
  }).join("");
}
function renderEngine(engine) {
  return `<div class="engine"><div class="row"><strong>${text().engine}: ${engine.ready ? text().ready : text().unavailable}</strong><span class="status-pill ${engine.ready ? "completed" : "failed"}">${engine.ready ? text().ready : text().unavailable}</span></div><small>${escapeHtml(engine.message || "")}</small>${engine.remediation ? `<small class="engine-help">${escapeHtml(engine.remediation)}</small>` : `<small class="engine-help">${text().engineHelp}</small>`}<div class="actions"><button type="button" class="secondary" data-action="refresh-engine">${text().refresh}</button><button type="button" class="secondary" data-action="open-engine">${text().openCodex}</button></div></div>`;
}
function renderProject() {
  const engine = state.engine || {};
  return `<div class="grid"><div class="card start-card"><h1 class="start-title">${text().startHere}</h1><div class="start-hint" style="margin:10px 0 0;padding:12px 14px;border:1px solid #ccefe0;border-radius:12px;background:#effbf6;color:#2f7d5a;font-size:13px;line-height:1.8">${text().projectStartHint}</div><p class="muted start-description">${language === "fa" ? "Empy یک کپی ایزوله می‌سازد و اصل پروژه را تغییر نمی‌دهد." : "Empy creates an isolated copy and never changes the original project."}</p><label class="field-label" for="path">${text().import}</label><input id="path" aria-label="${text().import}" placeholder="${text().import}"><div class="actions"><button type="button" class="secondary" data-action="choose-folder">${text().folder}</button><button type="button" class="secondary" data-action="choose-zip">${text().zip}</button></div></div><div class="card project-card"><h1>${text().project}</h1><div class="project-list">${projectList()}</div><div class="actions project-actions"><button type="button" class="primary" data-action="choose-folder">${text().chooseProject}</button></div>${renderEngine(engine)}</div></div>`;
}
function renderImportReport() {
  const report = state.import_report;
  const readiness = report?.verification_readiness || {};
  if (!report || (!report.skipped_files && readiness.status !== "needs_attention")) return "";
  const labels = language === "fa" ? {
    macos_metadata: "فایل‌های جانبی macOS",
    dependencies: "فایل یا لینک وابستگی که قابل کپی نبوده است",
    git_metadata: "تاریخچه و متادیتای Git",
    sensitive_or_runtime: "فایل‌های حساس یا گزارش‌های اجرایی",
    unsafe_path: "مسیرهای ناامن",
    access_or_copy: "فایل‌های غیرقابل‌خواندن یا کپی‌نشده",
  } : {
    macos_metadata: "macOS metadata",
    dependencies: "Dependency files or links that could not be copied",
    git_metadata: "Git history and metadata",
    sensitive_or_runtime: "Sensitive or runtime files",
    unsafe_path: "Unsafe paths",
    access_or_copy: "Unreadable or uncopied files",
  };
  const rows = Object.entries(report.categories || {}).map(([key, count]) => "<li><span>" + escapeHtml(labels[key] || key) + "</span><strong>" + Number(count).toLocaleString() + "</strong></li>").join("");
  const status = report.status === "partial"
    ? text().importPartial
    : text().importReady;
  const readinessClass = readiness.status === "needs_attention" ? "needs-attention" : "ready";
  const readinessTitle = readiness.status === "needs_attention" ? text().verificationNeedsAttention : text().verificationReady;
  const readinessDetails = readiness.status === "needs_attention"
    ? "<strong>" + text().verificationDiagnostics + "</strong><ul>" + (readiness.diagnostics || []).map(item => "<li><span>" + escapeHtml(item) + "</span></li>").join("") + "</ul>"
    : "<strong>" + text().verificationChecks + "</strong><ul>" + (readiness.checks || []).map(item => "<li><span>" + escapeHtml(item) + "</span></li>").join("") + "</ul>";
  const categoryBlock = report.skipped_files ? "<ul>" + rows + "</ul>" : "";
  return '<section class="import-report warning"><h2>' + text().importReview + '</h2><p>' + escapeHtml(status) + '</p><div class="import-stats"><div><small>' + text().importedFiles + '</small><strong>' + Number(report.copied_files || 0).toLocaleString() + '</strong></div><div><small>' + text().excludedItems + '</small><strong>' + Number(report.skipped_files || 0).toLocaleString() + '</strong></div></div><p class="muted">' + text().importContinue + '</p>' + categoryBlock + '<div class="import-readiness ' + readinessClass + '"><h3>' + readinessTitle + '</h3>' + readinessDetails + '</div></section>';
}
function renderFailureContext(context, compact = false) {
  if (!context) return "";
  const failures = (context.failures || []).map(item => `<article class="failure-item"><div class="row"><strong>${escapeHtml(item.label || text().verification)}</strong>${item.returncode === null || item.returncode === undefined ? "" : `<span class="status-pill failed">exit ${escapeHtml(item.returncode)}</span>`}</div><p class="failure-finding"><strong>${text().failureFinding}:</strong> ${escapeHtml(item.user_finding || item.detail || text().noDiagnostic)}</p><p class="failure-action"><strong>${text().requiredAction}:</strong> ${escapeHtml(item.action || "")}</p></article>`).join("");
  const findings = (context.findings || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
  const evidence = context.evidence ? `<small class="evidence">${text().failureEvidence}: ${escapeHtml(context.evidence)}</small>` : "";
  const suggested = !compact && context.suggested_ticket
    ? `<details class="suggested-ticket"><summary>${text().suggestedTicket}</summary><pre>${escapeHtml(context.suggested_ticket)}</pre></details>`
    : "";
  return `<section class="failure-context ${compact ? "compact" : ""}" role="alert"><h2>${escapeHtml(context.title || "")}</h2><p>${escapeHtml(context.summary || "")}</p>${context.next_step ? `<p class="failure-next-step"><strong>${text().nextStep}:</strong> ${escapeHtml(context.next_step)}</p>` : ""}${failures ? `<div class="failure-list">${failures}</div>` : ""}${!failures && findings ? `<div class="failure-findings"><strong>${text().failureFinding}</strong><ul>${findings}</ul></div>` : ""}${evidence}${suggested}</section>`;
}
function renderRecoveryActions(context) {
  if (!context) return "";
  const primaryAction = context.repair_available ? "auto-repair" : "resume-ticket";
  const primaryLabel = context.kind === "dirty_worktree" && context.repair_available ? text().recoverAndContinue : context.repair_available ? text().autoRepair : text().continueTicket;
  const secondary = primaryAction === "resume-ticket" ? "" : `<button type="button" class="secondary" data-action="resume-ticket">${text().continueTicket}</button>`;
  return `<button type="button" class="primary" data-action="${primaryAction}">${primaryLabel}</button>${secondary}`;
}
function renderTask() {
  const tasks = state.tasks || [];
  const projectId = state.active_project?.id || null;
  const draft = taskDraftProjectId === projectId ? taskDraft : "";
  return `<div class="card"><div class="row"><div><h1>${text().tasks}</h1><p class="muted">${escapeHtml(state.active_project?.name || "")}</p></div><button type="button" class="secondary" data-action="reset-project">${text().newProject}</button></div>${renderFailureContext(state.failure_context)}${state.failure_context ? `<div class="actions failure-actions">${renderRecoveryActions(state.failure_context)}</div>` : ""}<label class="field-label" for="tasks">${text().tasks}</label>${state.failure_context ? `<p class="muted corrective-ticket-hint">${escapeHtml(state.failure_context.next_step || "")}</p>` : ""}<textarea id="tasks" aria-label="${text().tasks}" placeholder="${text().taskHint}">${escapeHtml(draft)}</textarea><div class="actions"><button type="button" class="primary" data-action="build-plan">${text().plan}</button></div><h2>${language === "fa" ? "تاریخچه تیکت‌ها" : "Ticket history"}</h2><div class="task-list">${tasks.length ? tasks.map(task => `<button type="button" class="task ${task.id === state.active_task_id ? "active" : ""}" data-action="select-task" data-task-id="${escapeHtml(task.id)}"><strong>${escapeHtml(task.title)}</strong><small>${escapeHtml(task.status)} · ${text().resume}</small></button>`).join("") : `<p class="muted">${text().noTask}</p>`}</div></div>`;
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
  const labels = language === "fa" ? {completed:"کامل شد", pass:"موفق", failed:"ناموفق", fail:"ناموفق", cancelled:"لغو شد", timed_out:"پایان زمان", unavailable:"در دسترس نیست", skipped:"به‌دلیل توقف مرحلهٔ قبل اجرا نشد", running:"در حال اجرا", waiting:"در انتظار", not_run:"اجرا نشده", ready_for_export:"آماده تولید ZIP", awaiting_review:"در انتظار تأیید تغییرات", blocked:"مسدود", exported:"خروجی تولید شد"} : {completed:"Completed", pass:"Passed", failed:"Failed", fail:"Failed", cancelled:"Cancelled", timed_out:"Timed out", unavailable:"Unavailable", skipped:"Not run (previous step stopped)", running:"Running", waiting:"Waiting", not_run:"Not run", ready_for_export:"Ready to create ZIP", awaiting_review:"Waiting for change approval", blocked:"Blocked", exported:"Export created"};
  return labels[value] || value || "—";
}
function releaseGateLabel(gate, verification, review) {
  if (gate.status === "exported" || gate.exported) return text().exported;
  if (gate.ready) return text().readyForExport;
  if (review?.pending_count) return text().reviewPending;
  if (verification?.status === "fail" || verification?.status === "needs_attention") return text().verificationBlocked;
  return statusLabel(gate.status || "blocked");
}
function renderReleaseGateExplanation(gate, verification, review) {
  const blockers = gate?.blockers || [];
  if (!blockers.length && gate?.ready) return "";
  const waitingForReview = gate?.status === "awaiting_review" && review?.pending_count;
  if (waitingForReview) {
    return `<section class="release-gate-explanation review-waiting" role="status"><strong>${text().nextStep}</strong><p>${escapeHtml(text().reviewPendingAction)}</p></section>`;
  }
  const details = blockers.length
    ? `<ul>${blockers.map(item => `<li>${escapeHtml(localizeMessage(item))}</li>`).join("")}</ul>`
    : `<p>${escapeHtml(releaseGateLabel(gate || {}, verification || {}, review || {}))}</p>`;
  return `<section class="release-gate-explanation" role="alert"><strong>${text().gateReason}</strong>${details}</section>`;
}
function renderUsage(usage) {
  if (!usage) return `<span class="usage unavailable">${text().notReported}</span>`;
  if (!usage.available) return `<span class="usage unavailable">${text().notReported} · ${escapeHtml(usage.source || "not_reported")}</span>`;
  const fresh = usage.fresh_input_tokens === undefined ? "—" : Number(usage.fresh_input_tokens).toLocaleString();
  const newTokens = usage.uncached_total_tokens === undefined ? "—" : Number(usage.uncached_total_tokens).toLocaleString();
  const cached = usage.cached_input_tokens === undefined ? "—" : Number(usage.cached_input_tokens).toLocaleString();
  return `<span class="usage">${text().actual}: ${Number(usage.total_tokens || 0).toLocaleString()} · ${text().fresh}: ${fresh} · ${text().newTokens}: ${newTokens} · ${text().cached}: ${cached} · ${escapeHtml(usage.source || "provider")}</span>`;
}
function renderGuidance(guidance) {
  if (!guidance) return "";
  const steps = (guidance.steps || []).map(step => "<li>" + escapeHtml(step) + "</li>").join("");
  return '<section class="action-guide" role="status"><h3>' + escapeHtml(guidance.title || "") + "</h3><p>" + escapeHtml(guidance.summary || "") + "</p>" + (steps ? "<strong>" + text().nextStep + "</strong><ol>" + steps + "</ol>" : "") + "</section>";
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
  const verification = state.verification || report.verification || {};
  const diagnostics = (verification.diagnostics || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
  const failures = (verification.failures || []).map(item => `<article class="report-error"><strong>${escapeHtml(item.label || item.check_id || "Verification check")}</strong><small>${escapeHtml(item.category || "")}${item.returncode === undefined ? "" : ` · exit ${escapeHtml(item.returncode)}`}</small><p>${escapeHtml(item.detail || text().noDiagnostic)}</p></article>`).join("");
  const verificationDetails = `${diagnostics ? `<section class="verification-details"><h3>${text().verificationDiagnostics}</h3><ul>${diagnostics}</ul></section>` : ""}${failures ? `<section class="verification-details"><h3>${text().verificationFailures}</h3>${failures}</section>` : ""}`;
  const reviewState = state.review;
  const review = reviewState
    ? {pending: reviewState.pending_count || 0, accepted: reviewState.accepted_count || 0, reverted: reviewState.reverted_count || 0, ready: (reviewState.pending_count || 0) === 0}
    : (report.review || {});
  const exported = state.release_gate || report.export || {};
  const exportState = state.export || null;
  const exportVerified = exportState
    ? Boolean(exportState.verified)
    : Boolean(exported.exported || report.export?.verified);
  const exportFileCount = exportState?.file_count ?? report.export?.file_count ?? exported.file_count ?? 0;
  const schedule = report.schedule || [];
  const scheduleText = schedule.length ? schedule.map(item => `${text().schedule} ${item.wave}: ${item.mode === "parallel" ? text().parallel : text().serial} · ${(item.node_ids || []).length}`).join(" · ") : text().notReported;
  const exportStatus = exportVerified ? "✓" : releaseGateLabel(exported, verification, reviewState);
  const exportDetail = exportVerified
    ? `${exportFileCount} ${text().filesChanged}`
    : (report.guidance?.summary || (exported.blockers || []).map(localizeMessage).join(" · ") || releaseGateLabel(exported, verification, reviewState));
  const gateDetails = (exported.blockers || []).map(item => `<li>${escapeHtml(localizeMessage(item))}</li>`).join("");
  const actualNewWork = usage.uncached_total_tokens ?? usage.total_tokens ?? 0;
  const nodeDetails = nodes
    ? `<details class="technical-details"><summary>${text().technicalDetails}</summary><div class="report-node-list">${nodes}</div></details>`
    : `<p class="muted">${text().noReport}</p>`;
  return `<section class="report"><div class="row"><div><h2>${text().report}</h2><p class="muted">${escapeHtml(report.provider || "")} · ${escapeHtml(statusLabel(report.status))}</p></div><strong>${formatDuration(report.duration_seconds)}</strong></div><div class="report-stats"><div><small>${text().newTokens}</small><strong>${usage.available ? Number(actualNewWork).toLocaleString() : "—"}</strong><span>${usage.available ? `${text().actual} · ${escapeHtml(usage.source || "provider")}` : text().notReported}</span></div><div><small>${text().estimate}</small><strong>${estimate}</strong><span>${text().bounded}</span></div><div><small>${text().saved}</small><strong>${savings}</strong><span>${text().benchmark}</span></div><div><small>${text().verification}</small><strong>${escapeHtml(statusLabel(verification.status))}</strong><span>${verification.passed_checks || 0}/${verification.total_checks || 0}</span></div><div><small>${text().review}</small><strong>${review.pending || 0}</strong><span>${text().pending}</span></div><div><small>${text().exportReady}</small><strong>${exportStatus}</strong><span>${escapeHtml(exportDetail)}</span></div></div><p class="muted report-schedule">${escapeHtml(scheduleText)}</p>${gateDetails ? `<section class="verification-details"><h3>${text().releaseGate}</h3><ul>${gateDetails}</ul></section>` : ""}${verificationDetails}${nodeDetails}</section>`;
}
function renderRun() {
  const nodes = state.plan?.nodes || [];
  const title = state.running ? text().run : state.run_status === "cancelled" ? text().cancelled : text().failed;
  const error = state.run_error ? `<p class="muted">${escapeHtml(state.run_error)}</p>` : "";
  const dependency = state.dependency_bootstrap || null;
  const dependencyInfo = dependency?.message
    ? `<section class="dependency-status ${dependency.successful ? "ready" : "blocked"}"><strong>${escapeHtml(dependency.manager || "Dependency")}</strong><p>${escapeHtml(localizeMessage(dependency.message))}</p>${dependency.generated_scope ? `<small>${escapeHtml(dependency.generated_scope)}</small>` : ""}</section>`
    : "";
  const dependencyRetry = dependency?.retryable && !state.running
    ? `<button type="button" class="primary" data-action="start-run">${text().retryDependency}</button>`
    : "";
  const action = state.running
    ? `<button type="button" class="danger" data-action="cancel-run">${text().cancel}</button>`
    : `${dependencyRetry}${state.failure_context ? renderRecoveryActions(state.failure_context) : `<button type="button" class="${dependencyRetry ? "secondary" : "primary"}" data-action="resume-ticket">${text().continueTicket}</button>`}`;
  return `<div class="card"><h1>${title}</h1>${error}${state.failure_context ? renderFailureContext(state.failure_context) : ""}${dependencyInfo}<div class="node-list">${nodes.map(node => `<div class="node ${node.status}"><span>${escapeHtml(statusLabel(node.status))}</span><strong>${escapeHtml(node.title)}</strong></div>`).join("")}</div><pre class="log">${(state.logs || []).map(item => `[${escapeHtml(item.time)}] ${escapeHtml(item.text)}`).join("\n")}</pre><div class="actions">${action}</div></div>`;
}
function enhanceImportUi() {
  if (state?.phase !== "task") return;
  const card = document.querySelector("#screen > .card");
  if (!card || !state?.import_report?.skipped_files) return;
  card.insertAdjacentHTML("afterbegin", renderImportReport());
}
function renderResult() {
  const review = state.review || {files:[], pending_count:0}; const verification = state.verification || {}; const gate = state.release_gate || state.run_report?.export || {};
  const continuation = state.failure_context
    ? renderRecoveryActions(state.failure_context)
    : verification.finalized_at ? "" : `<button type="button" class="primary" data-action="resume-ticket">${text().continueTicket}</button>`;
  const verificationReady = verification.status === "pass" && Boolean(verification.finalized_at || verification.finalized);
  const gateReady = Boolean(gate.ready && verificationReady && state.run_status === "completed");
  const gateStatus = releaseGateLabel(gate, verification, review);
  const gateExplanation = renderReleaseGateExplanation(gate, verification, review);
  const waitingForReview = gate.status === "awaiting_review" || Boolean(review.pending_count && !gateReady);
  const qualityClass = gateReady || gate.status === "exported" ? "pass" : waitingForReview ? "pending" : "fail";
  return `<div class="card"><h1>${text().result}</h1>${renderFailureContext(state.failure_context, true)}${renderRunReport()}<div class="quality ${qualityClass}">${escapeHtml(gateStatus)}</div>${gateExplanation}<div class="file-list">${(review.files || []).map(file => `<div class="file"><strong>${escapeHtml(file.relative_path)}</strong><small>${escapeHtml(file.decision)}</small><pre>${escapeHtml(file.diff_text || "")}</pre></div>`).join("") || `<p class="muted">${language === "fa" ? "تغییری ثبت نشده است. در صورت عبور از گیت، خروجی باید با دکمه زیر تولید شود." : "No changes recorded. If the gate passes, create the ZIP with the button below."}</p>`}</div><div class="actions">${continuation}<button type="button" class="primary" data-action="decide" data-decision="accept" ${review.pending_count ? "" : "disabled"}>${text().accept}</button><button type="button" class="danger" data-action="decide" data-decision="revert" ${review.pending_count ? "" : "disabled"}>${text().revert}</button><button type="button" class="secondary" data-action="export-project" ${gateReady ? "" : "disabled"}>${text().export}</button></div></div>`;
}
function enhanceReportUi() {
  const report = document.querySelector(".report");
  const guidance = state?.run_report?.guidance;
  if (!report) return;
  // The result screen already renders the authoritative failure context. Do
  // not inject the same next-step panel again inside the report.
  if (guidance && !state?.failure_context) report.insertAdjacentHTML("afterbegin", renderGuidance(guidance));
  const technicalNodes = Array.from(report.querySelectorAll(".verification-details"));
  if (!technicalNodes.length) return;
  let details = report.querySelector("details.technical-details");
  if (!details) {
    details = document.createElement("details");
    details.className = "technical-details";
    const summary = document.createElement("summary");
    summary.textContent = text().technicalDetails;
    details.appendChild(summary);
    report.appendChild(details);
  }
  technicalNodes.forEach(node => details.appendChild(node));
}
function renderSaved() {
  const archive = state.export || {};
  const archiveName = archive.archive_name || String(archive.archive_path || "project.zip").split(/[\\/]/).pop();
  const downloadUrl = `/api/export/download?token=${encodeURIComponent(token)}`;
  const manifestUrl = `/api/export/manifest?token=${encodeURIComponent(token)}`;
  const checksumUrl = `/api/export/checksum?token=${encodeURIComponent(token)}`;
  const fileCount = Number(archive.file_count || 0).toLocaleString();
  const changedFiles = (archive.changed_files || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
  const sidecars = `${archive.manifest_available ? `<a class="secondary download-link" href="${manifestUrl}" download="${escapeHtml(archive.manifest_name || "manifest.json")}">${text().exportManifest}</a>` : ""}${archive.checksum_available ? `<a class="secondary download-link" href="${checksumUrl}" download="${escapeHtml(archive.checksum_name || "checksum.sha256")}">${text().exportChecksum}</a>` : ""}`;
  const digest = archive.sha256 ? `<p class="muted export-digest"><strong>${text().sha256}:</strong> <code>${escapeHtml(archive.sha256)}</code></p>` : "";
  const root = archive.extraction_root ? `<p class="muted"><strong>${text().extractionRoot}:</strong> <code>${escapeHtml(archive.extraction_root)}</code></p>` : "";
  const fileList = changedFiles ? `<details class="export-files"><summary>${text().changedFilesList}</summary><ul>${changedFiles}</ul></details>` : "";
  return `<div class="card center"><h1>✓</h1><h2>${language === "fa" ? "خروجی آماده است" : "Export is ready"}</h2><p class="muted">${language === "fa" ? `${fileCount} فایل تغییرکرده در ZIP قرار گرفت.` : `${fileCount} changed file(s) are in the ZIP.`}<br><strong>${escapeHtml(archiveName || "project.zip")}</strong></p><p class="muted export-instructions">${text().deltaDownloadHint}</p>${root}${digest}${fileList}<div class="actions centered-actions"><a class="secondary download-link" href="${downloadUrl}" download="${escapeHtml(archiveName || "project.zip")}">${text().download}</a>${sidecars}<button type="button" class="secondary" data-action="reveal-export">${text().revealExport}</button><button type="button" class="secondary" data-action="reset-project">${text().newProject}</button></div></div>`;
}
function render() {
  if (!state) return; language = state.language || language; banner(); let html = "";
  if (state.export) html = renderSaved(); else if (!state.active_project) html = renderProject(); else if (state.phase === "task") html = renderTask(); else if (state.phase === "plan") html = renderPlan(); else if (state.phase === "run") html = renderRun(); else html = renderResult();
  document.querySelector("#screen").innerHTML = html;
  enhanceReportUi();
  enhanceImportUi();
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
      const field = document.querySelector("#tasks");
      if (field) {
        taskDraft = field.value;
        taskDraftProjectId = state?.active_project?.id || null;
      }
      const tasks = (taskDraftProjectId === (state?.active_project?.id || null) ? taskDraft : "").trim();
      if (!tasks) { state = {...state, error: text().fieldRequired}; render(); break; }
      await runAction(() => api("/api/plan", {tasks}));
      break;
    }
    case "run-benchmark": await runAction(() => api("/api/benchmark", {})); break;
    case "start-run": await runAction(() => api("/api/run", {})); break;
    case "cancel-run": await runAction(() => api("/api/cancel", {})); break;
    case "resume-ticket": await runAction(() => api("/api/resume-ticket", {})); break;
    case "auto-repair": await runAction(() => api("/api/auto-repair", {})); break;
    case "decide": await runAction(() => api("/api/decision", {decision: target.dataset.decision})); break;
    case "export-project": await runAction(() => api("/api/export", {})); break;
    case "reveal-export": await runAction(() => api("/api/reveal-export", {})); break;
    case "reset-project": taskDraft = ""; taskDraftProjectId = null; await runAction(() => api("/api/reset", {})); break;
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
document.querySelector("#screen").addEventListener("input", event => {
  const target = event.target;
  if (target?.id !== "tasks") return;
  taskDraft = target.value;
  taskDraftProjectId = state?.active_project?.id || null;
});
document.querySelector("#screen").addEventListener("keydown", event => {
  const target = event.target;
  if (event.key !== "Enter" || target?.id !== "path") return;
  event.preventDefault();
  void handleAction("import-path", target);
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
