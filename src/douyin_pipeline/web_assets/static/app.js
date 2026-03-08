const state = {
  currentView: "task-center",
  selectedJobId: null,
  selectedJob: null,
  doctor: [],
  dashboard: {
    jobs: [],
    summary: null,
    totalJobs: 0,
  },
  history: {
    jobs: [],
    offset: 0,
    limit: 20,
    filteredTotal: 0,
    totalJobs: 0,
    hasMore: false,
    summary: null,
    q: "",
    status: "",
    action: "",
    activeOnly: false,
  },
  telegram: null,
  jobCache: new Map(),
  pollTimer: null,
};

const elements = {
  flash: document.getElementById("flash"),
  submitBtn: document.getElementById("submitBtn"),
  jobForm: document.getElementById("jobForm"),
  dashboardSummary: document.getElementById("dashboardSummary"),
  dashboardJobsList: document.getElementById("dashboardJobsList"),
  historySummary: document.getElementById("historySummary"),
  historyList: document.getElementById("historyList"),
  historyFilters: document.getElementById("historyFilters"),
  historySearchInput: document.getElementById("historySearchInput"),
  historyStatusInput: document.getElementById("historyStatusInput"),
  historyActionInput: document.getElementById("historyActionInput"),
  historyActiveOnlyInput: document.getElementById("historyActiveOnlyInput"),
  historyPrevBtn: document.getElementById("historyPrevBtn"),
  historyNextBtn: document.getElementById("historyNextBtn"),
  historyPager: document.getElementById("historyPager"),
  doctorList: document.getElementById("doctorList"),
  detailPanel: document.getElementById("detailPanel"),
  telegramForm: document.getElementById("telegramForm"),
  telegramRuntimeBadge: document.getElementById("telegramRuntimeBadge"),
  telegramRuntimeInfo: document.getElementById("telegramRuntimeInfo"),
  telegramEnabledInput: document.getElementById("telegramEnabledInput"),
  telegramTokenInput: document.getElementById("telegramTokenInput"),
  telegramTokenHint: document.getElementById("telegramTokenHint"),
  telegramClearTokenInput: document.getElementById("telegramClearTokenInput"),
  telegramAllowedChatIdsInput: document.getElementById("telegramAllowedChatIdsInput"),
  telegramPublicBaseUrlInput: document.getElementById("telegramPublicBaseUrlInput"),
  telegramPollTimeoutInput: document.getElementById("telegramPollTimeoutInput"),
  telegramRetryDelayInput: document.getElementById("telegramRetryDelayInput"),
  telegramProgressUpdatesInput: document.getElementById("telegramProgressUpdatesInput"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function showFlash(message, type = "info") {
  elements.flash.textContent = message;
  elements.flash.className = `flash ${type}`;
  elements.flash.classList.remove("hidden");
}

function hideFlash() {
  elements.flash.textContent = "";
  elements.flash.className = "flash hidden";
}

function setBusy(isBusy) {
  elements.submitBtn.disabled = isBusy;
  elements.submitBtn.textContent = isBusy ? "创建任务中..." : "开始处理";
}

function isActiveStatus(status) {
  return ["queued", "downloading", "transcribing", "running"].includes(status);
}

function statusClass(status) {
  if (status === "success" || status === "ok") return "status-success";
  if (isActiveStatus(status)) return "status-running";
  return "status-error";
}

function formatAction(action) {
  return action === "run" ? "下载 + 转文字" : "只下载";
}

function formatStatus(status) {
  return (
    {
      queued: "排队中",
      downloading: "下载中",
      transcribing: "转写中",
      success: "已完成",
      error: "失败",
    }[status] || status || "-"
  );
}

function formatPhase(phase, status) {
  return (
    {
      queued: "等待处理",
      downloading: "下载中",
      extracting_audio: "提取音频",
      loading_model: "加载模型",
      transcribing: "转写中",
      writing_transcript: "写入文本",
      completed: "已完成",
      failed: "失败",
    }[phase] ||
    {
      queued: "等待处理",
      downloading: "下载中",
      transcribing: "转写中",
      success: "已完成",
      error: "失败",
    }[status] ||
    phase ||
    status ||
    "-"
  );
}

function formatClock(value) {
  const seconds = Math.max(0, Math.round(Number(value) || 0));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
  }

  return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
}

function formatEta(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "预计剩余时间计算中";
  }
  return `预计剩余 ${formatClock(seconds)}`;
}

function getProgressPercent(job) {
  if (Number.isFinite(job?.progress_percent)) {
    return Math.max(0, Math.min(100, Number(job.progress_percent)));
  }
  if (job?.status === "success") {
    return 100;
  }
  return null;
}

function buildProgress(job, compact = false) {
  if (!job) return "";

  const progressPercent = getProgressPercent(job);
  const hasTiming =
    Number.isFinite(job?.processed_seconds) &&
    Number.isFinite(job?.duration_seconds) &&
    Number(job.duration_seconds) > 0;

  if (progressPercent === null && !hasTiming && !isActiveStatus(job.status)) {
    return "";
  }

  const percentText = progressPercent === null ? "--" : `${Math.round(progressPercent)}%`;
  const phaseText = formatPhase(job.phase, job.status);
  const leftText = hasTiming
    ? `已处理 ${formatClock(job.processed_seconds)} / ${formatClock(job.duration_seconds)}`
    : escapeHtml(job.detail || phaseText);
  const rightText = isActiveStatus(job.status)
    ? formatEta(Number(job.eta_seconds))
    : progressPercent === 100
      ? "处理完成"
      : "";

  return `
    <div class="progress-block${compact ? " compact" : ""}">
      <div class="progress-topline">
        <span>${escapeHtml(phaseText)}</span>
        <strong>${escapeHtml(percentText)}</strong>
      </div>
      <div class="progress-track" aria-hidden="true">
        <span class="progress-fill" style="width:${progressPercent ?? 0}%"></span>
      </div>
      <div class="progress-meta">
        <span>${leftText}</span>
        <span>${escapeHtml(rightText)}</span>
      </div>
    </div>
  `;
}

function formatApiError(data, fallback) {
  const detail = typeof data?.detail === "string" && data.detail ? data.detail : fallback;
  const hint = typeof data?.error_hint === "string" && data.error_hint ? data.error_hint : "";
  return [detail, hint].filter(Boolean).join(" ");
}

function rememberJobs(jobs) {
  jobs.forEach((job) => {
    state.jobCache.set(job.job_id, job);
  });
}

function rememberJob(job) {
  if (!job?.job_id) return;
  state.jobCache.set(job.job_id, job);
}

function jobById(jobId) {
  return state.jobCache.get(jobId) || null;
}

function buildSummaryCards(summary) {
  if (!summary) {
    return `<article class="summary-card muted"><strong>暂无统计</strong><span>等待数据</span></article>`;
  }

  const cards = [
    ["总任务", summary.total, "neutral"],
    ["进行中", summary.active, summary.active > 0 ? "running" : "neutral"],
    ["已完成", summary.success, summary.success > 0 ? "success" : "neutral"],
    ["失败", summary.error, summary.error > 0 ? "error" : "neutral"],
    ["待转写", summary.download_only, summary.download_only > 0 ? "warning" : "neutral"],
    ["已有文本", summary.with_transcript, summary.with_transcript > 0 ? "success" : "neutral"],
  ];

  return cards
    .map(
      ([label, value, tone]) => `
        <article class="summary-card ${tone}">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
        </article>
      `
    )
    .join("");
}

function buildJobActions(job, { includeDelete = false } = {}) {
  const actions = [
    `<button class="ghost-button small" type="button" data-job-action="view" data-job-id="${escapeHtml(job.job_id)}">查看</button>`,
  ];

  if (job.can_transcribe) {
    actions.push(
      `<button class="ghost-button small" type="button" data-job-action="transcribe" data-job-id="${escapeHtml(job.job_id)}">转文字</button>`
    );
  }

  if (includeDelete && job.can_delete) {
    actions.push(
      `<button class="ghost-button small danger" type="button" data-job-action="delete" data-job-id="${escapeHtml(job.job_id)}">删除</button>`
    );
  }

  return `<div class="job-actions">${actions.join("")}</div>`;
}

function buildJobCard(job, { includeDelete = false } = {}) {
  return `
    <article class="job-card ${state.selectedJobId === job.job_id ? "selected" : ""}">
      <div class="job-top">
        <strong>${escapeHtml(job.title || job.job_id)}</strong>
        <span class="status-pill ${statusClass(job.status)}">${escapeHtml(formatStatus(job.status))}</span>
      </div>
      <div class="job-meta">
        <span>${escapeHtml(formatAction(job.action))}</span>
        <span>${escapeHtml(job.created_at || "-")}</span>
      </div>
      <div class="job-path">${escapeHtml(job.source_url || job.job_id)}</div>
      <div class="doctor-detail">${escapeHtml(job.detail || "")}</div>
      ${buildProgress(job, true)}
      ${buildJobActions(job, { includeDelete })}
    </article>
  `;
}

function renderDashboard() {
  elements.dashboardSummary.innerHTML = buildSummaryCards(state.dashboard.summary);

  if (!state.dashboard.jobs.length) {
    elements.dashboardJobsList.innerHTML = `
      <div class="empty-state small-empty">
        <strong>还没有任务</strong>
        <p>先在左侧发起第一条下载或转写任务。</p>
      </div>
    `;
    return;
  }

  elements.dashboardJobsList.innerHTML = state.dashboard.jobs
    .map((job) => buildJobCard(job, { includeDelete: false }))
    .join("");
}

function renderHistory() {
  elements.historySummary.innerHTML = buildSummaryCards(state.history.summary);

  if (!state.history.jobs.length) {
    elements.historyList.innerHTML = `
      <div class="empty-state small-empty">
        <strong>没有匹配结果</strong>
        <p>调整筛选条件，或者去任务中心创建新的任务。</p>
      </div>
    `;
  } else {
    elements.historyList.innerHTML = state.history.jobs
      .map((job) => buildJobCard(job, { includeDelete: true }))
      .join("");
  }

  const page = Math.floor(state.history.offset / state.history.limit) + 1;
  const totalPages = Math.max(1, Math.ceil((state.history.filteredTotal || 0) / state.history.limit));
  elements.historyPager.textContent = `第 ${page} 页 / 共 ${totalPages} 页 · ${state.history.filteredTotal} 条`;
  elements.historyPrevBtn.disabled = state.history.offset <= 0;
  elements.historyNextBtn.disabled = !state.history.hasMore;
}

function renderDoctor() {
  if (!state.doctor.length) {
    elements.doctorList.innerHTML = `<div class="empty-state small-empty"><strong>暂无环境信息</strong></div>`;
    return;
  }

  elements.doctorList.innerHTML = state.doctor
    .map(
      (item) => `
        <article class="doctor-item">
          <div class="doctor-top">
            <strong>${escapeHtml(item.name)}</strong>
            <span class="status-pill ${item.ok ? "status-success" : "status-error"}">${item.ok ? "OK" : "FAIL"}</span>
          </div>
          <div class="doctor-detail">${escapeHtml(item.detail)}</div>
        </article>
      `
    )
    .join("");
}

function buildErrorHint(job) {
  if (!job) return "";

  if (job.error_hint) {
    return `<p class="result-copy">提示：${escapeHtml(job.error_hint)}</p>`;
  }

  const errorText = String(job.technical_error || job.error || "");
  if (!errorText) return "";

  if (errorText.includes("Fresh cookies")) {
    return `<p class="result-copy">提示：这条链接需要更新后的浏览器 cookies。先在浏览器里打开视频确认能播放，再回到这里重试。</p>`;
  }

  if (errorText.includes("Could not copy Chrome cookie database")) {
    return `<p class="result-copy">提示：Chrome 的 cookies 数据库当前被占用。先完全关闭 Chrome 后再试，或者换用 Edge / cookies.txt。</p>`;
  }

  return "";
}

function buildDetailActions(job) {
  if (!job) return "";

  const actions = [];
  if (job.can_transcribe) {
    actions.push(
      `<button class="primary-button small" type="button" data-detail-action="transcribe" data-job-id="${escapeHtml(job.job_id)}">转成文字</button>`
    );
  }
  if (job.can_delete) {
    actions.push(
      `<button class="ghost-button small danger" type="button" data-detail-action="delete" data-job-id="${escapeHtml(job.job_id)}">删除任务</button>`
    );
  }
  if (job.transcript_preview) {
    actions.push(
      `<button class="ghost-button small" type="button" data-detail-action="copy-transcript" data-job-id="${escapeHtml(job.job_id)}">复制文本</button>`
    );
  }

  return actions.length ? `<div class="result-actions">${actions.join("")}</div>` : "";
}

function renderDetail(job) {
  if (!job) {
    state.selectedJobId = null;
    state.selectedJob = null;
    elements.detailPanel.className = "panel detail-panel empty";
    elements.detailPanel.innerHTML = `
      <div class="result-empty">
        <p class="eyebrow">JOB DETAIL</p>
        <h2>选中任务后，这里会显示完整详情。</h2>
        <p>你可以在这里查看进度、打开输出文件、继续转文字，或者删除已完成的历史任务。</p>
      </div>
    `;
    renderDashboard();
    renderHistory();
    return;
  }

  state.selectedJobId = job.job_id;
  state.selectedJob = job;
  rememberJob(job);

  const filesHtml = (job.files || []).length
    ? job.files
        .map(
          (file) => `
            <div class="file-row">
              <div>
                <span class="file-kind">${escapeHtml(file.kind)}</span>
                <strong>${escapeHtml(file.name)}</strong>
              </div>
              <a class="file-link" href="${escapeHtml(file.url)}" target="_blank" rel="noreferrer">打开</a>
            </div>
          `
        )
        .join("")
    : `<div class="empty-inline">当前任务还没有输出文件。</div>`;

  const transcriptHtml = job.transcript_preview
    ? `<pre>${escapeHtml(job.transcript_preview)}</pre>`
    : `<div class="empty-inline">当前任务还没有可展示的文本内容。</div>`;

  const errorHtml = job.error
    ? `
      <section class="result-block full-width">
        <div class="result-tools"><strong>错误信息</strong></div>
        <p class="error-text">${escapeHtml(job.error)}</p>
        ${
          job.technical_error
            ? `
              <details class="technical-error">
                <summary>技术细节</summary>
                <pre>${escapeHtml(job.technical_error)}</pre>
              </details>
            `
            : ""
        }
        ${buildErrorHint(job)}
      </section>
    `
    : "";

  elements.detailPanel.className = "panel detail-panel";
  elements.detailPanel.innerHTML = `
    <div class="result-top">
      <div>
        <p class="eyebrow">JOB DETAIL</p>
        <h2>${escapeHtml(job.title || job.job_id)}</h2>
      </div>
      <span class="status-pill ${statusClass(job.status)}">${escapeHtml(formatStatus(job.status))}</span>
    </div>
    <div class="result-grid">
      <section class="result-block meta-block">
        <div class="result-tools"><strong>任务信息</strong></div>
        <dl>
          <div>
            <dt>模式</dt>
            <dd>${escapeHtml(formatAction(job.action))}</dd>
          </div>
          <div>
            <dt>创建时间</dt>
            <dd>${escapeHtml(job.created_at || "-")}</dd>
          </div>
          <div>
            <dt>任务目录</dt>
            <dd>${escapeHtml(job.job_dir || "-")}</dd>
          </div>
          <div>
            <dt>来源链接</dt>
            <dd>${escapeHtml(job.source_url || "-")}</dd>
          </div>
          <div>
            <dt>状态明细</dt>
            <dd>${escapeHtml(job.detail || "-")}</dd>
          </div>
          <div>
            <dt>阶段</dt>
            <dd>${escapeHtml(formatPhase(job.phase, job.status))}</dd>
          </div>
        </dl>
        ${buildProgress(job)}
        ${buildDetailActions(job)}
      </section>
      <section class="result-block">
        <div class="result-tools"><strong>输出文件</strong></div>
        ${filesHtml}
      </section>
      <section class="result-block transcript-block">
        <div class="result-tools"><strong>文本预览</strong></div>
        ${transcriptHtml}
      </section>
      ${errorHtml}
    </div>
  `;

  renderDashboard();
  renderHistory();
}

function renderTelegramState(payload) {
  state.telegram = payload;
  const config = payload?.config || {};
  const runtime = payload?.runtime || {};

  elements.telegramEnabledInput.checked = Boolean(config.enabled);
  elements.telegramTokenInput.value = "";
  elements.telegramClearTokenInput.checked = false;
  elements.telegramAllowedChatIdsInput.value = config.allowed_chat_ids_text || "";
  elements.telegramPublicBaseUrlInput.value = config.public_base_url || window.location.origin;
  elements.telegramPollTimeoutInput.value = String(config.poll_timeout ?? 15);
  elements.telegramRetryDelayInput.value = String(config.retry_delay ?? 3);
  elements.telegramProgressUpdatesInput.checked = Boolean(config.progress_updates);
  elements.telegramTokenHint.textContent = config.has_token
    ? `已保存 token：${config.token_masked}`
    : "当前未保存 token。";

  const running = Boolean(runtime.running);
  elements.telegramRuntimeBadge.textContent = running ? "运行中" : "未运行";
  elements.telegramRuntimeBadge.className = `status-pill ${running ? "status-running" : "status-error"}`;

  const infoLines = [
    `<div><dt>模式</dt><dd>${escapeHtml(runtime.mode || "managed_by_web")}</dd></div>`,
    `<div><dt>运行状态</dt><dd>${running ? "运行中" : "未运行"}</dd></div>`,
    `<div><dt>Bot 用户名</dt><dd>${escapeHtml(runtime.bot_username || "-")}</dd></div>`,
    `<div><dt>访问限制</dt><dd>${escapeHtml(config.allowed_chat_ids_text || "all")}</dd></div>`,
    `<div><dt>结果链接</dt><dd>${escapeHtml(config.public_base_url || window.location.origin)}</dd></div>`,
    `<div><dt>进度回推</dt><dd>${config.progress_updates ? "开启" : "关闭"}</dd></div>`,
  ];

  if (runtime.last_error) {
    infoLines.push(`<div><dt>最近错误</dt><dd>${escapeHtml(runtime.last_error)}</dd></div>`);
  }

  elements.telegramRuntimeInfo.innerHTML = `<dl>${infoLines.join("")}</dl>`;
}

function setView(viewName) {
  state.currentView = viewName;
  document.querySelectorAll(".view").forEach((section) => {
    section.classList.toggle("active", section.id === `view-${viewName}`);
  });
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.classList.toggle("active", button.dataset.viewTarget === viewName);
  });

  if (viewName === "history") {
    loadHistory({ silent: true });
  }
  if (viewName === "settings" && !state.telegram) {
    loadTelegramSettings({ silent: true });
  }
}

function stopPolling() {
  if (state.pollTimer) {
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
}

function shouldPoll() {
  return Boolean(state.dashboard.summary?.active) || isActiveStatus(state.selectedJob?.status);
}

function schedulePoll() {
  stopPolling();
  if (!shouldPoll()) {
    return;
  }

  state.pollTimer = setTimeout(async () => {
    try {
      await loadDashboard({ silent: true });
      if (state.selectedJobId) {
        try {
          const detail = await fetchJob(state.selectedJobId);
          renderDetail(detail);
        } catch (error) {
          renderDetail(jobById(state.selectedJobId));
        }
      }
      if (state.currentView === "history") {
        await loadHistory({ silent: true });
      }
    } finally {
      schedulePoll();
    }
  }, 1800);
}

async function fetchJson(url, options = {}, fallbackMessage = "请求失败") {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(data, fallbackMessage));
  }
  return data;
}

async function fetchJob(jobId) {
  const data = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`, {}, "任务详情加载失败");
  rememberJob(data);
  return data;
}

async function loadDashboard({ silent = false } = {}) {
  try {
    const data = await fetchJson("/api/jobs?limit=6", {}, "任务中心加载失败");
    state.dashboard.jobs = data.jobs || [];
    state.dashboard.summary = data.summary || null;
    state.dashboard.totalJobs = data.total_jobs || 0;
    rememberJobs(state.dashboard.jobs);
    renderDashboard();

    if (!state.selectedJobId && state.dashboard.jobs.length) {
      renderDetail(state.dashboard.jobs[0]);
    }

    schedulePoll();
  } catch (error) {
    if (!silent) {
      showFlash(error.message, "error");
    }
  }
}

function readHistoryFiltersFromForm() {
  state.history.q = elements.historySearchInput.value.trim();
  state.history.status = elements.historyStatusInput.value;
  state.history.action = elements.historyActionInput.value;
  state.history.activeOnly = elements.historyActiveOnlyInput.checked;
}

async function loadHistory({ silent = false } = {}) {
  readHistoryFiltersFromForm();
  const params = new URLSearchParams({
    offset: String(state.history.offset),
    limit: String(state.history.limit),
  });
  if (state.history.q) params.set("q", state.history.q);
  if (state.history.status) params.set("status", state.history.status);
  if (state.history.action) params.set("action", state.history.action);
  if (state.history.activeOnly) params.set("active_only", "true");

  try {
    const data = await fetchJson(`/api/jobs?${params.toString()}`, {}, "历史记录加载失败");
    state.history.jobs = data.jobs || [];
    state.history.filteredTotal = data.filtered_total || 0;
    state.history.totalJobs = data.total_jobs || 0;
    state.history.hasMore = Boolean(data.has_more);
    state.history.summary = data.summary || null;
    rememberJobs(state.history.jobs);
    renderHistory();

    if (!state.selectedJobId && state.history.jobs.length) {
      renderDetail(state.history.jobs[0]);
    }
  } catch (error) {
    if (!silent) {
      showFlash(error.message, "error");
    }
  }
}

async function loadDoctor({ silent = false } = {}) {
  try {
    const data = await fetchJson("/api/doctor", {}, "环境检查失败");
    state.doctor = data.items || [];
    renderDoctor();
    if (!silent) {
      showFlash("环境状态已刷新");
    }
  } catch (error) {
    renderDoctor();
    if (!silent) {
      showFlash(error.message, "error");
    }
  }
}

async function loadTelegramSettings({ silent = false } = {}) {
  try {
    const data = await fetchJson("/api/settings/telegram", {}, "Telegram 配置加载失败");
    renderTelegramState(data);
    if (!silent) {
      showFlash("Telegram 配置已刷新");
    }
  } catch (error) {
    if (!silent) {
      showFlash(error.message, "error");
    }
  }
}

async function selectJob(jobId, fallbackJob = null) {
  try {
    const job = await fetchJob(jobId);
    renderDetail(job);
  } catch (error) {
    if (fallbackJob) {
      renderDetail(fallbackJob);
      return;
    }
    showFlash(error.message, "error");
  }
}

async function submitJob(event) {
  event.preventDefault();
  hideFlash();
  setBusy(true);

  const payload = {
    raw_input: document.getElementById("rawInput").value.trim(),
    action: elements.jobForm.querySelector('input[name="action"]:checked').value,
    cookies: document.getElementById("cookiesInput").value.trim(),
    cookies_browser: document.getElementById("browserCookiesInput").value,
    model: document.getElementById("modelInput").value.trim(),
    device: document.getElementById("deviceInput").value.trim(),
  };

  try {
    const data = await fetchJson(
      "/api/jobs",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
      "任务创建失败"
    );
    rememberJob(data);
    renderDetail(data);
    await Promise.all([loadDashboard({ silent: true }), loadHistory({ silent: true })]);
    showFlash("任务已创建，正在后台处理。");
    schedulePoll();
  } catch (error) {
    showFlash(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function transcribeJob(jobId) {
  if (!jobId) return;

  hideFlash();
  try {
    const data = await fetchJson(
      `/api/jobs/${encodeURIComponent(jobId)}/transcribe`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: document.getElementById("modelInput").value.trim(),
          device: document.getElementById("deviceInput").value.trim(),
        }),
      },
      "转写任务创建失败"
    );
    rememberJob(data);
    renderDetail(data);
    await Promise.all([loadDashboard({ silent: true }), loadHistory({ silent: true })]);
    showFlash("转写任务已启动。");
    schedulePoll();
  } catch (error) {
    showFlash(error.message, "error");
  }
}

async function deleteJob(jobId) {
  if (!jobId) return;
  const job = jobById(jobId);
  const label = job?.title || jobId;
  const confirmed = window.confirm(`确认删除任务“${label}”？\n已生成的视频、音频和文本文件会一起删除。`);
  if (!confirmed) return;

  hideFlash();
  try {
    await fetchJson(
      `/api/jobs/${encodeURIComponent(jobId)}`,
      { method: "DELETE" },
      "删除任务失败"
    );
    state.jobCache.delete(jobId);
    if (state.selectedJobId === jobId) {
      renderDetail(null);
    }
    await Promise.all([loadDashboard({ silent: true }), loadHistory({ silent: true })]);
    if (!state.selectedJobId) {
      const nextJob = state.dashboard.jobs[0] || state.history.jobs[0] || null;
      if (nextJob) {
        renderDetail(nextJob);
      }
    }
    showFlash("任务已删除。");
  } catch (error) {
    showFlash(error.message, "error");
  }
}

function collectTelegramPayload() {
  const pollTimeout = Number.parseInt(elements.telegramPollTimeoutInput.value.trim(), 10);
  const retryDelay = Number.parseFloat(elements.telegramRetryDelayInput.value.trim());

  return {
    enabled: elements.telegramEnabledInput.checked,
    token: elements.telegramTokenInput.value.trim(),
    clear_token: elements.telegramClearTokenInput.checked,
    allowed_chat_ids: elements.telegramAllowedChatIdsInput.value.trim(),
    public_base_url: elements.telegramPublicBaseUrlInput.value.trim(),
    poll_timeout: Number.isFinite(pollTimeout) ? pollTimeout : 15,
    retry_delay: Number.isFinite(retryDelay) ? retryDelay : 3,
    progress_updates: elements.telegramProgressUpdatesInput.checked,
  };
}

async function saveTelegramSettings(startAfterSave = false) {
  hideFlash();
  const payload = collectTelegramPayload();
  const url = startAfterSave ? "/api/settings/telegram/start" : "/api/settings/telegram";
  const method = startAfterSave ? "POST" : "PUT";

  try {
    const data = await fetchJson(
      url,
      {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
      startAfterSave ? "Telegram 启动失败" : "Telegram 配置保存失败"
    );
    renderTelegramState(data);
    showFlash(startAfterSave ? "Telegram 机器人已启动。" : "Telegram 配置已保存。");
  } catch (error) {
    showFlash(error.message, "error");
  }
}

async function stopTelegram() {
  hideFlash();
  try {
    const data = await fetchJson(
      "/api/settings/telegram/stop",
      { method: "POST" },
      "Telegram 停止失败"
    );
    renderTelegramState(data);
    showFlash("Telegram 机器人已停止。");
  } catch (error) {
    showFlash(error.message, "error");
  }
}

function handleJobAction(event) {
  const actionButton = event.target.closest("[data-job-action]");
  if (!actionButton) return;

  const jobId = actionButton.dataset.jobId;
  const action = actionButton.dataset.jobAction;

  if (action === "view") {
    selectJob(jobId, jobById(jobId));
    return;
  }
  if (action === "transcribe") {
    transcribeJob(jobId);
    return;
  }
  if (action === "delete") {
    deleteJob(jobId);
  }
}

function handleDetailAction(event) {
  const actionButton = event.target.closest("[data-detail-action]");
  if (!actionButton) return;

  const jobId = actionButton.dataset.jobId;
  const action = actionButton.dataset.detailAction;

  if (action === "transcribe") {
    transcribeJob(jobId);
    return;
  }
  if (action === "delete") {
    deleteJob(jobId);
    return;
  }
  if (action === "copy-transcript") {
    navigator.clipboard
      .writeText(state.selectedJob?.transcript_preview || "")
      .then(() => showFlash("文本预览已复制。"))
      .catch((error) => showFlash(`复制失败: ${error.message}`, "error"));
  }
}

document.querySelectorAll("[data-view-target]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.viewTarget));
});

elements.jobForm.addEventListener("submit", submitJob);
elements.dashboardJobsList.addEventListener("click", handleJobAction);
elements.historyList.addEventListener("click", handleJobAction);
elements.detailPanel.addEventListener("click", handleDetailAction);

document.getElementById("refreshDashboardBtn").addEventListener("click", async () => {
  hideFlash();
  await loadDashboard();
});

document.getElementById("jumpToHistoryBtn").addEventListener("click", () => {
  setView("history");
});

document.getElementById("refreshHistoryBtn").addEventListener("click", async () => {
  hideFlash();
  await loadHistory();
});

elements.historyFilters.addEventListener("submit", async (event) => {
  event.preventDefault();
  state.history.offset = 0;
  await loadHistory();
});

document.getElementById("resetHistoryFiltersBtn").addEventListener("click", async () => {
  elements.historySearchInput.value = "";
  elements.historyStatusInput.value = "";
  elements.historyActionInput.value = "";
  elements.historyActiveOnlyInput.checked = false;
  state.history.offset = 0;
  await loadHistory();
});

elements.historyPrevBtn.addEventListener("click", async () => {
  if (state.history.offset <= 0) return;
  state.history.offset = Math.max(0, state.history.offset - state.history.limit);
  await loadHistory();
});

elements.historyNextBtn.addEventListener("click", async () => {
  if (!state.history.hasMore) return;
  state.history.offset += state.history.limit;
  await loadHistory();
});

document.getElementById("selfCheckBtn").addEventListener("click", async () => {
  hideFlash();
  await loadDoctor();
});

elements.telegramForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await saveTelegramSettings(false);
});

document.getElementById("startTelegramBtn").addEventListener("click", async () => {
  await saveTelegramSettings(true);
});

document.getElementById("stopTelegramBtn").addEventListener("click", async () => {
  await stopTelegram();
});

Promise.allSettled([
  loadDashboard({ silent: true }),
  loadHistory({ silent: true }),
  loadDoctor({ silent: true }),
  loadTelegramSettings({ silent: true }),
]).then(() => {
  renderDashboard();
  renderHistory();
  renderDoctor();
  if (!state.selectedJobId && state.dashboard.jobs.length) {
    renderDetail(state.dashboard.jobs[0]);
  }
  schedulePoll();
});
