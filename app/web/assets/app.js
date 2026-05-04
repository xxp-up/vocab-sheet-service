const STORAGE_KEYS = {
  vocabJobId: "vocab-workspace:vocab-job-id",
  feedbackJobId: "vocab-workspace:feedback-job-id",
  lastTaskKind: "vocab-workspace:last-task-kind",
  downloadedJobId: "vocab-workspace:downloaded-job-id",
};

const POLL_INTERVAL_MS = 1800;
const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50];
const SETTINGS_SAVE_BLOCKED_MESSAGE = "后台任务正在运行，请等待后台任务运行完成后再进行系统配置修改保存。";

const VIEW_CONFIG = {
  vocab: {
    panelId: "vocab-panel",
    title: "教材提词",
    defaultContext: "请提交教材任务或查看当前进度",
    idleStageLabel: "等待开始",
    idleMessage: "提交任务后，这里会展示当前处理进度与结果摘要。",
  },
  feedback: {
    panelId: "feedback-panel",
    title: "课后反馈",
    defaultContext: "提交反馈任务后可在右侧查看进度",
    idleStageLabel: "等待开始",
    idleMessage: "提交反馈任务后，这里会同步展示草稿生成进度与编辑准备状态。",
  },
  settings: {
    panelId: "settings-panel",
    title: "系统配置",
    defaultContext: "可先测试连接，再保存新的运行配置",
    idleStageLabel: "配置就绪",
    idleMessage: "可在左侧先测试连接；若后台任务仍在运行，需等待完成后再保存最新参数。",
  },
};

const stageSets = {
  vocab: [
    ["upload_validation", "上传校验"],
    ["document_parsing", "教材解析"],
    ["merge_candidates", "音频/补词合并"],
    ["lexicon_enrichment", "词典补全"],
    ["sentence_matching", "例句定位"],
    ["workbook_writing", "模板写入"],
    ["download_ready", "准备下载"],
  ],
  feedback: [
    ["source_preparing", "整理源材料"],
    ["audio_transcribing", "音频转写"],
    ["draft_generating", "生成反馈草稿"],
    ["draft_ready", "草稿可编辑"],
  ],
  settings: [],
};

const JOB_STORAGE_KEYS = {
  vocab: STORAGE_KEYS.vocabJobId,
  feedback: STORAGE_KEYS.feedbackJobId,
};

const JOB_ENDPOINTS = {
  vocab: "/v1/vocab/jobs",
  feedback: "/v1/feedback/jobs",
};

const state = {
  currentTab: "vocab",
  pollTimers: {
    vocab: null,
    feedback: null,
  },
  activeJobIds: {
    vocab: null,
    feedback: null,
  },
  jobSnapshots: {
    vocab: null,
    feedback: null,
  },
  viewContextOverrides: {
    vocab: null,
    feedback: null,
    settings: null,
  },
  currentDownloadUrl: null,
  activeResultTab: "written",
  resultPagination: {
    written: { page: 1, pageSize: DEFAULT_PAGE_SIZE },
    exception: { page: 1, pageSize: DEFAULT_PAGE_SIZE },
  },
  feedbackOriginals: new Map(),
  isRecording: false,
  mediaRecorder: null,
  recordedChunks: [],
};

document.addEventListener("DOMContentLoaded", () => {
  pruneSettingsWorkspace();
  bindTabs();
  bindFileInputs();
  bindResultInspector();
  bindVocabForm();
  bindFeedbackForm();
  bindSettingsForm();
  bindManualMic();
  activateTab(resolveInitialTab());
  hydrateDefaults();
  syncManualWordsChips();
  restoreCurrentTask();
});

function pruneSettingsWorkspace() {
  document.querySelector('[data-tab-target="settings-panel"]')?.remove();
  document.getElementById("settings-panel")?.remove();
}

function bindTabs() {
  document.querySelectorAll("[data-tab-target]").forEach((button) => {
    button.addEventListener("click", () => {
      const kind = getKindFromPanelId(button.dataset.tabTarget);
      if (kind) {
        activateTab(kind);
      }
    });
  });
}

function bindFileInputs() {
  [
    ["teaching-file", "teaching-file-name"],
    ["audio-file", "audio-file-name"],
    ["feedback-audio-file", "feedback-audio-file-name"],
  ].forEach(([inputId, labelId]) => {
    const input = document.getElementById(inputId);
    const label = document.getElementById(labelId);
    if (!input || !label) {
      return;
    }
    input.addEventListener("change", () => {
      label.textContent = input.files && input.files[0] ? input.files[0].name : "未选择文件";
    });
  });

  document.getElementById("words-text")?.addEventListener("input", syncManualWordsChips);
}

function bindResultInspector() {
  document.querySelectorAll("[data-result-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      setResultTab(button.dataset.resultTab || "written");
      renderResultInspector(state.jobSnapshots.vocab);
    });
  });

  document.querySelectorAll("[data-result-tab-trigger]").forEach((button) => {
    button.addEventListener("click", () => {
      openResultInspector(button.dataset.resultTabTrigger || "written");
    });
  });

  const inspector = document.getElementById("result-inspector");
  inspector?.addEventListener("click", (event) => {
    const pageButton = event.target.closest("[data-page-action]");
    const pageNumberButton = event.target.closest("[data-page-number]");
    if (pageButton && !pageButton.disabled) {
      const tab = normalizeResultTab(pageButton.dataset.pageTab);
      const direction = pageButton.dataset.pageAction === "prev" ? -1 : 1;
      const pagination = state.resultPagination[tab];
      pagination.page = Math.max(1, pagination.page + direction);
      renderResultInspector(state.jobSnapshots.vocab);
      return;
    }

    if (pageNumberButton && !pageNumberButton.disabled) {
      const tab = normalizeResultTab(pageNumberButton.dataset.pageTab);
      state.resultPagination[tab].page = Number(pageNumberButton.dataset.pageNumber) || 1;
      renderResultInspector(state.jobSnapshots.vocab);
    }
  });

  inspector?.addEventListener("change", (event) => {
    const select = event.target.closest("[data-page-size-select]");
    if (!select) {
      return;
    }
    const tab = normalizeResultTab(select.dataset.pageSizeSelect);
    const nextSize = Number(select.value) || DEFAULT_PAGE_SIZE;
    state.resultPagination[tab].pageSize = nextSize;
    state.resultPagination[tab].page = 1;
    renderResultInspector(state.jobSnapshots.vocab);
  });

}

function bindVocabForm() {
  const form = document.getElementById("vocab-form");
  if (!form) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const teachingFile = document.getElementById("teaching-file")?.files?.[0];
    if (!teachingFile) {
      showBanner("请先选择教材文件。");
      return;
    }

    const formData = new FormData(form);
    activateTab("vocab");
    localStorage.setItem(STORAGE_KEYS.lastTaskKind, "vocab");
    setJobSnapshot("vocab", {
      status: "processing",
      stageCode: null,
      stageLabel: "提交任务中",
      progressPercent: 3,
      message: "正在创建任务...",
      jobId: null,
      raw: null,
    });
    resetResultInspectorState();
    resetResultCard();

    try {
      const created = await requestJSON(JOB_ENDPOINTS.vocab, { method: "POST", body: formData });
      localStorage.setItem(STORAGE_KEYS.vocabJobId, created.job_id);
      state.activeJobIds.vocab = created.job_id;
      await startJobPolling("vocab", created.job_id);
    } catch (error) {
      showBanner(resolveErrorMessage(error));
      setJobSnapshot("vocab", {
        status: "failed",
        stageCode: null,
        stageLabel: "提交失败",
        progressPercent: 0,
        message: resolveErrorMessage(error),
        jobId: null,
        raw: null,
      });
    }
  });
}

function bindFeedbackForm() {
  const form = document.getElementById("feedback-form");
  const copyFeedbackButton = document.getElementById("copy-feedback-button");
  const copyHomeworkButton = document.getElementById("copy-homework-button");

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const transcript = document.getElementById("feedback-transcript")?.value.trim();
    const audioFile = document.getElementById("feedback-audio-file")?.files?.[0];
    if (!transcript && !audioFile) {
      showBanner("请提供课堂音频或逐字稿文本。");
      return;
    }

    const formData = new FormData(form);
    activateTab("feedback");
    localStorage.setItem(STORAGE_KEYS.lastTaskKind, "feedback");
    document.getElementById("feedback-editor")?.classList.add("hidden");
    setJobSnapshot("feedback", {
      status: "processing",
      stageCode: null,
      stageLabel: "提交任务中",
      progressPercent: 3,
      message: "正在创建反馈任务...",
      jobId: null,
      raw: null,
    });

    try {
      const created = await requestJSON(JOB_ENDPOINTS.feedback, { method: "POST", body: formData });
      localStorage.setItem(STORAGE_KEYS.feedbackJobId, created.job_id);
      state.activeJobIds.feedback = created.job_id;
      await startJobPolling("feedback", created.job_id);
    } catch (error) {
      showBanner(resolveErrorMessage(error));
      setJobSnapshot("feedback", {
        status: "failed",
        stageCode: null,
        stageLabel: "提交失败",
        progressPercent: 0,
        message: resolveErrorMessage(error),
        jobId: null,
        raw: null,
      });
    }
  });

  copyFeedbackButton?.addEventListener("click", async () => {
    const text = Array.from(document.querySelectorAll("[data-feedback-section] textarea"))
      .map((item) => `${item.dataset.title}\n${item.value.trim()}`)
      .join("\n\n")
      .trim();
    await copyText(text, "课后反馈已复制到剪贴板。");
  });

  copyHomeworkButton?.addEventListener("click", async () => {
    const homeworkArea = document.querySelector('[data-feedback-section-key="homework"] textarea');
    const text = homeworkArea ? homeworkArea.value.trim() : "";
    await copyText(text, "作业内容已复制。");
  });
}

function bindSettingsForm() {
  const form = document.getElementById("settings-form");
  const validateButton = document.getElementById("settings-validate");

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!canSaveSettings()) {
      showBanner(SETTINGS_SAVE_BLOCKED_MESSAGE);
      return;
    }

    try {
      const payload = collectSettingsPayload();
      const response = await requestJSON("/v1/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      applySettings(response);
      document.getElementById("vision-api-key").value = "";
      setViewContextOverride("settings", "配置保存成功");
      showToast("配置已保存，新任务将使用最新设置。");
    } catch (error) {
      showBanner(resolveErrorMessage(error));
    }
  });

  validateButton?.addEventListener("click", async () => {
    try {
      const payload = collectSettingsPayload();
      const response = await requestJSON("/v1/settings/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setViewContextOverride("settings", "连接校验通过");
      showToast(response.detail || "连接校验通过。");
    } catch (error) {
      showBanner(resolveErrorMessage(error));
      setViewContextOverride("settings", "连接校验失败");
    }
  });
}

function bindManualMic() {
  const button = document.getElementById("manual-mic-button");
  button?.addEventListener("click", async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      showBanner("当前浏览器不支持网页内录音，请改用手输补词。");
      return;
    }

    if (state.isRecording) {
      state.mediaRecorder?.stop();
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      state.recordedChunks = [];
      state.mediaRecorder = new MediaRecorder(stream);
      state.mediaRecorder.addEventListener("dataavailable", (event) => {
        if (event.data?.size) {
          state.recordedChunks.push(event.data);
        }
      });
      state.mediaRecorder.addEventListener("stop", async () => {
        stream.getTracks().forEach((track) => track.stop());
        state.isRecording = false;
        updateMicButton();
        await uploadRecordedWords();
      });
      state.mediaRecorder.start();
      state.isRecording = true;
      updateMicButton();
      showToast("正在录音，再次点击即可停止并识别。");
    } catch (_) {
      showBanner("无法启用麦克风，请检查浏览器权限。");
    }
  });
}

function hydrateDefaults() {
  const lessonDate = document.getElementById("lesson-date");
  if (lessonDate && !lessonDate.value) {
    lessonDate.value = new Date().toISOString().slice(0, 10);
  }
}

async function loadSettings() {
  try {
    const settings = await requestJSON("/v1/settings");
    applySettings(settings);
  } catch (error) {
    showBanner(`配置加载失败：${resolveErrorMessage(error)}`);
  }
}

function applySettings(settings) {
  document.getElementById("vision-base-url").value = settings.vision_base_url || "";
  document.getElementById("vision-model").value = settings.vision_model || "";
  document.getElementById("request-timeout").value = settings.request_timeout_seconds ?? 90;
  document.getElementById("vision-timeout").value = settings.vision_timeout_seconds ?? settings.request_timeout_seconds ?? 90;
  document.getElementById("runtime-root").value = settings.runtime_root || ".runtime";
  const keyHint = document.getElementById("settings-key-hint");
  if (settings.vision_api_key_configured) {
    keyHint.textContent = `当前密钥：${settings.vision_api_key_masked}`;
  } else {
    keyHint.textContent = "当前尚未配置密钥。";
  }
}

function collectSettingsPayload() {
  const keyInput = document.getElementById("vision-api-key").value.trim();
  return {
    vision_api_key: keyInput || null,
    vision_base_url: document.getElementById("vision-base-url").value.trim(),
    vision_model: document.getElementById("vision-model").value.trim(),
    request_timeout_seconds: Number(document.getElementById("request-timeout").value),
    vision_timeout_seconds: Number(document.getElementById("vision-timeout").value),
    runtime_root: document.getElementById("runtime-root").value.trim(),
  };
}

function resolveInitialTab() {
  const lastTaskKind = localStorage.getItem(STORAGE_KEYS.lastTaskKind);
  if ((lastTaskKind === "vocab" || lastTaskKind === "feedback") && localStorage.getItem(JOB_STORAGE_KEYS[lastTaskKind])) {
    return lastTaskKind;
  }
  return "vocab";
}

function restoreCurrentTask() {
  const vocabJobId = localStorage.getItem(STORAGE_KEYS.vocabJobId);
  const feedbackJobId = localStorage.getItem(STORAGE_KEYS.feedbackJobId);

  if (vocabJobId) {
    state.activeJobIds.vocab = vocabJobId;
    void startJobPolling("vocab", vocabJobId);
  }

  if (feedbackJobId) {
    state.activeJobIds.feedback = feedbackJobId;
    void startJobPolling("feedback", feedbackJobId);
  }

  renderStatusCard();
}

async function startJobPolling(kind, jobId) {
  stopJobPolling(kind);
  state.activeJobIds[kind] = jobId;
  await refreshJob(kind, jobId);
  const snapshot = state.jobSnapshots[kind];
  if (!snapshot || snapshot.jobId !== jobId || isTerminalStatus(snapshot.status)) {
    return;
  }
  state.pollTimers[kind] = window.setInterval(() => {
    void refreshJob(kind, jobId);
  }, POLL_INTERVAL_MS);
}

function stopJobPolling(kind) {
  if (state.pollTimers[kind]) {
    window.clearInterval(state.pollTimers[kind]);
    state.pollTimers[kind] = null;
  }
}

async function refreshJob(kind, jobId) {
  try {
    const job = await requestJSON(`${JOB_ENDPOINTS[kind]}/${jobId}`);
    state.activeJobIds[kind] = jobId;
    if (kind === "vocab") {
      handleVocabJob(job);
    } else {
      handleFeedbackJob(job);
    }
    if (isTerminalStatus(job.status)) {
      stopJobPolling(kind);
    }
  } catch (error) {
    stopJobPolling(kind);
    if (error.status === 404) {
      localStorage.removeItem(JOB_STORAGE_KEYS[kind]);
      state.activeJobIds[kind] = null;
      clearJobSnapshot(kind);
      return;
    }
    showBanner(resolveErrorMessage(error));
  }
}

function handleVocabJob(job) {
  const message = job.status === "failed"
    ? job.error_message || "处理失败，请检查输入文件。"
    : job.status === "completed"
      ? "处理完成，系统已准备下载文件。"
      : "系统正在处理教材，请稍候。";

  setJobSnapshot("vocab", createJobSnapshot("vocab", job, message));

  const redownloadButton = document.getElementById("redownload-button");
  if (job.status === "completed") {
    state.currentDownloadUrl = job.download_url || null;
    redownloadButton.onclick = job.download_url ? () => triggerDownload(job.download_url) : null;
    const alreadyDownloaded = localStorage.getItem(STORAGE_KEYS.downloadedJobId);
    if (job.download_url && alreadyDownloaded !== job.job_id) {
      triggerDownload(job.download_url);
      localStorage.setItem(STORAGE_KEYS.downloadedJobId, job.job_id);
      showToast("词表已生成，开始自动下载。");
    }
  } else if (job.status !== "failed") {
    state.currentDownloadUrl = null;
    redownloadButton.onclick = null;
  }
}

function handleFeedbackJob(job) {
  const previousSnapshot = state.jobSnapshots.feedback;
  const message = job.status === "failed"
    ? job.error_message || "生成失败，请检查课堂内容。"
    : job.status === "completed"
      ? "反馈草稿已生成，可在左侧继续编辑。"
      : "系统正在整理源材料并生成反馈草稿。";

  setJobSnapshot("feedback", createJobSnapshot("feedback", job, message));

  if (job.status === "completed") {
    localStorage.setItem(STORAGE_KEYS.feedbackJobId, job.job_id);
    renderFeedbackSections(job.draft_sections || []);
    document.getElementById("feedback-editor").classList.remove("hidden");
    if (!previousSnapshot || previousSnapshot.jobId !== job.job_id || previousSnapshot.status !== "completed") {
      showToast("课后反馈草稿已准备好。");
    }
  } else if (job.status === "failed") {
    document.getElementById("feedback-editor").classList.add("hidden");
  }
}

function createJobSnapshot(kind, job, message) {
  return {
    kind,
    status: job.status,
    stageCode: job.stage_code || null,
    stageLabel: job.stage_label || VIEW_CONFIG[kind].idleStageLabel,
    progressPercent: Number(job.progress_percent) || 0,
    message,
    jobId: job.job_id || null,
    raw: job,
  };
}

function setJobSnapshot(kind, snapshot) {
  state.jobSnapshots[kind] = {
    kind,
    status: snapshot.status,
    stageCode: snapshot.stageCode ?? null,
    stageLabel: snapshot.stageLabel || VIEW_CONFIG[kind].idleStageLabel,
    progressPercent: Number(snapshot.progressPercent) || 0,
    message: snapshot.message || VIEW_CONFIG[kind].idleMessage,
    jobId: snapshot.jobId || null,
    raw: snapshot.raw || null,
  };
  renderStatusCard();
}

function clearJobSnapshot(kind) {
  state.jobSnapshots[kind] = null;
  if (kind === "feedback") {
    document.getElementById("feedback-editor")?.classList.add("hidden");
  }
  if (kind === "vocab") {
    state.currentDownloadUrl = null;
    resetResultCard();
  }
  renderStatusCard();
}

function activateTab(kind) {
  state.currentTab = kind;
  const shell = document.querySelector(".workspace-shell");
  if (shell) {
    shell.dataset.currentTab = kind;
  }

  document.querySelectorAll("[data-tab-target]").forEach((button) => {
    button.classList.toggle("active", button.dataset.tabTarget === VIEW_CONFIG[kind].panelId);
  });

  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.id === VIEW_CONFIG[kind].panelId);
  });

  renderStatusCard();
}

function openResultInspector(tab) {
  setResultTab(tab);
  renderResultInspector(state.jobSnapshots.vocab);
  const inspector = document.getElementById("result-inspector");
  if (!inspector || inspector.classList.contains("hidden")) {
    return;
  }
  inspector.scrollIntoView({ behavior: "smooth", block: "start" });
}

function setResultTab(tab) {
  state.activeResultTab = normalizeResultTab(tab);
  syncResultTabButtons();
}

function normalizeResultTab(tab) {
  return tab === "exception" ? "exception" : "written";
}

function syncResultTabButtons() {
  const activeTab = state.activeResultTab;
  document.querySelectorAll("[data-result-tab]").forEach((button) => {
    const isActive = button.dataset.resultTab === activeTab;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });
  document.querySelectorAll("[data-result-panel]").forEach((panel) => {
    const isActive = panel.dataset.resultPanel === activeTab;
    panel.classList.toggle("hidden", !isActive);
    panel.classList.toggle("active", isActive);
  });
}

function renderStatusCard() {
  const viewKind = state.currentTab;
  const config = VIEW_CONFIG[viewKind];
  const snapshot = viewKind === "settings" ? null : state.jobSnapshots[viewKind];
  const statusCard = document.querySelector(".status-card");
  const progressWrap = document.getElementById("progress-wrap");
  const stageList = document.getElementById("status-stage-list");
  const progressLabel = document.getElementById("progress-label");
  const progressPercent = document.getElementById("progress-percent");
  const progressBar = document.getElementById("progress-bar");
  const statusTitle = document.getElementById("status-title");
  const statusContext = document.getElementById("status-context");
  const statusMessage = document.getElementById("status-message");

  statusCard.dataset.viewKind = viewKind;
  statusTitle.textContent = config.title;
  statusContext.textContent = getStatusContext(viewKind, snapshot);
  statusMessage.textContent = snapshot?.message || config.idleMessage;

  renderSecondaryTaskHint(viewKind);
  syncSettingsSaveState();
  renderStageList(viewKind);

  const percent = Math.max(0, Math.min(100, snapshot?.progressPercent ?? 0));
  progressLabel.textContent = snapshot?.stageLabel || config.idleStageLabel;
  progressPercent.textContent = `${percent}%`;
  progressBar.style.width = `${percent}%`;
  highlightStage(snapshot?.stageCode || null);

  const hasStages = stageSets[viewKind].length > 0;
  progressWrap.classList.toggle("hidden", !hasStages);
  stageList.classList.toggle("hidden", !hasStages);

  renderResultCard(viewKind, snapshot);
  renderResultInspector(state.jobSnapshots.vocab);
}

function renderSecondaryTaskHint(viewKind) {
  const element = document.getElementById("status-secondary-task");
  const snapshot = getBackgroundTaskSnapshot(viewKind);
  if (!snapshot) {
    element.textContent = "";
    element.classList.add("hidden");
    return;
  }

  element.textContent = `后台进行中 · ${VIEW_CONFIG[snapshot.kind].title} · ${snapshot.stageLabel} · ${snapshot.progressPercent}%`;
  element.classList.remove("hidden");
}

function getBackgroundTaskSnapshot(viewKind) {
  const processingKinds = ["vocab", "feedback"].filter((kind) => {
    if (kind === viewKind) {
      return false;
    }
    return isActiveJobStatus(state.jobSnapshots[kind]?.status);
  });

  if (!processingKinds.length) {
    return null;
  }

  const preferredKind = localStorage.getItem(STORAGE_KEYS.lastTaskKind);
  if (preferredKind && processingKinds.includes(preferredKind)) {
    return state.jobSnapshots[preferredKind];
  }

  return state.jobSnapshots[processingKinds[0]];
}

function renderResultCard(viewKind, snapshot) {
  const resultCard = document.getElementById("result-card");
  const redownloadButton = document.getElementById("redownload-button");
  const previewContainer = document.getElementById("skip-reasons");
  const rowsWritten = document.getElementById("rows-written");
  const exceptionCount = document.getElementById("rows-skipped");

  if (viewKind !== "vocab" || !snapshot?.raw || (snapshot.status !== "completed" && snapshot.status !== "failed")) {
    resultCard.classList.add("hidden");
    redownloadButton.classList.add("hidden");
    return;
  }

  const job = snapshot.raw;
  const writtenRows = getWrittenRows(job);
  const exceptionItems = getExceptionItems(job);
  resultCard.classList.remove("hidden");

  if (snapshot.status === "completed") {
    rowsWritten.textContent = String(job.rows_written || writtenRows.length);
    exceptionCount.textContent = String(exceptionItems.length);
    renderExceptionPreview(exceptionItems);
    redownloadButton.classList.toggle("hidden", !job.download_url);
    redownloadButton.onclick = job.download_url ? () => triggerDownload(job.download_url) : null;
    return;
  }

  rowsWritten.textContent = "0";
  exceptionCount.textContent = String(exceptionItems.length);
  redownloadButton.classList.add("hidden");
  redownloadButton.onclick = null;
  if (exceptionItems.length) {
    renderExceptionPreview(exceptionItems);
    return;
  }
  previewContainer.innerHTML = `<div class="skip-reason-item"><strong>失败原因：</strong>${escapeHTML(job.error_message || "处理失败")}</div>`;
}

function renderExceptionPreview(exceptionItems) {
  const container = document.getElementById("skip-reasons");
  const entries = exceptionItems.slice(0, 3);
  if (!entries.length) {
    container.innerHTML = '<div class="skip-reason-item">本次没有处理异常。</div>';
    return;
  }
  container.innerHTML = entries
    .map((item) => `<div class="skip-reason-item"><strong>${escapeHTML(item.word || "")}</strong>：${escapeHTML(item.reason || "")}</div>`)
    .join("");
}

function renderResultInspector(snapshot) {
  const inspector = document.getElementById("result-inspector");
  const title = document.getElementById("result-inspector-title");
  const summary = document.getElementById("result-inspector-summary");
  const outputFilename = document.getElementById("result-output-filename");
  const writtenCount = document.getElementById("result-written-count");
  const exceptionCount = document.getElementById("result-skipped-count");
  const writtenPanel = document.getElementById("result-panel-written");
  const exceptionPanel = document.getElementById("result-panel-exception");

  if (!inspector || !title || !summary || !outputFilename || !writtenCount || !exceptionCount || !writtenPanel || !exceptionPanel) {
    return;
  }

  if (!snapshot?.raw || (snapshot.status !== "completed" && snapshot.status !== "failed")) {
    inspector.classList.add("hidden");
    return;
  }

  const job = snapshot.raw;
  const writtenRows = getWrittenRows(job);
  const exceptionItems = getExceptionItems(job);
  inspector.classList.remove("hidden");
  title.textContent = snapshot.status === "completed" ? "词表明细" : "失败结果检查";
  summary.textContent = snapshot.status === "completed"
    ? `已写入 ${writtenRows.length} 个词条，出现 ${exceptionItems.length} 条处理异常。`
    : job.error_message || "处理失败，请查看处理异常或失败原因。";
  outputFilename.textContent = job.output_filename || "-";
  writtenCount.textContent = String(job.rows_written || writtenRows.length);
  exceptionCount.textContent = String(exceptionItems.length);
  writtenPanel.innerHTML = renderWrittenRowsTable(writtenRows);
  exceptionPanel.innerHTML = renderExceptionItemsTable(exceptionItems, snapshot.status === "failed" ? job.error_message : "");
  syncResultTabButtons();
}

function renderWrittenRowsTable(rows) {
  if (!rows.length) {
    return '<div class="result-empty">当前没有可展示的写入明细。</div>';
  }

  const pagination = getPaginationState("written", rows.length);
  const pageRows = rows.slice(pagination.startIndex, pagination.endIndex);
  const body = pageRows
    .map(
      (row, index) => `
        <tr>
          <td>${pagination.startIndex + index + 1}</td>
          <td>${escapeHTML(row.word || "")}</td>
          <td>${escapeHTML(row.ipa || "")}</td>
          <td>${escapeHTML(row.pos_abbr || "")}</td>
          <td>${escapeHTML(row.zh_meaning || "")}</td>
          <td>${renderHighlightedExample(row.example || "", row.word || "")}</td>
          <td>${row.example_page == null ? "" : escapeHTML(String(row.example_page))}</td>
          <td>${renderSourceBadges(row.sources || [])}</td>
        </tr>`,
    )
    .join("");

  return `
    <div class="result-table-wrap">
      <table class="result-table">
        <thead>
          <tr>
            <th>序号</th>
            <th>单词</th>
            <th>音标</th>
            <th>词性</th>
            <th>中文意思</th>
            <th>例句</th>
            <th>页数</th>
            <th>来源</th>
          </tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
    </div>
    ${renderPagination("written", pagination)}`;
}

function renderExceptionItemsTable(items, errorMessage = "") {
  const errorBlock = errorMessage ? `<div class="result-empty">${escapeHTML(errorMessage)}</div>` : "";
  if (!items.length) {
    return errorBlock || '<div class="result-empty">当前没有处理异常。</div>';
  }

  const pagination = getPaginationState("exception", items.length);
  const pageItems = items.slice(pagination.startIndex, pagination.endIndex);
  const body = pageItems
    .map(
      (item, index) => `
        <tr>
          <td>${pagination.startIndex + index + 1}</td>
          <td>${escapeHTML(item.word || "")}</td>
          <td>${escapeHTML(item.reason || "")}</td>
          <td>${renderSourceBadges(item.sources || [])}</td>
        </tr>`,
    )
    .join("");

  return `
    ${errorBlock}
    <div class="result-table-wrap">
      <table class="result-table">
        <thead>
          <tr>
            <th>序号</th>
            <th>单词</th>
            <th>异常原因</th>
            <th>来源</th>
          </tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
    </div>
    ${renderPagination("exception", pagination)}`;
}

function getPaginationState(tab, totalItems) {
  const pagination = state.resultPagination[tab];
  const totalPages = Math.max(1, Math.ceil(totalItems / pagination.pageSize));
  pagination.page = Math.min(Math.max(1, pagination.page), totalPages);
  const startIndex = (pagination.page - 1) * pagination.pageSize;
  const endIndex = Math.min(startIndex + pagination.pageSize, totalItems);
  return {
    page: pagination.page,
    pageSize: pagination.pageSize,
    totalPages,
    totalItems,
    startIndex,
    endIndex,
  };
}

function renderPagination(tab, pagination) {
  const pageSizeOptions = PAGE_SIZE_OPTIONS
    .map((size) => `<option value="${size}" ${size === pagination.pageSize ? "selected" : ""}>${size}</option>`)
    .join("");
  const pageButtons = buildPageButtons(pagination)
    .map((item) => {
      if (item.type === "ellipsis") {
        return '<span class="result-page-ellipsis" aria-hidden="true">&hellip;</span>';
      }
      return `
        <button
          class="result-page-number ${item.page === pagination.page ? "is-active" : ""}"
          type="button"
          data-page-number="${item.page}"
          data-page-tab="${tab}"
          aria-label="跳转到第 ${item.page} 页"
          aria-current="${item.page === pagination.page ? "page" : "false"}"
        >
          ${item.page}
        </button>`;
    })
    .join("");

  return `
    <div class="result-pagination">
      <div class="result-pagination-summary">
        <span>共有 ${pagination.totalItems} 条</span>
        <label class="result-page-size-inline">
          <span>每页</span>
          <select class="result-page-size-select" data-page-size-select="${tab}">
            ${pageSizeOptions}
          </select>
          <span>条</span>
        </label>
      </div>
      <div class="result-pagination-nav">
        <button
          class="result-page-button is-icon"
          type="button"
          aria-label="上一页"
          data-page-action="prev"
          data-page-tab="${tab}"
          ${pagination.page <= 1 ? "disabled" : ""}
        >
          &lsaquo;
        </button>
        ${pageButtons}
        <button
          class="result-page-button is-icon"
          type="button"
          aria-label="下一页"
          data-page-action="next"
          data-page-tab="${tab}"
          ${pagination.page >= pagination.totalPages ? "disabled" : ""}
        >
          &rsaquo;
        </button>
      </div>
    </div>`;
}

function buildPageButtons(pagination) {
  const totalPages = pagination.totalPages;
  const currentPage = pagination.page;
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => ({ type: "page", page: index + 1 }));
  }

  const pages = new Set([1, totalPages, currentPage - 1, currentPage, currentPage + 1]);
  if (currentPage <= 3) {
    pages.add(2);
    pages.add(3);
    pages.add(4);
  }
  if (currentPage >= totalPages - 2) {
    pages.add(totalPages - 1);
    pages.add(totalPages - 2);
    pages.add(totalPages - 3);
  }

  const sortedPages = Array.from(pages)
    .filter((page) => page >= 1 && page <= totalPages)
    .sort((a, b) => a - b);

  const result = [];
  for (let index = 0; index < sortedPages.length; index += 1) {
    const page = sortedPages[index];
    const previous = sortedPages[index - 1];
    if (previous && page - previous > 1) {
      result.push({ type: "ellipsis" });
    }
    result.push({ type: "page", page });
  }
  return result;
}

function renderSourceBadges(sources) {
  const normalized = Array.from(new Set((sources || []).map(normalizeSourceLabel).filter(Boolean)));
  if (!normalized.length) {
    return '<span class="source-badge">教材</span>';
  }
  return `<div class="source-badges">${normalized.map((item) => `<span class="source-badge">${escapeHTML(item)}</span>`).join("")}</div>`;
}

function normalizeSourceLabel(source) {
  if (!source) {
    return "教材";
  }
  if (source === "manual") {
    return "手工补词";
  }
  if (source === "audio") {
    return "音频补词";
  }
  return "教材";
}

function renderHighlightedExample(example, term) {
  const text = String(example ?? "");
  const pattern = buildTermPattern(term);
  if (!pattern) {
    return escapeHTML(text);
  }

  let cursor = 0;
  let result = "";
  for (const match of text.matchAll(pattern)) {
    const prefix = match[1] || "";
    const matchedTerm = match[2] || "";
    const start = match.index + prefix.length;
    const end = start + matchedTerm.length;
    result += escapeHTML(text.slice(cursor, start));
    result += `<strong class="example-term-highlight">${escapeHTML(text.slice(start, end))}</strong>`;
    cursor = end;
  }
  result += escapeHTML(text.slice(cursor));
  return result;
}

function buildTermPattern(term) {
  const normalized = normalizeTerm(term);
  if (!normalized) {
    return null;
  }
  const parts = normalized.split(/\s+/).map(escapeRegExp).filter(Boolean);
  if (!parts.length) {
    return null;
  }
  return new RegExp(`(^|[^A-Za-z])(${parts.join("\\s+")})(?![A-Za-z])`, "gi");
}

function normalizeTerm(term) {
  return String(term ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/(^[^A-Za-z]+|[^A-Za-z]+$)/g, "")
    .toLowerCase();
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function getWrittenRows(job) {
  return Array.isArray(job?.written_rows) ? job.written_rows : [];
}

function getExceptionItems(job) {
  if (Array.isArray(job?.skipped_items)) {
    return job.skipped_items;
  }
  return Object.entries(job?.skipped_words || {}).map(([word, reason]) => ({
    word,
    reason,
    sources: [],
  }));
}

function resetResultInspectorState() {
  state.activeResultTab = "written";
  state.resultPagination.written = { page: 1, pageSize: DEFAULT_PAGE_SIZE };
  state.resultPagination.exception = { page: 1, pageSize: DEFAULT_PAGE_SIZE };
}

function getStatusContext(viewKind, snapshot) {
  if (snapshot?.jobId) {
    return `任务 ID: ${snapshot.jobId.slice(0, 8)}`;
  }
  return state.viewContextOverrides[viewKind] || VIEW_CONFIG[viewKind].defaultContext;
}

function setViewContextOverride(kind, context) {
  state.viewContextOverrides[kind] = context;
  if (state.currentTab === kind) {
    renderStatusCard();
  }
}

function renderFeedbackSections(sections) {
  const container = document.getElementById("feedback-sections");
  container.innerHTML = "";
  state.feedbackOriginals = new Map();

  sections.forEach((section) => {
    state.feedbackOriginals.set(section.key, section.content);
    const card = document.createElement("article");
    card.className = "feedback-section-card";
    card.dataset.feedbackSectionKey = section.key;
    card.innerHTML = `
      <div class="feedback-section-head">
        <h4>${escapeHTML(section.title)}</h4>
        <button class="secondary-button icon-button" type="button" data-regenerate-section="${escapeHTML(section.key)}">
          <svg><use href="#icon-refresh"></use></svg>
          <span>重新生成本模块</span>
        </button>
      </div>
      <div data-feedback-section data-feedback-section-key="${escapeHTML(section.key)}">
        <textarea data-title="${escapeHTML(section.title)}">${escapeHTML(section.content)}</textarea>
      </div>
    `;
    container.appendChild(card);
  });

  container.querySelectorAll("[data-regenerate-section]").forEach((button) => {
    button.addEventListener("click", async () => {
      const key = button.dataset.regenerateSection;
      await regenerateFeedbackSection(key, button);
    });
  });
}

async function regenerateFeedbackSection(sectionKey, button) {
  const jobId = getJobIdForKind("feedback");
  if (!jobId || !sectionKey) {
    showBanner("未找到可重新生成的反馈任务，请先重新生成反馈草稿。");
    return;
  }

  const textarea = document.querySelector(`[data-feedback-section-key="${cssEscape(sectionKey)}"] textarea`);
  if (!textarea) {
    showBanner("未找到对应的反馈模块。");
    return;
  }

  const originalLabel = button?.querySelector("span")?.textContent || "";
  if (button) {
    button.disabled = true;
    const span = button.querySelector("span");
    if (span) {
      span.textContent = "重新生成中...";
    }
  }

  try {
    const section = await requestJSON(`/v1/feedback/jobs/${jobId}/sections/${encodeURIComponent(sectionKey)}/regenerate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ draft_sections: collectFeedbackSections() }),
    });
    textarea.value = section.content || "";
    state.feedbackOriginals.set(section.key, section.content || "");
    showToast("该模块已根据课堂内容重新生成。");
  } catch (error) {
    showBanner(resolveErrorMessage(error));
  } finally {
    if (button) {
      button.disabled = false;
      const span = button.querySelector("span");
      if (span) {
        span.textContent = originalLabel || "重新生成本模块";
      }
    }
  }
}

function collectFeedbackSections() {
  return Array.from(document.querySelectorAll("[data-feedback-section] textarea"))
    .map((item) => ({
      key: item.closest("[data-feedback-section-key]")?.dataset.feedbackSectionKey || "",
      title: item.dataset.title || "",
      content: item.value || "",
    }))
    .filter((item) => item.key);
}

function renderStageList(kind) {
  const list = document.getElementById("status-stage-list");
  list.innerHTML = stageSets[kind]
    .map(([code, label]) => `<li data-stage="${code}">${label}</li>`)
    .join("");
}

function highlightStage(stageCode) {
  const items = Array.from(document.querySelectorAll("#status-stage-list li"));
  if (!stageCode || !items.some((item) => item.dataset.stage === stageCode)) {
    items.forEach((item) => item.classList.remove("active", "done"));
    return;
  }

  let activeReached = false;
  items.forEach((item) => {
    item.classList.remove("active", "done");
    if (item.dataset.stage === stageCode) {
      item.classList.add("active");
      activeReached = true;
      return;
    }
    if (!activeReached) {
      item.classList.add("done");
    }
  });
}

function resetResultCard() {
  document.getElementById("result-card")?.classList.add("hidden");
  document.getElementById("redownload-button")?.classList.add("hidden");
  const redownloadButton = document.getElementById("redownload-button");
  if (redownloadButton) {
    redownloadButton.onclick = null;
  }
  const preview = document.getElementById("skip-reasons");
  if (preview) {
    preview.innerHTML = "";
  }
  const inspector = document.getElementById("result-inspector");
  if (inspector) {
    inspector.classList.add("hidden");
  }
  syncResultTabButtons();
}

function getJobIdForKind(kind) {
  return state.jobSnapshots[kind]?.jobId || state.activeJobIds[kind] || localStorage.getItem(JOB_STORAGE_KEYS[kind]);
}

function getKindFromPanelId(panelId) {
  return Object.keys(VIEW_CONFIG).find((kind) => VIEW_CONFIG[kind].panelId === panelId) || null;
}

function isTerminalStatus(status) {
  return status === "completed" || status === "failed";
}

function isActiveJobStatus(status) {
  return status === "queued" || status === "processing";
}

function canSaveSettings() {
  return !["vocab", "feedback"].some((kind) => isActiveJobStatus(state.jobSnapshots[kind]?.status));
}

function syncSettingsSaveState() {
  const button = document.getElementById("settings-save");
  if (!button) {
    return;
  }

  const blocked = !canSaveSettings();
  button.classList.toggle("is-disabled", blocked);
  button.setAttribute("aria-disabled", String(blocked));
  if (blocked) {
    button.title = SETTINGS_SAVE_BLOCKED_MESSAGE;
    return;
  }
  button.removeAttribute("title");
}

async function uploadRecordedWords() {
  if (!state.recordedChunks.length) {
    showBanner("没有录到可识别的音频，请重试。");
    return;
  }

  const blob = new Blob(state.recordedChunks, { type: "audio/webm" });
  const formData = new FormData();
  formData.append("audio_file", blob, "manual-words.webm");

  try {
    const result = await requestJSON("/v1/audio/transcribe", { method: "POST", body: formData });
    mergeManualWords(result.candidate_words || []);
    if (result.candidate_words?.length) {
      showToast(`已补入 ${result.candidate_words.length} 个候选词。`);
    } else {
      showToast("录音已处理，但暂未识别到可补入的词。");
    }
  } catch (error) {
    showBanner(resolveErrorMessage(error));
  }
}

function mergeManualWords(nextWords) {
  const textarea = document.getElementById("words-text");
  const current = parseWords(textarea.value);
  const merged = Array.from(new Set([...current, ...nextWords.map((item) => item.trim()).filter(Boolean)]));
  textarea.value = merged.join(", ");
  syncManualWordsChips();
}

function syncManualWordsChips() {
  const textarea = document.getElementById("words-text");
  const container = document.getElementById("manual-words-chips");
  const words = parseWords(textarea.value);
  container.innerHTML = "";
  words.forEach((word) => {
    const chip = document.createElement("span");
    chip.className = "word-chip";
    chip.innerHTML = `${escapeHTML(word)}<button type="button" aria-label="删除 ${escapeHTML(word)}">×</button>`;
    chip.querySelector("button").addEventListener("click", () => {
      textarea.value = words.filter((item) => item !== word).join(", ");
      syncManualWordsChips();
    });
    container.appendChild(chip);
  });
}

function parseWords(text) {
  return Array.from(
    new Set(
      text
        .split(/[\n,;，；、]+/g)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

function triggerDownload(url) {
  if (!url) {
    return;
  }
  const link = document.createElement("a");
  link.href = url;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function copyText(text, successMessage) {
  if (!text) {
    showBanner("当前没有可复制的内容。");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    showToast(successMessage);
  } catch (_) {
    showBanner("复制失败，请检查浏览器剪贴板权限。");
  }
}

async function requestJSON(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = "请求失败";
    try {
      const data = await response.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data);
    } catch (_) {
      detail = response.statusText || detail;
    }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function resolveErrorMessage(error) {
  return error?.message || "发生未知错误。";
}

function showBanner(message) {
  const banner = document.getElementById("global-banner");
  banner.textContent = message;
  banner.classList.remove("hidden");
  window.clearTimeout(showBanner.timer);
  showBanner.timer = window.setTimeout(() => banner.classList.add("hidden"), 3600);
}

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.add("hidden"), 2600);
}

function updateMicButton() {
  const button = document.getElementById("manual-mic-button");
  if (!button) {
    return;
  }
  button.innerHTML = state.isRecording
    ? '<svg><use href="#icon-mic"></use></svg><span>停止并识别</span>'
    : '<svg><use href="#icon-mic"></use></svg><span>点麦补词</span>';
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function cssEscape(value) {
  if (window.CSS?.escape) {
    return window.CSS.escape(value);
  }
  return String(value).replace(/"/g, '\\"');
}
