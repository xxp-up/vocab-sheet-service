const STORAGE_KEYS = {
  vocabJobId: "vocab-workspace:vocab-job-id",
  feedbackJobId: "vocab-workspace:feedback-job-id",
  lastTaskKind: "vocab-workspace:last-task-kind",
  downloadedJobId: "vocab-workspace:downloaded-job-id",
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
};

const state = {
  pollTimer: null,
  activeTaskKind: "vocab",
  activeTaskId: null,
  currentDownloadUrl: null,
  feedbackOriginals: new Map(),
  isRecording: false,
  mediaRecorder: null,
  recordedChunks: [],
};

document.addEventListener("DOMContentLoaded", () => {
  bindTabs();
  bindFileInputs();
  bindVocabForm();
  bindFeedbackForm();
  bindSettingsForm();
  bindManualMic();
  hydrateDefaults();
  loadSettings();
  restoreCurrentTask();
  syncManualWordsChips();
  renderStageList("vocab");
});

function bindTabs() {
  const buttons = document.querySelectorAll("[data-tab-target]");
  const panels = document.querySelectorAll("[data-panel]");

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.tabTarget;
      buttons.forEach((item) => item.classList.toggle("active", item === button));
      panels.forEach((panel) => panel.classList.toggle("active", panel.id === target));
      if (target === "vocab-panel") {
        updateStatusContext("教材题词", "请提交教材任务或查看当前进度");
      } else if (target === "feedback-panel") {
        updateStatusContext("课后反馈", "提交反馈任务后可在右侧查看进度");
      } else {
        updateStatusContext("系统配置", "可先测试连接，再保存新的运行配置");
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

function bindVocabForm() {
  const form = document.getElementById("vocab-form");
  if (!form) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const teachingFile = document.getElementById("teaching-file").files?.[0];
    if (!teachingFile) {
      showBanner("请先选择教材文件。");
      return;
    }

    const formData = new FormData(form);
    updateStatusMode("vocab");
    updateStatusContext("教材题词", "正在提交教材题词任务");
    resetResultCard();
    setProgress({ stageLabel: "提交任务中", percent: 3, title: "教材题词", message: "正在创建任务..." });

    try {
      const created = await requestJSON("/v1/vocab/jobs", { method: "POST", body: formData });
      localStorage.setItem(STORAGE_KEYS.vocabJobId, created.job_id);
      localStorage.setItem(STORAGE_KEYS.lastTaskKind, "vocab");
      state.activeTaskKind = "vocab";
      state.activeTaskId = created.job_id;
      await pollVocabJob(created.job_id);
    } catch (error) {
      showBanner(resolveErrorMessage(error));
      setProgress({ stageLabel: "提交失败", percent: 0, title: "教材题词", message: resolveErrorMessage(error) });
    }
  });
}

function bindFeedbackForm() {
  const form = document.getElementById("feedback-form");
  const copyFeedbackButton = document.getElementById("copy-feedback-button");
  const copyHomeworkButton = document.getElementById("copy-homework-button");

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const transcript = document.getElementById("feedback-transcript").value.trim();
    const audioFile = document.getElementById("feedback-audio-file").files?.[0];
    if (!transcript && !audioFile) {
      showBanner("请提供课堂音频或逐字稿文本。");
      return;
    }

    const formData = new FormData(form);
    updateStatusMode("feedback");
    updateStatusContext("课后反馈", "正在提交课后反馈任务");
    setProgress({ stageLabel: "提交任务中", percent: 3, title: "课后反馈", message: "正在创建反馈任务..." });

    try {
      const created = await requestJSON("/v1/feedback/jobs", { method: "POST", body: formData });
      localStorage.setItem(STORAGE_KEYS.feedbackJobId, created.job_id);
      localStorage.setItem(STORAGE_KEYS.lastTaskKind, "feedback");
      state.activeTaskKind = "feedback";
      state.activeTaskId = created.job_id;
      await pollFeedbackJob(created.job_id);
    } catch (error) {
      showBanner(resolveErrorMessage(error));
      setProgress({ stageLabel: "提交失败", percent: 0, title: "课后反馈", message: resolveErrorMessage(error) });
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
    try {
      const payload = collectSettingsPayload();
      const response = await requestJSON("/v1/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      applySettings(response);
      document.getElementById("vision-api-key").value = "";
      showToast("配置已保存，新任务将使用最新设置。");
      updateStatusContext("系统配置", "配置保存成功");
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
      showToast(response.detail || "连接校验通过。");
      updateStatusContext("系统配置", "连接校验通过");
    } catch (error) {
      showBanner(resolveErrorMessage(error));
      updateStatusContext("系统配置", "连接校验失败");
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
    } catch (error) {
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

function restoreCurrentTask() {
  const lastTaskKind = localStorage.getItem(STORAGE_KEYS.lastTaskKind);
  const vocabJobId = localStorage.getItem(STORAGE_KEYS.vocabJobId);
  const feedbackJobId = localStorage.getItem(STORAGE_KEYS.feedbackJobId);

  if (lastTaskKind === "feedback" && feedbackJobId) {
    state.activeTaskKind = "feedback";
    state.activeTaskId = feedbackJobId;
    updateStatusMode("feedback");
    pollFeedbackJob(feedbackJobId);
    return;
  }

  if (vocabJobId) {
    state.activeTaskKind = "vocab";
    state.activeTaskId = vocabJobId;
    updateStatusMode("vocab");
    pollVocabJob(vocabJobId);
    return;
  }

  if (feedbackJobId) {
    state.activeTaskKind = "feedback";
    state.activeTaskId = feedbackJobId;
    updateStatusMode("feedback");
    pollFeedbackJob(feedbackJobId);
  }
}

async function pollVocabJob(jobId) {
  clearPoller();
  updateStatusMode("vocab");
  updateStatusContext("教材题词", `任务 ID: ${jobId.slice(0, 8)}`);
  await refreshVocabJob(jobId);
  state.pollTimer = window.setInterval(() => refreshVocabJob(jobId), 1800);
}

async function refreshVocabJob(jobId) {
  try {
    const job = await requestJSON(`/v1/vocab/jobs/${jobId}`);
    state.activeTaskKind = "vocab";
    state.activeTaskId = jobId;
    renderVocabJob(job);
    if (job.status === "completed" || job.status === "failed") {
      clearPoller();
    }
  } catch (error) {
    clearPoller();
    if (error.status === 404) {
      localStorage.removeItem(STORAGE_KEYS.vocabJobId);
    }
    showBanner(resolveErrorMessage(error));
  }
}

async function pollFeedbackJob(jobId) {
  clearPoller();
  updateStatusMode("feedback");
  updateStatusContext("课后反馈", `任务 ID: ${jobId.slice(0, 8)}`);
  await refreshFeedbackJob(jobId);
  state.pollTimer = window.setInterval(() => refreshFeedbackJob(jobId), 1800);
}

async function refreshFeedbackJob(jobId) {
  try {
    const job = await requestJSON(`/v1/feedback/jobs/${jobId}`);
    state.activeTaskKind = "feedback";
    state.activeTaskId = jobId;
    renderFeedbackJob(job);
    if (job.status === "completed" || job.status === "failed") {
      clearPoller();
    }
  } catch (error) {
    clearPoller();
    if (error.status === 404) {
      localStorage.removeItem(STORAGE_KEYS.feedbackJobId);
    }
    showBanner(resolveErrorMessage(error));
  }
}

function renderVocabJob(job) {
  const message = job.status === "failed"
    ? job.error_message || "处理失败，请检查输入文件。"
    : job.status === "completed"
      ? "处理完成，系统已准备下载文件。"
      : "系统正在处理教材，请稍候。";
  setProgress({
    stageLabel: job.stage_label,
    percent: job.progress_percent,
    title: "教材题词",
    message,
    stageCode: job.stage_code,
  });

  const resultCard = document.getElementById("result-card");
  const redownloadButton = document.getElementById("redownload-button");
  const skipReasons = document.getElementById("skip-reasons");
  const rowsWritten = document.getElementById("rows-written");
  const rowsSkipped = document.getElementById("rows-skipped");

  if (job.status === "completed") {
    rowsWritten.textContent = String(job.rows_written || 0);
    rowsSkipped.textContent = String(Object.keys(job.skipped_words || {}).length);
    resultCard.classList.remove("hidden");
    renderSkipReasons(job.skipped_words || {});
    state.currentDownloadUrl = job.download_url;
    redownloadButton.classList.toggle("hidden", !job.download_url);
    redownloadButton.onclick = () => triggerDownload(job.download_url);
    const alreadyDownloaded = localStorage.getItem(STORAGE_KEYS.downloadedJobId);
    if (job.download_url && alreadyDownloaded !== job.job_id) {
      triggerDownload(job.download_url);
      localStorage.setItem(STORAGE_KEYS.downloadedJobId, job.job_id);
      showToast("词表已生成，开始自动下载。");
    }
  } else if (job.status === "failed") {
    resultCard.classList.remove("hidden");
    redownloadButton.classList.add("hidden");
    rowsWritten.textContent = "0";
    rowsSkipped.textContent = String(Object.keys(job.skipped_words || {}).length);
    skipReasons.innerHTML = `<div class="skip-reason-item"><strong>失败原因：</strong>${escapeHTML(job.error_message || "处理失败")}</div>`;
  } else {
    resultCard.classList.add("hidden");
    redownloadButton.classList.add("hidden");
  }
}

function renderFeedbackJob(job) {
  const message = job.status === "failed"
    ? job.error_message || "生成失败，请检查课堂内容。"
    : job.status === "completed"
      ? "反馈草稿已生成，可在左侧继续编辑。"
      : "系统正在整理源材料并生成反馈草稿。";

  setProgress({
    stageLabel: job.stage_label,
    percent: job.progress_percent,
    title: "课后反馈",
    message,
    stageCode: job.stage_code,
  });

  if (job.status === "completed") {
    localStorage.setItem(STORAGE_KEYS.feedbackJobId, job.job_id);
    renderFeedbackSections(job.draft_sections || []);
    document.getElementById("feedback-editor").classList.remove("hidden");
    showToast("课后反馈草稿已准备好。");
  }

  if (job.status === "failed") {
    document.getElementById("feedback-editor").classList.add("hidden");
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
  const jobId = state.activeTaskKind === "feedback"
    ? state.activeTaskId
    : localStorage.getItem(STORAGE_KEYS.feedbackJobId);
  if (!jobId || !sectionKey) {
    showBanner("未找到可重生成的反馈任务，请先重新生成反馈草稿。");
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
    showToast("该模块已根据原始课堂内容重新生成。");
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
  return Array.from(document.querySelectorAll("[data-feedback-section] textarea")).map((item) => ({
    key: item.closest("[data-feedback-section-key]")?.dataset.feedbackSectionKey || "",
    title: item.dataset.title || "",
    content: item.value || "",
  })).filter((item) => item.key);
}

function renderSkipReasons(skippedWords) {
  const container = document.getElementById("skip-reasons");
  const entries = Object.entries(skippedWords).slice(0, 3);
  if (!entries.length) {
    container.innerHTML = '<div class="skip-reason-item">没有需要提示的跳过项。</div>';
    return;
  }
  container.innerHTML = entries
    .map(([word, reason]) => `<div class="skip-reason-item"><strong>${escapeHTML(word)}</strong>：${escapeHTML(reason)}</div>`)
    .join("");
}

function renderStageList(kind) {
  const list = document.getElementById("vocab-stage-list");
  list.innerHTML = stageSets[kind]
    .map(([code, label]) => `<li data-stage="${code}">${label}</li>`)
    .join("");
}

function updateStatusMode(kind) {
  if (state.activeTaskKind !== kind) {
    renderStageList(kind);
  }
  state.activeTaskKind = kind;
}

function updateStatusContext(title, context) {
  document.getElementById("status-title").textContent = title;
  document.getElementById("status-context").textContent = context;
}

function setProgress({ stageLabel, percent, title, message, stageCode }) {
  document.getElementById("status-title").textContent = title;
  document.getElementById("progress-label").textContent = stageLabel;
  document.getElementById("progress-percent").textContent = `${percent}%`;
  document.getElementById("progress-bar").style.width = `${Math.max(0, Math.min(100, percent))}%`;
  document.getElementById("status-message").textContent = message;
  highlightStage(stageCode);
}

function highlightStage(stageCode) {
  const items = Array.from(document.querySelectorAll("#vocab-stage-list li"));
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
  document.getElementById("result-card").classList.add("hidden");
  document.getElementById("redownload-button").classList.add("hidden");
  document.getElementById("skip-reasons").innerHTML = "";
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
  const parts = text
    .split(/[\n,;，；]+/g)
    .map((item) => item.trim())
    .filter(Boolean);
  return Array.from(new Set(parts));
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
  } catch (error) {
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

function clearPoller() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
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
