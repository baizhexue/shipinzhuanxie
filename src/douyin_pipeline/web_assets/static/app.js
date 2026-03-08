const doctorList = document.getElementById("doctorList");
const jobsList = document.getElementById("jobsList");
const resultPanel = document.getElementById("resultPanel");
const flash = document.getElementById("flash");
const submitBtn = document.getElementById("submitBtn");
const form = document.getElementById("jobForm");

let currentJob = null;
let pollTimer = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function showFlash(message, type = "info") {
  flash.textContent = message;
  flash.className = `flash ${type}`;
  flash.classList.remove("hidden");
}

function hideFlash() {
  flash.className = "flash hidden";
  flash.textContent = "";
}

function setBusy(isBusy) {
  submitBtn.disabled = isBusy;
  submitBtn.textContent = isBusy ? "创建任务中..." : "开始处理";
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
      queued: "queued",
      downloading: "downloading",
      transcribing: "transcribing",
      success: "success",
      error: "error",
    }[status] || status
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
    return "预计剩余计算中";
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
  const hasTimeNumbers =
    Number.isFinite(job.processed_seconds) && Number.isFinite(job.duration_seconds) && job.duration_seconds > 0;

  if (progressPercent === null && !hasTimeNumbers && !isActiveStatus(job.status)) {
    return "";
  }

  const progressText = progressPercent === null ? "--" : `${Math.round(progressPercent)}%`;
  const phaseText = formatPhase(job.phase, job.status);
  const timingText = hasTimeNumbers
    ? `已处理 ${formatClock(job.processed_seconds)} / ${formatClock(job.duration_seconds)}`
    : escapeHtml(job.detail || phaseText);
  const etaText = isActiveStatus(job.status)
    ? formatEta(Number(job.eta_seconds))
    : progressPercent === 100
      ? "处理完成"
      : "";

  return `
    <div class="progress-block${compact ? " compact" : ""}">
      <div class="progress-topline">
        <span>${escapeHtml(phaseText)}</span>
        <strong>${escapeHtml(progressText)}</strong>
      </div>
      <div class="progress-track" aria-hidden="true">
        <span class="progress-fill" style="width:${progressPercent ?? 0}%"></span>
      </div>
      <div class="progress-meta">
        <span>${timingText}</span>
        <span>${escapeHtml(etaText)}</span>
      </div>
    </div>
  `;
}

function formatApiError(data, fallback) {
  const detail = typeof data?.detail === "string" && data.detail ? data.detail : fallback;
  const hint = typeof data?.error_hint === "string" && data.error_hint ? data.error_hint : "";
  return [detail, hint].filter(Boolean).join(" ");
}

function buildErrorHint(job) {
  if (!job) return "";

  if (job.error_hint) {
    return `<p class="result-copy">提示：${escapeHtml(job.error_hint)}</p>`;
  }

  const errorText = String(job.technical_error || job.error || "");
  if (!errorText) return "";

  if (errorText.includes("Fresh cookies")) {
    return `
      <p class="result-copy">
        提示：Douyin 这次要求 fresh cookies。程序现在会自动尝试浏览器辅助回退；
        如果仍然失败，再考虑换浏览器或重新打开视频页面后重试。
      </p>
    `;
  }

  if (errorText.includes("Could not copy Chrome cookie database")) {
    return `
      <p class="result-copy">
        提示：Chrome 的 cookies 数据库当前可能被占用。先完全关闭 Chrome 后再试，
        或者改用 Edge / cookies.txt。
      </p>
    `;
  }

  return "";
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function renderDoctor(items = []) {
  if (!items.length) {
    doctorList.innerHTML = `<div class="doctor-item"><div class="doctor-detail">暂无环境信息</div></div>`;
    return;
  }

  doctorList.innerHTML = items
    .map(
      (item) => `
        <article class="doctor-item">
          <div class="doctor-top">
            <strong>${escapeHtml(item.name)}</strong>
            <span class="status-pill ${item.ok ? "status-ok" : "status-fail"}">
              ${item.ok ? "OK" : "FAIL"}
            </span>
          </div>
          <div class="doctor-detail">${escapeHtml(item.detail)}</div>
        </article>
      `
    )
    .join("");
}

function renderJobs(jobs = []) {
  if (!jobs.length) {
    jobsList.innerHTML = `<div class="job-card"><div class="job-meta">还没有任务记录。</div></div>`;
    return;
  }

  jobsList.innerHTML = jobs
    .map(
      (job) => `
        <article class="job-card" data-job='${escapeHtml(JSON.stringify(job))}'>
          <div class="job-top">
            <strong>${escapeHtml(job.title || job.job_id)}</strong>
            <span class="status-pill ${statusClass(job.status)}">${escapeHtml(formatStatus(job.status))}</span>
          </div>
          <div class="job-meta">
            ${escapeHtml(formatAction(job.action))} · ${escapeHtml(job.created_at)}
          </div>
          <div class="doctor-detail">${escapeHtml(job.detail || "")}</div>
          ${buildProgress(job, true)}
          ${
            job.can_transcribe
              ? `
                <div class="job-actions">
                  <button class="copy-button" type="button" data-job-action="transcribe">转文字</button>
                </div>
              `
              : ""
          }
        </article>
      `
    )
    .join("");
}

function buildResultActions(job) {
  if (!job) return "";

  const actions = [];

  if (job.can_transcribe) {
    actions.push(
      `<button class="primary-button" type="button" data-job-action="transcribe">转成文字</button>`
    );
  }

  if (job.transcript_preview) {
    actions.push(
      `<button class="copy-button" type="button" data-copy="transcript">复制文字</button>`
    );
  }

  if (!actions.length) return "";
  return `<div class="result-actions">${actions.join("")}</div>`;
}

function renderResult(job) {
  if (!job) {
    currentJob = null;
    stopPolling();
    resultPanel.className = "panel result-panel empty";
    resultPanel.innerHTML = `
      <div class="result-empty">
        <p class="eyebrow">RESULT PREVIEW</p>
        <h2>结果会显示在这里。</h2>
        <p>页面会展示任务状态、输出文件、文字预览。刷新页面后，最近任务也会保留下来。</p>
      </div>
    `;
    return;
  }

  currentJob = job;

  const filesHtml = (job.files || []).length
    ? job.files
        .map(
          (file) => `
            <div class="file-row">
              <div>
                <span class="file-kind">${escapeHtml(file.kind)}</span>
                <strong>${escapeHtml(file.name)}</strong>
              </div>
              <a class="file-link" href="${escapeHtml(file.url)}" target="_blank" rel="noreferrer">打开文件</a>
            </div>
          `
        )
        .join("")
    : `<div class="error-text">当前任务还没有输出文件。</div>`;

  const transcriptHtml = job.transcript_preview
    ? `<pre>${escapeHtml(job.transcript_preview)}</pre>`
    : `<div class="error-text">当前任务还没有可展示的文字内容。</div>`;

  const errorHtml = job.error
    ? `
      <div class="result-error">
        <p class="error-text">错误信息：${escapeHtml(job.error)}</p>
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
      </div>
    `
    : `<p class="result-copy">任务完成后，下面可以直接打开生成的文件。</p>`;

  const hintHtml = buildErrorHint(job);
  const actionsHtml = buildResultActions(job);
  const progressHtml = buildProgress(job);

  resultPanel.className = "panel result-panel";
  resultPanel.innerHTML = `
    <div class="result-top">
      <div>
        <p class="eyebrow">RESULT PREVIEW</p>
        <h2>${escapeHtml(job.title || job.job_id)}</h2>
      </div>
      <span class="status-pill ${statusClass(job.status)}">${escapeHtml(formatStatus(job.status))}</span>
    </div>
    <div class="result-grid">
      <section class="result-meta">
        <dl>
          <div>
            <dt>Mode</dt>
            <dd>${escapeHtml(formatAction(job.action))}</dd>
          </div>
          <div>
            <dt>Created</dt>
            <dd>${escapeHtml(job.created_at)}</dd>
          </div>
          <div>
            <dt>Job Folder</dt>
            <dd>${escapeHtml(job.job_dir)}</dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>${escapeHtml(job.source_url || "-")}</dd>
          </div>
          <div>
            <dt>Status Detail</dt>
            <dd>${escapeHtml(job.detail || "-")}</dd>
          </div>
        </dl>
        ${progressHtml}
        ${actionsHtml}
      </section>
      <section class="result-files">
        <div class="result-tools">
          <strong>输出文件</strong>
        </div>
        ${filesHtml}
      </section>
      <section class="result-transcript">
        <div class="result-tools">
          <strong>文字预览</strong>
        </div>
        ${transcriptHtml}
      </section>
      ${errorHtml}
      ${hintHtml}
    </div>
  `;
}

async function fetchJob(jobId) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(formatApiError(data, "任务详情加载失败"));
  }
  return data;
}

function queuePoll(jobId) {
  stopPolling();
  pollTimer = setTimeout(async () => {
    try {
      const job = await fetchJob(jobId);
      renderResult(job);

      if (isActiveStatus(job.status)) {
        queuePoll(jobId);
        return;
      }

      await loadJobs();
      showFlash(job.status === "success" ? "任务已完成。" : "任务结束，请查看结果。");
    } catch (error) {
      showFlash(`轮询失败: ${error.message}`, "error");
    }
  }, 1500);
}

async function loadDoctor() {
  try {
    const response = await fetch("/api/doctor");
    const data = await response.json();
    renderDoctor(data.items || []);
  } catch (error) {
    renderDoctor([]);
    showFlash(`环境检查失败: ${error.message}`, "error");
  }
}

async function loadJobs() {
  try {
    const response = await fetch("/api/jobs");
    const data = await response.json();
    renderJobs(data.jobs || []);
    if ((data.jobs || []).length && resultPanel.classList.contains("empty")) {
      renderResult(data.jobs[0]);
      if (isActiveStatus(data.jobs[0].status)) {
        queuePoll(data.jobs[0].job_id);
      }
    }
  } catch (error) {
    renderJobs([]);
    showFlash(`任务列表加载失败: ${error.message}`, "error");
  }
}

async function submitJob(event) {
  event.preventDefault();
  hideFlash();
  setBusy(true);
  stopPolling();

  const payload = {
    raw_input: document.getElementById("rawInput").value.trim(),
    action: form.querySelector('input[name="action"]:checked').value,
    cookies: document.getElementById("cookiesInput").value.trim(),
    cookies_browser: document.getElementById("browserCookiesInput").value,
    model: document.getElementById("modelInput").value.trim(),
    device: document.getElementById("deviceInput").value.trim(),
  };

  try {
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(formatApiError(data, "任务创建失败"));
    }

    renderResult(data);
    await loadJobs();
    showFlash("任务已创建，正在后台处理。");

    if (isActiveStatus(data.status)) {
      queuePoll(data.job_id);
    }
  } catch (error) {
    showFlash(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function transcribeJob(job = currentJob) {
  if (!job?.job_id) return;

  hideFlash();
  stopPolling();
  currentJob = job;

  const payload = {
    model: document.getElementById("modelInput").value.trim(),
    device: document.getElementById("deviceInput").value.trim(),
  };

  try {
    const response = await fetch(
      `/api/jobs/${encodeURIComponent(job.job_id)}/transcribe`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(formatApiError(data, "转写任务创建失败"));
    }

    renderResult(data);
    await loadJobs();
    showFlash("转写任务已启动。");

    if (isActiveStatus(data.status)) {
      queuePoll(data.job_id);
    }
  } catch (error) {
    showFlash(error.message, "error");
  }
}

document.getElementById("selfCheckBtn").addEventListener("click", async () => {
  hideFlash();
  await loadDoctor();
  showFlash("环境状态已刷新。");
});

document.getElementById("refreshJobsBtn").addEventListener("click", async () => {
  hideFlash();
  await loadJobs();
  showFlash("最近任务列表已刷新。");
});

jobsList.addEventListener("click", (event) => {
  const transcribeButton = event.target.closest("[data-job-action='transcribe']");
  if (transcribeButton) {
    const card = transcribeButton.closest(".job-card");
    if (!card || !card.dataset.job) return;

    const job = JSON.parse(card.dataset.job);
    transcribeJob(job);
    return;
  }

  const card = event.target.closest(".job-card");
  if (!card || !card.dataset.job) return;

  const job = JSON.parse(card.dataset.job);
  renderResult(job);
  if (isActiveStatus(job.status)) {
    queuePoll(job.job_id);
  } else {
    stopPolling();
  }
});

resultPanel.addEventListener("click", async (event) => {
  const transcribeButton = event.target.closest("[data-job-action='transcribe']");
  if (transcribeButton) {
    await transcribeJob(currentJob);
    return;
  }

  const copyButton = event.target.closest("[data-copy]");
  if (!copyButton) return;

  try {
    await navigator.clipboard.writeText(currentJob?.transcript_preview || "");
    showFlash("文字预览已复制。");
  } catch (error) {
    showFlash(`复制失败: ${error.message}`, "error");
  }
});

form.addEventListener("submit", submitJob);

loadDoctor();
loadJobs();
