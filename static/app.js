import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.min.mjs";
import DOMPurify from "https://cdn.jsdelivr.net/npm/dompurify@3.2.6/dist/purify.es.mjs";
import { marked } from "https://cdn.jsdelivr.net/npm/marked@15.0.12/lib/marked.esm.js";
import { linkifyChatPageReferences } from "./chat_references.js";
import {
  createHighlightNavigationController,
  highlightSourceRects,
} from "./highlight-navigation.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.4.168/pdf.worker.min.mjs";

marked.setOptions({
  breaks: true,
  gfm: true,
});

const HIGHLIGHT_FACETS = [
  { id: "all", label: "All" },
  { id: "problem", label: "Problem" },
  { id: "solution", label: "Solution" },
  { id: "novelty", label: "Novelty" },
  { id: "method", label: "Method" },
  { id: "benchmarking", label: "Benchmarking" },
  { id: "result", label: "Result" },
  { id: "ablation", label: "Ablation" },
  { id: "hyperparams", label: "Hyperparams" },
  { id: "tradeoff", label: "Tradeoff" },
  { id: "limitation", label: "Limitation" },
  { id: "failure", label: "Failure" },
];

const DEFAULT_HIGHLIGHT_COLORS = {
  goal: "#0040ff",
  problem: "#0040ff",
  solution: "#00c000",
  method: "#00ffff",
  novelty: "#8000ff",
  benchmarking: "#7a3e00",
  result: "#ffd400",
  ablation: "#80ff00",
  hyperparams: "#404040",
  tradeoff: "#ff7000",
  limitation: "#ff00d4",
  failure: "#ff002b",
  important: "#808080",
};

const HIGHLIGHT_LABEL_ALIASES = {
  goal: "problem",
  objective: "problem",
  task: "problem",
  approach: "solution",
  contribution: "novelty",
  benchmark: "benchmarking",
  benchmarks: "benchmarking",
  evaluation: "benchmarking",
  compute: "hyperparams",
  computing: "hyperparams",
  hyperparameter: "hyperparams",
  hyperparameters: "hyperparams",
  hardware: "hyperparams",
  runtime: "hyperparams",
  "training-cost": "hyperparams",
  "model-size": "hyperparams",
  ablations: "ablation",
  "ablation-study": "ablation",
  failures: "failure",
  "failure-mode": "failure",
  "failure-modes": "failure",
};

const PDF_ZOOM_MIN = 0.6;
const PDF_ZOOM_MAX = 2.4;
const PDF_ZOOM_STEP = 0.1;
const MODEL_SETTINGS_KEY = "papersprint.modelSettings";
const CUSTOM_MODEL_VALUE = "__custom__";

const state = {
  papers: [],
  selectedPaper: null,
  settings: null,
  providerModelOptions: {},
  chatMessages: [],
  renderToken: 0,
  pdfDocument: null,
  pdfLoadingTask: null,
  analysisPoll: null,
  figurePoll: null,
  uploadPromise: null,
  pageTexts: new Map(),
  pageWords: new Map(),
  textSelectionDrag: null,
  activeSelection: null,
  activeCitation: null,
  activeHighlightIndex: null,
  pendingCitationContext: null,
  activeFigure: null,
  activeHighlightFacet: "all",
  pdfZoom: 1,
  leftPanelCollapsed: false,
  rightPanelCollapsed: false,
  figureAnalysisRunning: false,
  figurePopoverDrag: null,
  selectedFigures: [],
  summaryEvidenceTargets: [],
};

const els = {
  workspace: document.querySelector(".workspace"),
  uploadForm: document.getElementById("upload-form"),
  pdfInput: document.getElementById("pdf-input"),
  providerSelect: document.getElementById("provider-select"),
  textModelInput: document.getElementById("text-model-input"),
  apiKeyInput: document.getElementById("api-key-input"),
  analyzeButton: document.getElementById("analyze-button"),
  providerStatus: document.getElementById("provider-status"),
  refreshButton: document.getElementById("refresh-button"),
  paperList: document.getElementById("paper-list"),
  assistantPanel: document.querySelector(".assistant-panel"),
  leftPanelToggle: document.getElementById("left-panel-toggle"),
  rightPanelToggle: document.getElementById("right-panel-toggle"),
  summaryPanel: document.querySelector(".summary-panel"),
  summaryResizeHandle: document.getElementById("summary-resize-handle"),
  takeawaysSection: document.querySelector(".takeaways-section"),
  chatResizeHandle: document.getElementById("chat-resize-handle"),
  readerPanel: document.querySelector(".reader-panel"),
  readerEmpty: document.getElementById("reader-empty"),
  pdfViewer: document.getElementById("pdf-viewer"),
  pdfZoomControls: document.getElementById("pdf-zoom-controls"),
  pdfZoomOutButton: document.getElementById("pdf-zoom-out-button"),
  pdfZoomInButton: document.getElementById("pdf-zoom-in-button"),
  pdfZoomLabel: document.getElementById("pdf-zoom-label"),
  highlightCount: document.getElementById("highlight-count"),
  highlightFilterStatus: document.getElementById("highlight-filter-status"),
  highlightFilters: document.getElementById("highlight-filters"),
  previousHighlightButton: document.getElementById("previous-highlight-button"),
  nextHighlightButton: document.getElementById("next-highlight-button"),
  highlightList: document.getElementById("highlight-list"),
  paperProvider: document.getElementById("paper-provider"),
  paperTitle: document.getElementById("paper-title"),
  paperOverview: document.getElementById("paper-overview"),
  backgroundSection: document.getElementById("background-section"),
  backgroundNotes: document.getElementById("background-notes"),
  takeawaysTab: document.getElementById("takeaways-tab"),
  chatStatus: document.getElementById("chat-status"),
  chatFigureFocus: document.getElementById("chat-figure-focus"),
  chatMessages: document.getElementById("chat-messages"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  chatResetButton: document.getElementById("chat-reset-button"),
  webToggle: document.getElementById("web-toggle"),
  selectionPopover: document.getElementById("selection-popover"),
  copySelectionButton: document.getElementById("copy-selection-button"),
  explainSelectionButton: document.getElementById("explain-selection-button"),
  addSelectionHighlightButton: document.getElementById("add-selection-highlight-button"),
  selectionHighlightForm: document.getElementById("selection-highlight-form"),
  highlightTextInput: document.getElementById("highlight-text-input"),
  highlightCategorySelect: document.getElementById("highlight-category-select"),
  highlightCategoryInput: document.getElementById("highlight-category-input"),
  highlightColorInput: document.getElementById("highlight-color-input"),
  highlightPopover: document.getElementById("highlight-popover"),
  figurePopover: document.getElementById("figure-popover"),
  citationPopover: document.getElementById("citation-popover"),
  toast: document.getElementById("toast"),
};

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function briefText(value = "", maxLength = 240) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength).replace(/\s+\S*$/, "").trim()}...`;
}

function highlightLabelId(value = "") {
  const id = String(value || "important")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "important";
  return HIGHLIGHT_LABEL_ALIASES[id] || id;
}

function highlightLabelText(value = "") {
  const id = highlightLabelId(value);
  const facet = HIGHLIGHT_FACETS.find((item) => item.id === id);
  if (facet) {
    return facet.label;
  }
  return String(value || "highlight").trim() || "highlight";
}

function safeHexColor(value) {
  const color = String(value || "").trim();
  return /^#[0-9a-f]{6}$/i.test(color) ? color : "";
}

function hexToRgba(hex, alpha) {
  const color = safeHexColor(hex);
  if (!color) {
    return "";
  }
  const value = Number.parseInt(color.slice(1), 16);
  const red = (value >> 16) & 255;
  const green = (value >> 8) & 255;
  const blue = value & 255;
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function highlightColor(highlight) {
  return safeHexColor(highlight?.color) || DEFAULT_HIGHLIGHT_COLORS[highlightLabelId(highlight?.label)] || "";
}

function customHighlightStyle(highlight) {
  const color = highlightColor(highlight);
  if (!color || !safeHexColor(highlight?.color)) {
    return "";
  }
  return ` style="background: ${hexToRgba(color, 0.24)}; color: var(--ink);"`;
}

function facetChipStyle(facet) {
  const color = safeHexColor(facet?.color);
  if (!color) {
    return "";
  }
  return ` style="--facet-color: ${color}; --facet-bg: ${hexToRgba(color, 0.32)};"`;
}

function showToast(message, sticky = false) {
  if (!els.toast) {
    return;
  }
  els.toast.textContent = message;
  els.toast.classList.remove("hidden");
  if (!sticky) {
    window.setTimeout(() => els.toast.classList.add("hidden"), 3200);
  }
}

function hideToast() {
  if (!els.toast) {
    return;
  }
  els.toast.classList.add("hidden");
}

function setHtml(target, html) {
  if (!target) {
    return;
  }
  target.innerHTML = html;
}

function setLoadingButton(button, isLoading, label) {
  if (!button) {
    return;
  }
  button.classList.toggle("is-loading", isLoading);
  button.setAttribute("aria-busy", isLoading ? "true" : "false");
  const labelNode = button.querySelector(".button-label");
  if (labelNode) {
    labelNode.textContent = label;
  } else {
    button.textContent = label;
  }
}

function resizeChatInput() {
  if (!els.chatInput) {
    return;
  }

  const style = window.getComputedStyle(els.chatInput);
  const lineHeight = Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.35 || 18;
  const verticalPadding = Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom);
  const verticalBorder = Number.parseFloat(style.borderTopWidth) + Number.parseFloat(style.borderBottomWidth);
  const maxHeight = Math.ceil(lineHeight * 5 + verticalPadding + verticalBorder);

  els.chatInput.style.height = "auto";
  els.chatInput.style.height = `${Math.min(els.chatInput.scrollHeight + verticalBorder, maxHeight)}px`;
  els.chatInput.style.overflowY = els.chatInput.scrollHeight + verticalBorder > maxHeight ? "auto" : "hidden";
}

function submitChatOnEnter(event) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
    return;
  }
  event.preventDefault();
  els.chatForm?.requestSubmit();
}

function setSummaryPanelSplit(clientY) {
  if (!els.assistantPanel || !els.summaryResizeHandle) {
    return;
  }

  const panelRect = els.assistantPanel.getBoundingClientRect();
  const handleHeight = els.summaryResizeHandle.getBoundingClientRect().height || 8;
  const minSummaryHeight = 72;
  const minTakeawaysHeight = 90;
  const minChatHeight = 180;
  const maxSummaryHeight = Math.max(
    minSummaryHeight,
    panelRect.height - handleHeight * 2 - minTakeawaysHeight - minChatHeight,
  );
  const nextSummaryHeight = Math.min(
    maxSummaryHeight,
    Math.max(minSummaryHeight, clientY - panelRect.top),
  );
  els.assistantPanel.style.setProperty("--summary-panel-height", `${Math.round(nextSummaryHeight)}px`);
}

function currentSummaryPanelHeight() {
  return els.summaryPanel?.getBoundingClientRect().height || 0;
}

function startSummaryPanelResize(event) {
  if (!els.assistantPanel) {
    return;
  }

  event.preventDefault();
  els.assistantPanel.classList.add("is-resizing-summary");
  const pointerId = event.pointerId;
  els.summaryResizeHandle?.setPointerCapture?.(pointerId);
  setSummaryPanelSplit(event.clientY);

  const onPointerMove = (moveEvent) => {
    setSummaryPanelSplit(moveEvent.clientY);
  };
  const onPointerUp = () => {
    els.assistantPanel?.classList.remove("is-resizing-summary");
    els.summaryResizeHandle?.releasePointerCapture?.(pointerId);
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
  };

  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp, { once: true });
}

function setTakeawaysPanelSplit(clientY) {
  if (!els.assistantPanel || !els.takeawaysSection || !els.chatResizeHandle) {
    return;
  }

  const panelRect = els.assistantPanel.getBoundingClientRect();
  const takeawaysRect = els.takeawaysSection.getBoundingClientRect();
  const handleHeight = els.chatResizeHandle.getBoundingClientRect().height || 8;
  const minTakeawaysHeight = 90;
  const minChatHeight = 180;
  const maxTakeawaysHeight = Math.max(
    minTakeawaysHeight,
    panelRect.bottom - takeawaysRect.top - handleHeight - minChatHeight,
  );
  const nextHeight = clamp(clientY - takeawaysRect.top, minTakeawaysHeight, maxTakeawaysHeight);
  els.assistantPanel.style.setProperty("--takeaways-panel-height", `${Math.round(nextHeight)}px`);
}

function currentTakeawaysHeight() {
  return els.takeawaysSection?.getBoundingClientRect().height || 0;
}

function startTakeawaysPanelResize(event) {
  if (!els.assistantPanel || !els.takeawaysSection) {
    return;
  }

  event.preventDefault();
  els.assistantPanel.classList.add("is-resizing-takeaways");
  const pointerId = event.pointerId;
  els.chatResizeHandle?.setPointerCapture?.(pointerId);
  setTakeawaysPanelSplit(event.clientY);

  const onPointerMove = (moveEvent) => {
    setTakeawaysPanelSplit(moveEvent.clientY);
  };
  const onPointerUp = () => {
    els.assistantPanel?.classList.remove("is-resizing-takeaways");
    els.chatResizeHandle?.releasePointerCapture?.(pointerId);
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
  };

  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp, { once: true });
}

function resetPaperViewport() {
  window.scrollTo(0, 0);
  if (els.readerPanel) {
    els.readerPanel.scrollTop = 0;
    els.readerPanel.scrollLeft = 0;
  }
  if (els.pdfViewer) {
    els.pdfViewer.scrollTop = 0;
  }
  if (els.chatMessages) {
    els.chatMessages.scrollTop = 0;
  }
}

function clampPdfZoom(value) {
  const rounded = Math.round(Number(value) * 10) / 10;
  return Math.min(PDF_ZOOM_MAX, Math.max(PDF_ZOOM_MIN, rounded || 1));
}

function pdfScrollAnchor() {
  const scroller = els.readerPanel;
  if (!scroller) {
    return null;
  }
  return {
    leftRatio: (scroller.scrollLeft + scroller.clientWidth / 2) / Math.max(1, scroller.scrollWidth),
    topRatio: (scroller.scrollTop + scroller.clientHeight / 2) / Math.max(1, scroller.scrollHeight),
  };
}

function restorePdfScrollAnchor(anchor) {
  const scroller = els.readerPanel;
  if (!scroller || !anchor) {
    return;
  }
  scroller.scrollLeft = Math.max(0, anchor.leftRatio * scroller.scrollWidth - scroller.clientWidth / 2);
  scroller.scrollTop = Math.max(0, anchor.topRatio * scroller.scrollHeight - scroller.clientHeight / 2);
}

function syncPdfZoomControls() {
  const hasPaper = Boolean(state.selectedPaper);
  els.pdfZoomControls?.classList.toggle("hidden", !hasPaper);
  if (els.pdfZoomLabel) {
    els.pdfZoomLabel.textContent = `${Math.round(state.pdfZoom * 100)}%`;
  }
  if (els.pdfZoomOutButton) {
    els.pdfZoomOutButton.disabled = !hasPaper || state.pdfZoom <= PDF_ZOOM_MIN;
  }
  if (els.pdfZoomInButton) {
    els.pdfZoomInButton.disabled = !hasPaper || state.pdfZoom >= PDF_ZOOM_MAX;
  }
}

function syncPanelToggles() {
  els.workspace?.classList.toggle("left-panel-collapsed", state.leftPanelCollapsed);
  els.workspace?.classList.toggle("right-panel-collapsed", state.rightPanelCollapsed);

  if (els.leftPanelToggle) {
    const label = state.leftPanelCollapsed ? "Show left panel" : "Hide left panel";
    els.leftPanelToggle.textContent = state.leftPanelCollapsed ? "›" : "‹";
    els.leftPanelToggle.title = label;
    els.leftPanelToggle.setAttribute("aria-label", label);
    els.leftPanelToggle.setAttribute("aria-pressed", String(state.leftPanelCollapsed));
  }

  if (els.rightPanelToggle) {
    const label = state.rightPanelCollapsed ? "Show right panel" : "Hide right panel";
    els.rightPanelToggle.textContent = state.rightPanelCollapsed ? "‹" : "›";
    els.rightPanelToggle.title = label;
    els.rightPanelToggle.setAttribute("aria-label", label);
    els.rightPanelToggle.setAttribute("aria-pressed", String(state.rightPanelCollapsed));
  }
}

async function setPdfZoom(nextZoom) {
  if (!state.selectedPaper) {
    return;
  }
  const zoom = clampPdfZoom(nextZoom);
  if (zoom === state.pdfZoom) {
    return;
  }
  state.pdfZoom = zoom;
  syncPdfZoomControls();
  await renderPdfPreservingScroll(state.selectedPaper);
  syncPdfZoomControls();
}

function apiErrorMessage(payload, fallback) {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (detail && typeof detail === "object") {
    if (typeof detail.message === "string" && detail.message.trim()) {
      return detail.message;
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  return fallback;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { detail: text };
    }
  }
  if (!response.ok) {
    throw new Error(apiErrorMessage(payload, response.statusText));
  }
  return payload;
}

function storedModelSettings(provider = selectedProvider()) {
  try {
    const stored = JSON.parse(window.localStorage.getItem(MODEL_SETTINGS_KEY) || "{}");
    return stored.providers?.[provider] || (provider === "codex" ? stored : {});
  } catch {
    return {};
  }
}

function saveModelSettings() {
  let stored = {};
  try {
    stored = JSON.parse(window.localStorage.getItem(MODEL_SETTINGS_KEY) || "{}");
  } catch {
    stored = {};
  }
  const settings = { textModel: selectedTextModel() };
  const providers = {
    ...(stored.providers || {}),
    [selectedProvider()]: settings,
  };
  window.localStorage.setItem(MODEL_SETTINGS_KEY, JSON.stringify({ ...settings, providers }));
}

function populateEffortSelect(select, efforts, selected) {
  if (!select) {
    return;
  }
  const options = Array.from(new Set((efforts || []).map((effort) => String(effort || "").trim()).filter(Boolean)));
  const selectedEffort = options.includes(selected) ? selected : options[0] || "high";
  select.value = selectedEffort;
  const picker = select.closest(".effort-picker");
  if (!picker) {
    return;
  }
  const button = picker.querySelector("[data-effort-button]");
  const menu = picker.querySelector(".effort-menu");
  if (button) {
    button.textContent = selectedEffort;
  }
  setHtml(
    menu,
    options.map((effort) => {
      const isSelected = effort === selectedEffort ? "true" : "false";
      return `<button type="button" role="option" data-effort-option="${escapeHtml(effort)}" aria-selected="${isSelected}">${escapeHtml(effort)}</button>`;
    }).join(""),
  );
}

function closeEffortPickers(exceptPicker = null) {
  document.querySelectorAll(".effort-picker").forEach((picker) => {
    if (picker === exceptPicker) {
      return;
    }
    picker.querySelector(".effort-menu")?.classList.add("hidden");
    picker.querySelector("[data-effort-button]")?.setAttribute("aria-expanded", "false");
  });
}

function toggleEffortPicker(button) {
  const picker = button.closest(".effort-picker");
  if (!picker) {
    return;
  }
  const menu = picker.querySelector(".effort-menu");
  const isOpen = !menu?.classList.contains("hidden");
  closeEffortPickers(picker);
  menu?.classList.toggle("hidden", isOpen);
  button.setAttribute("aria-expanded", String(!isOpen));
}

function selectEffortOption(option) {
  const picker = option.closest(".effort-picker");
  const input = picker?.querySelector("input[type='hidden']");
  const button = picker?.querySelector("[data-effort-button]");
  if (!input || !button) {
    return;
  }
  input.value = option.dataset.effortOption || "high";
  button.textContent = input.value;
  picker.querySelectorAll("[data-effort-option]").forEach((node) => {
    node.setAttribute("aria-selected", String(node === option));
  });
  input.dispatchEvent(new Event("change", { bubbles: true }));
  closeEffortPickers();
}

function providerRequiresApiKey(provider = selectedProvider()) {
  return provider === "openai" || provider === "openrouter";
}

function providerApiKeyLabel(provider = selectedProvider()) {
  return provider === "openrouter" ? "OpenRouter API key" : "OpenAI API key";
}

function currentProviderModels(settings) {
  const provider = selectedProvider();
  return state.providerModelOptions[provider]
    || settings.provider_model_options?.[provider]
    || settings.model_options
    || [];
}

function availableModels(settings, ...extraModels) {
  const models = [
    ...currentProviderModels(settings),
    ...extraModels,
    settings.default_text_model,
  ]
    .map((model) => String(model || "").trim())
    .filter(Boolean);
  return Array.from(new Set(models));
}

function populateModelSelect(select, models, selected) {
  if (!select) {
    return;
  }
  const selectedModel = String(selected || "").trim();
  const options = models.includes(selectedModel) || !selectedModel
    ? models
    : [selectedModel, ...models];
  setHtml(
    select,
    [
      ...options.map((model) => {
        const isSelected = model === selectedModel ? " selected" : "";
        return `<option value="${escapeHtml(model)}"${isSelected}>${escapeHtml(model)}</option>`;
      }),
      `<option value="${CUSTOM_MODEL_VALUE}">Custom...</option>`,
    ].join(""),
  );
}

function setModelOptions(settings) {
  const stored = storedModelSettings();
  const providerModels = availableModels(settings);
  const textModel = stored.textModel || providerModels[0] || settings.default_text_model || "gpt-5.5";
  populateModelSelect(els.textModelInput, providerModels, textModel);
}

function setProviderOptions(settings) {
  if (settings.default_provider && els.providerSelect) {
    els.providerSelect.value = settings.default_provider;
  }
  setModelOptions(settings);
  const parts = [];
  parts.push(settings.codex_available ? "Codex ready" : "Codex unavailable");
  parts.push(settings.openai_available ? "OpenAI key set" : "No OpenAI key");
  parts.push(settings.openrouter_available ? "OpenRouter key set" : "No OpenRouter key");
  if (els.providerStatus) {
    els.providerStatus.textContent = parts.join("\n");
  }
  syncApiKeyInput();
}

async function loadSettings() {
  const settings = await requestJson("/api/settings");
  state.settings = settings;
  setProviderOptions(settings);
  refreshProviderModels().catch(() => {});
}

function selectedProvider() {
  return els.providerSelect?.value || "codex";
}

function requestApiKey() {
  return providerRequiresApiKey() ? els.apiKeyInput?.value.trim() || "" : "";
}

function selectedTextModel() {
  const value = els.textModelInput?.value.trim();
  return value && value !== CUSTOM_MODEL_VALUE ? value : state.settings?.default_text_model || "gpt-5.5";
}

function selectedVisionModel() {
  const value = els.visionModelInput?.value.trim();
  return value && value !== CUSTOM_MODEL_VALUE ? value : state.settings?.default_vision_model || selectedTextModel();
}

function selectedTextEffort() {
  return "high";
}

function selectedVisionEffort() {
  return els.visionEffortSelect?.value || state.settings?.default_vision_reasoning_effort || selectedTextEffort();
}

function setCustomModel(select, model) {
  if (!select || !model) {
    return;
  }
  if (![...select.options].some((option) => option.value === model)) {
    const option = new Option(model, model);
    select.insertBefore(option, select.querySelector(`option[value="${CUSTOM_MODEL_VALUE}"]`));
  }
  select.value = model;
}

function handleModelSelectChange(select, fallbackModel) {
  if (!select || select.value !== CUSTOM_MODEL_VALUE) {
    return;
  }

  const customModel = window.prompt("Enter model name", fallbackModel || "gpt-5.5");
  const cleanModel = String(customModel || "").replace(/\s+/g, " ").trim();
  if (!cleanModel) {
    select.value = fallbackModel || state.settings?.default_text_model || "gpt-5.5";
    return;
  }
  setCustomModel(select, cleanModel);
}

function textModelRequestOptions() {
  return { model: selectedTextModel() };
}

function visionModelRequestOptions() {
  return {
    model: selectedVisionModel(),
    reasoning_effort: selectedVisionEffort(),
  };
}

function syncApiKeyInput() {
  if (!els.apiKeyInput) {
    return;
  }
  const needsKey = providerRequiresApiKey();
  els.apiKeyInput.classList.toggle("hidden", !needsKey);
  els.apiKeyInput.placeholder = providerApiKeyLabel();
  els.apiKeyInput.setAttribute("aria-label", providerApiKeyLabel());
}

function requireOpenAiKey() {
  if (!providerRequiresApiKey() || requestApiKey()) {
    return true;
  }
  showToast(`Enter an ${providerApiKeyLabel()}`);
  els.apiKeyInput?.focus();
  return false;
}

async function refreshProviderModels() {
  if (!state.settings) {
    return;
  }
  const provider = selectedProvider();
  const payload = await requestJson("/api/models", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider,
      api_key: requestApiKey() || null,
    }),
  });
  state.providerModelOptions[provider] = payload.model_options || [];
  setModelOptions(state.settings);
}

async function loadPapers(selectFirst = true) {
  const payload = await requestJson("/api/papers");
  await applyPaperSummaries(payload.papers || [], selectFirst);
}

async function applyPaperSummaries(papers, selectFirst = true) {
  state.papers = papers;
  if (state.selectedPaper && !state.papers.some((paper) => paper.id === state.selectedPaper.id)) {
    state.selectedPaper = null;
    syncPaperActions();
  }
  renderPaperList();
  if (selectFirst && state.papers.length && !state.selectedPaper) {
    await selectPaper(state.papers[0].id);
  } else if (!state.papers.length) {
    clearSelectedPaper();
  }
}

async function refreshPapersFromCache() {
  showToast("Loading cached papers", true);
  const selectedId = state.selectedPaper?.id || null;
  const payload = await requestJson("/api/papers/refresh-cache", { method: "POST" });
  await applyPaperSummaries(payload.papers || [], false);

  const nextId = selectedId && state.papers.some((paper) => paper.id === selectedId)
    ? selectedId
    : state.papers[0]?.id;
  if (nextId) {
    await selectPaper(nextId);
  } else {
    clearSelectedPaper();
  }

  hideToast();
  showToast(`Loaded ${payload.loaded_count || 0} cached paper${payload.loaded_count === 1 ? "" : "s"}`);
}

function renderPaperList() {
  if (!state.papers.length) {
    setHtml(els.paperList, `<div class="muted-box">No PDFs loaded</div>`);
    return;
  }

  setHtml(
    els.paperList,
    state.papers
      .map((paper) => {
      const active = state.selectedPaper?.id === paper.id ? "active" : "";
      const warning = paper.warnings?.length ? `<span class="warning-dot" title="Warnings"></span>` : "";
      const citationText = paper.citation_count ? ` · ${paper.citation_count} citations` : "";
      const statusText = paper.analysis_status === "ready"
        ? `ready to analyze${citationText}`
        : paper.analysis_status === "analyzing"
          ? "analyzing"
          : paper.analysis_status === "error"
            ? "analysis failed"
            : paper.figure_analysis_status === "running"
              ? `${paper.highlight_count || 0} highlights · figures running${citationText}`
            : `${paper.highlight_count || 0} highlights${citationText} · ${escapeHtml(paper.provider_used || "unknown")}`;
      return `
        <article class="paper-card ${active}">
          <button class="paper-card-main" data-paper-id="${paper.id}" type="button">
            <strong>${escapeHtml(paper.title || paper.filename)}</strong>
            <span>${statusText}</span>
          </button>
          <button class="paper-remove-button" data-remove-paper-id="${paper.id}" title="Remove paper" type="button" aria-label="Remove paper">
            ×
          </button>
          ${warning}
        </article>
      `;
      })
      .join(""),
  );

  els.paperList?.querySelectorAll("[data-paper-id]").forEach((button) => {
    button.addEventListener("click", () => selectPaper(button.dataset.paperId));
  });
  els.paperList?.querySelectorAll("[data-remove-paper-id]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      removePaper(button.dataset.removePaperId).catch((error) => showToast(error.message || String(error)));
    });
  });
}

function paperSummary(paper) {
  return {
    id: paper.id,
    filename: paper.filename,
    title: paper.title,
    overview: paper.overview || "",
    provider_used: paper.provider_used || "unknown",
    warnings: paper.warnings || [],
    analysis_status: paper.analysis_status || "complete",
    analysis_error: paper.analysis_error || "",
    highlight_count: paper.highlight_count ?? paper.highlights?.length ?? 0,
    figure_count: paper.figure_count ?? paper.figures?.length ?? 0,
    figure_analysis_status: paper.figure_analysis_status || "idle",
    citation_count: paper.citation_count ?? paper.citations?.length ?? 0,
  };
}

function upsertPaperSummary(paper) {
  const summary = paperSummary(paper);
  const existingIndex = state.papers.findIndex((item) => item.id === paper.id);
  if (existingIndex === -1) {
    state.papers = [summary, ...state.papers];
    return;
  }

  state.papers = state.papers.map((item, index) => (index === existingIndex ? summary : item));
}

function prependPaperSummaries(papers) {
  const summaries = [];
  const seen = new Set();
  for (const paper of papers) {
    if (!paper?.id || seen.has(paper.id)) {
      continue;
    }
    seen.add(paper.id);
    summaries.push(paperSummary(paper));
  }

  state.papers = [
    ...summaries,
    ...state.papers.filter((paper) => !seen.has(paper.id)),
  ];
}

async function selectPaper(paperId) {
  resetPaperViewport();
  showReaderLoading();
  const paper = await requestJson(`/api/papers/${paperId}`);
  setSelectedPaper(paper);
  await renderPdf(paper);
  pollPaperAnalysis(paper.id);
}

async function removePaper(paperId) {
  if (!paperId) {
    return;
  }

  await requestJson(`/api/papers/${paperId}`, { method: "DELETE" });
  state.papers = state.papers.filter((paper) => paper.id !== paperId);
  if (state.selectedPaper?.id === paperId) {
    clearSelectedPaper();
    if (state.papers.length) {
      await selectPaper(state.papers[0].id);
    } else {
      renderPaperList();
    }
  } else {
    renderPaperList();
  }
  showToast("Paper removed");
}

function setSelectedPaper(paper, { preserveWorkspace = false } = {}) {
  state.selectedPaper = paper;
  if (preserveWorkspace) {
    syncSelectedFigures();
  } else {
    state.chatMessages = [];
    state.pendingCitationContext = null;
    state.selectedFigures = [];
    state.activeFigure = null;
    state.activeHighlightIndex = null;
    state.activeHighlightFacet = "all";
  }
  upsertPaperSummary(paper);
  syncPaperActions();
  renderPaperList();
  renderPaperDetails(paper);
  renderChat();
  renderChatFigureFocus();
}

function clearSelectedPaper() {
  state.renderToken += 1;
  state.pdfLoadingTask?.destroy?.();
  state.pdfLoadingTask = null;
  state.pdfDocument?.destroy?.();
  state.pdfDocument = null;
  state.selectedPaper = null;
  state.chatMessages = [];
  state.pageTexts = new Map();
  state.pageWords = new Map();
  state.textSelectionDrag = null;
  state.pendingCitationContext = null;
  state.selectedFigures = [];
  state.activeFigure = null;
  state.activeHighlightFacet = "all";
  hideSelectionPopover();
  hideCitationPopover();
  hideFigurePopover();
  hideHighlightPopover();
  clearActiveHighlight();
  if (state.analysisPoll) {
    window.clearTimeout(state.analysisPoll);
    state.analysisPoll = null;
  }
  if (state.figurePoll) {
    window.clearTimeout(state.figurePoll);
    state.figurePoll = null;
  }
  state.figureAnalysisRunning = false;
  syncPaperActions();
  els.readerEmpty?.classList.remove("hidden");
  els.pdfViewer?.classList.add("hidden");
  setHtml(els.pdfViewer, "");
  if (els.paperProvider) {
    els.paperProvider.textContent = "Idle";
  }
  if (els.paperTitle) {
    els.paperTitle.textContent = "PaperSprint";
  }
  if (els.paperOverview) {
    els.paperOverview.textContent = "";
  }
  renderBackgroundNotes([]);
  syncPdfZoomControls();
  if (els.highlightCount) {
    els.highlightCount.textContent = "0";
  }
  setHtml(els.highlightList, `<div class="muted-box">No highlights</div>`);
  renderHighlightFilters([]);
  renderListPanel(els.takeawaysTab, []);
  renderChat();
  renderChatFigureFocus();
}

function syncPaperActions() {
  const isAnalyzing = state.selectedPaper?.analysis_status === "analyzing" || state.selectedPaper?.reanalysis_status === "analyzing";
  const isFigureAnalyzing = state.figureAnalysisRunning || state.selectedPaper?.figure_analysis_status === "running";
  const isBusy = isAnalyzing || isFigureAnalyzing;
  const buttonLabel = isFigureAnalyzing
    ? "Analyzing figures"
    : isAnalyzing
      ? "Analyzing text"
      : state.selectedPaper?.analysis_status === "complete" ? "Reanalyze" : "Analyze";
  syncPdfZoomControls();
  setLoadingButton(els.analyzeButton, Boolean(isBusy), buttonLabel);
  if (els.analyzeButton) {
    els.analyzeButton.disabled = Boolean(isBusy);
  }
}

function showReaderLoading() {
  els.readerEmpty?.classList.add("hidden");
  els.pdfViewer?.classList.remove("hidden");
  setHtml(els.pdfViewer, `<div class="loading">Loading paper</div>`);
}

function renderPaperDetails(paper) {
  state.summaryEvidenceTargets = [];
  const chatAvailable = Boolean(paper.chat_available);
  const reanalysisFailed = paper.reanalysis_status === "error";
  if (els.chatStatus) {
    els.chatStatus.textContent = reanalysisFailed
      ? `Reanalysis failed: ${paper.reanalysis_error || "Unknown provider error."} The current analysis remains available.`
      : chatAvailable
        ? ""
        : paper.analysis_status === "analyzing"
        ? paper.analysis_stage || "Analysis in progress."
        : paper.analysis_status === "error"
          ? `Analysis failed: ${paper.analysis_error || "Unknown provider error."} Reanalyze to start chatting.`
          : "Analyze this paper to start chatting.";
    els.chatStatus.classList.toggle("hidden", chatAvailable && !reanalysisFailed);
  }
  if (els.chatInput) els.chatInput.disabled = !chatAvailable;
  els.chatForm?.querySelectorAll("button").forEach((button) => { button.disabled = !chatAvailable; });
  const highlights = paper.highlights || [];
  if (
    state.activeHighlightFacet !== "all"
    && !highlights.some((highlight) => highlight.label === state.activeHighlightFacet)
  ) {
    state.activeHighlightFacet = "all";
  }
  const visibleHighlights = filteredHighlights(highlights);
  if (els.highlightFilterStatus) {
    const filtered = state.activeHighlightFacet !== "all";
    els.highlightFilterStatus.classList.toggle("hidden", !filtered);
    els.highlightFilterStatus.innerHTML = filtered
      ? `Showing a facet subset; this view is not a standalone narrative. <button data-show-full-narrative type="button">Show full narrative</button>`
      : "";
    els.highlightFilterStatus.querySelector?.("[data-show-full-narrative]")?.addEventListener("click", async () => {
      state.activeHighlightFacet = "all";
      renderPaperDetails(paper);
      await refreshReaderAnnotations(paper);
    });
  }
  if (els.highlightCount) {
    els.highlightCount.textContent = state.activeHighlightFacet === "all"
      ? String(highlights.length)
      : `${visibleHighlights.length}/${highlights.length}`;
  }
  renderHighlightFilters(highlights);
  renderHighlights(visibleHighlights);
  syncHighlightNavigation();
}

function filteredHighlights(highlights) {
  return (highlights || [])
    .map((highlight, index) => ({ ...highlight, highlightIndex: index }))
    .filter((highlight) => state.activeHighlightFacet === "all" || highlightLabelId(highlight.label) === state.activeHighlightFacet);
}

function highlightCategoryOptions(highlights) {
  const options = HIGHLIGHT_FACETS
    .filter((facet) => facet.id !== "all")
    .map((facet) => ({
      id: facet.id,
      label: facet.label,
      color: DEFAULT_HIGHLIGHT_COLORS[facet.id] || "",
    }));
  const seen = new Set(options.map((option) => option.id));
  for (const highlight of highlights || []) {
    const id = highlightLabelId(highlight.label);
    if (!id || seen.has(id)) {
      continue;
    }
    seen.add(id);
    options.push({
      id,
      label: highlightLabelText(highlight.label),
      color: highlightColor(highlight) || DEFAULT_HIGHLIGHT_COLORS.important,
    });
  }
  return options;
}

function renderHighlightFilters(highlights) {
  if (!els.highlightFilters) {
    return;
  }

  const counts = new Map();
  for (const highlight of highlights || []) {
    const id = highlightLabelId(highlight.label);
    counts.set(id, (counts.get(id) || 0) + 1);
  }
  const facets = [
    HIGHLIGHT_FACETS[0],
    ...highlightCategoryOptions(highlights).filter((facet) => counts.has(facet.id)),
  ];

  setHtml(
    els.highlightFilters,
    facets.map((facet) => {
      const count = facet.id === "all" ? (highlights || []).length : counts.get(facet.id) || 0;
      const active = state.activeHighlightFacet === facet.id ? "active" : "";
      const hasColor = safeHexColor(facet.color) ? "has-color" : "";
      return `
        <button class="facet-chip ${active} ${hasColor}" data-highlight-facet="${escapeHtml(facet.id)}" type="button"${facetChipStyle(facet)}>
          ${escapeHtml(facet.label)}
          <span>${count}</span>
        </button>
      `;
    }).join(""),
  );

  els.highlightFilters.querySelectorAll("[data-highlight-facet]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.activeHighlightFacet = button.dataset.highlightFacet || "all";
      if (!state.selectedPaper) {
        return;
      }
      renderPaperDetails(state.selectedPaper);
      await refreshReaderAnnotations(state.selectedPaper);
    });
  });
}

function summaryItemText(item) {
  if (item && typeof item === "object") {
    return String(item.text || item.takeaway || item.summary || "").trim();
  }
  return String(item || "").trim();
}

function summaryItemEvidenceHint(item) {
  if (!item || typeof item !== "object") {
    return "";
  }
  return String(item.supporting_excerpt || item.evidence_hint || item.evidence || item.evidence_snippet || "").trim();
}

function summaryItemHighlightIds(item) {
  if (!item || typeof item !== "object") {
    return [];
  }
  const rawIds = item.highlight_ids || item.highlightIds || [];
  if (typeof rawIds === "string") {
    return rawIds.split(/[\s,;]+/).map((value) => value.trim()).filter(Boolean);
  }
  if (!Array.isArray(rawIds)) {
    return [];
  }
  return rawIds.map((value) => String(value || "").trim()).filter(Boolean);
}

function normalizedEvidenceValue(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/fig(?:ure)?\.?/g, "figure")
    .replace(/tables?/g, "table")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function evidenceTokens(value, limit = 28) {
  return normalizedEvidenceValue(value).split(" ").filter(Boolean).slice(0, limit);
}

function wordEvidenceTokens(word) {
  return normalizedEvidenceValue(word?.text || "").split(" ").filter(Boolean);
}

function evidenceWordEntries(words) {
  return (words || []).map((word, index) => ({ word, index }));
}

function evidenceTokenEntries(wordEntries) {
  return wordEntries.flatMap((entry) =>
    wordEvidenceTokens(entry.word).map((token) => ({ ...entry, token })),
  );
}

function uniqueWordsFromEntries(entries) {
  const seen = new Set();
  const result = [];
  for (const entry of entries) {
    if (seen.has(entry.index)) {
      continue;
    }
    seen.add(entry.index);
    result.push(entry.word);
  }
  return result;
}

function matchedTokenSpan(tokenEntries, queryTokens) {
  if (!tokenEntries.length || !queryTokens.length) {
    return null;
  }

  for (let start = 0; start < tokenEntries.length; start += 1) {
    let cursor = start;
    let matched = true;
    for (const queryToken of queryTokens) {
      let combined = "";
      while (cursor < tokenEntries.length && combined.length < queryToken.length) {
        const next = combined + tokenEntries[cursor].token;
        if (!queryToken.startsWith(next)) {
          matched = false;
          break;
        }
        combined = next;
        cursor += 1;
        if (combined === queryToken) {
          break;
        }
      }
      if (!matched || combined !== queryToken) {
        matched = false;
        break;
      }
    }
    if (matched) {
      return { start, end: cursor };
    }
  }
  return null;
}

function medianNumber(values, fallback = 0) {
  if (!values.length) {
    return fallback;
  }
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.floor(sorted.length / 2)];
}

function wordEntryCenterY(entry) {
  return (entry.word.cssRect[1] + entry.word.cssRect[3]) / 2;
}

function lineFromWordEntries(entries) {
  const rects = entries.map((entry) => entry.word.cssRect);
  return {
    centerY: rects.reduce((sum, rect) => sum + (rect[1] + rect[3]) / 2, 0) / rects.length,
    top: Math.min(...rects.map((rect) => rect[1])),
    bottom: Math.max(...rects.map((rect) => rect[3])),
    left: Math.min(...rects.map((rect) => rect[0])),
    right: Math.max(...rects.map((rect) => rect[2])),
    entries: [...entries].sort((left, right) => left.index - right.index),
  };
}

function splitWordLineEntries(entries) {
  const sortedEntries = [...entries].sort((left, right) => left.word.cssRect[0] - right.word.cssRect[0]);
  if (sortedEntries.length <= 1) {
    return [sortedEntries];
  }

  const heights = sortedEntries.map((entry) => Math.max(1, entry.word.cssRect[3] - entry.word.cssRect[1]));
  const medianHeight = medianNumber(heights, 10);
  const widths = sortedEntries.map((entry) => Math.max(1, entry.word.cssRect[2] - entry.word.cssRect[0]));
  const medianWidth = medianNumber(widths, 12);
  const gaps = sortedEntries
    .slice(1)
    .map((entry, index) => entry.word.cssRect[0] - sortedEntries[index].word.cssRect[2])
    .filter((gap) => gap > 0);
  const medianGap = medianNumber(gaps, 4);
  const columnGapThreshold = gaps.length >= 3
    ? Math.max(12, medianHeight * 1.2, medianGap * 3)
    : Math.max(12, medianHeight * 1.2, medianWidth * 1.8);
  const groups = [];
  let current = [sortedEntries[0]];

  for (const entry of sortedEntries.slice(1)) {
    const previousEntry = current[current.length - 1];
    const gap = entry.word.cssRect[0] - previousEntry.word.cssRect[2];
    if (gap > columnGapThreshold) {
      groups.push(current);
      current = [entry];
    } else {
      current.push(entry);
    }
  }
  groups.push(current);
  return groups;
}

function sameColumnLine(left, right) {
  const overlap = Math.min(left.right, right.right) - Math.max(left.left, right.left);
  const minWidth = Math.min(Math.max(1, left.right - left.left), Math.max(1, right.right - right.left));
  return overlap >= Math.max(8, minWidth * 0.2);
}

function wordLineGroups(wordEntries) {
  const yLines = [];
  const sortedEntries = [...wordEntries].sort((left, right) => {
    const leftCenter = wordEntryCenterY(left);
    const rightCenter = wordEntryCenterY(right);
    return leftCenter - rightCenter || left.word.cssRect[0] - right.word.cssRect[0];
  });

  for (const entry of sortedEntries) {
    const centerY = wordEntryCenterY(entry);
    const line = yLines.find((item) => Math.abs(item.centerY - centerY) <= 5);
    if (line) {
      line.entries.push(entry);
      line.centerY = (line.centerY * (line.entries.length - 1) + centerY) / line.entries.length;
    } else {
      yLines.push({
        centerY,
        entries: [entry],
      });
    }
  }

  return yLines
    .flatMap((line) => splitWordLineEntries(line.entries).map(lineFromWordEntries))
    .sort((left, right) => left.top - right.top || left.left - right.left);
}

function sentenceBoundaryAfter(wordEntries, index) {
  const text = String(wordEntries[index]?.word?.text || "").trim();
  if (!/[.!?][)"'\]]*$/.test(text)) {
    return false;
  }

  const token = normalizedEvidenceValue(text);
  if (["al", "dr", "eg", "fig", "figure", "ie", "mr", "mrs", "ms", "ref", "refs", "vs"].includes(token)) {
    return false;
  }

  const nextText = String(wordEntries[index + 1]?.word?.text || "").trim();
  return !nextText || /^[(\[]?[A-Z0-9]/.test(nextText);
}

function sentenceWordsForMatch(wordEntries, startIndex, endIndex) {
  return sentenceEntriesForMatch(wordEntries, startIndex, endIndex).map((entry) => entry.word);
}

function sentenceEntriesForMatch(wordEntries, startIndex, endIndex, options = {}) {
  const maxSentenceWords = options.maxWords || 90;
  const maxExpansionWords = options.maxExpansionWords ?? Number.POSITIVE_INFINITY;
  let first = startIndex;
  let last = endIndex;

  while (
    first > 0
    && startIndex - first < maxExpansionWords
    && !sentenceBoundaryAfter(wordEntries, first - 1)
  ) {
    first -= 1;
  }
  while (
    last < wordEntries.length
    && last - endIndex < maxExpansionWords
    && !sentenceBoundaryAfter(wordEntries, last - 1)
  ) {
    last += 1;
  }

  if (last - first > maxSentenceWords) {
    return wordEntries.slice(startIndex, endIndex);
  }
  return wordEntries.slice(first, last);
}

function sentenceBlocksForWordEntries(wordEntries) {
  const maxSentenceWords = 90;
  const blocks = [];
  let current = [];

  wordEntries.forEach((entry, index) => {
    current.push(entry);
    if (sentenceBoundaryAfter(wordEntries, index) || current.length >= maxSentenceWords) {
      blocks.push(current);
      current = [];
    }
  });
  if (current.length) {
    blocks.push(current);
  }
  return blocks;
}

function paragraphWordsForMatch(wordEntries, startIndex, endIndex) {
  const matchedIndexes = new Set(wordEntries.slice(startIndex, endIndex).map((entry) => entry.index));
  const lines = wordLineGroups(wordEntries);
  const matchedLineIndexes = lines
    .map((line, index) => (line.entries.some((entry) => matchedIndexes.has(entry.index)) ? index : null))
    .filter((index) => index !== null);
  if (!matchedLineIndexes.length) {
    return wordEntries.slice(startIndex, endIndex).map((entry) => entry.word);
  }

  const lineHeights = lines.map((line) => Math.max(1, line.bottom - line.top)).sort((left, right) => left - right);
  const medianLineHeight = lineHeights[Math.floor(lineHeights.length / 2)] || 10;
  const maxParagraphGap = Math.max(5, medianLineHeight * 0.75);
  const maxParagraphLines = 8;
  const anchorLineIndex = matchedLineIndexes.reduce((bestIndex, lineIndex) => {
    const bestCount = lines[bestIndex].entries.filter((entry) => matchedIndexes.has(entry.index)).length;
    const lineCount = lines[lineIndex].entries.filter((entry) => matchedIndexes.has(entry.index)).length;
    return lineCount > bestCount ? lineIndex : bestIndex;
  }, matchedLineIndexes[0]);
  const anchorLine = lines[anchorLineIndex];
  const columnLines = lines
    .map((line, index) => ({ line, index }))
    .filter((item) => item.index === anchorLineIndex || sameColumnLine(item.line, anchorLine));
  const matchedColumnLineIndexes = columnLines
    .map((item, index) => (matchedLineIndexes.includes(item.index) ? index : null))
    .filter((index) => index !== null);
  let firstLine = Math.min(...matchedColumnLineIndexes);
  let lastLine = Math.max(...matchedColumnLineIndexes);

  while (
    firstLine > 0
    && lastLine - firstLine + 1 < maxParagraphLines
    && columnLines[firstLine].line.top - columnLines[firstLine - 1].line.bottom <= maxParagraphGap
    && sameColumnLine(columnLines[firstLine].line, columnLines[firstLine - 1].line)
  ) {
    firstLine -= 1;
  }
  while (
    lastLine < columnLines.length - 1
    && lastLine - firstLine + 1 < maxParagraphLines
    && columnLines[lastLine + 1].line.top - columnLines[lastLine].line.bottom <= maxParagraphGap
    && sameColumnLine(columnLines[lastLine].line, columnLines[lastLine + 1].line)
  ) {
    lastLine += 1;
  }

  const paragraphEntries = columnLines
    .slice(firstLine, lastLine + 1)
    .flatMap((item) => item.line.entries)
    .sort((left, right) => left.index - right.index);
  const paragraphIndexes = new Set(paragraphEntries.map((entry) => entry.index));
  const columnEntries = columnLines
    .flatMap((item) => item.line.entries)
    .sort((left, right) => left.index - right.index);
  const paragraphPositions = columnEntries
    .map((entry, index) => (paragraphIndexes.has(entry.index) ? index : null))
    .filter((index) => index !== null);
  if (!paragraphPositions.length) {
    return paragraphEntries.map((entry) => entry.word);
  }

  return sentenceEntriesForMatch(
    columnEntries,
    Math.min(...paragraphPositions),
    Math.max(...paragraphPositions) + 1,
    { maxExpansionWords: 32, maxWords: 160 },
  ).map((entry) => entry.word);
}

function paragraphBlocksForWordEntries(wordEntries) {
  const lines = wordLineGroups(wordEntries);
  if (!lines.length) {
    return [];
  }

  const lineHeights = lines.map((line) => Math.max(1, line.bottom - line.top)).sort((left, right) => left - right);
  const medianLineHeight = lineHeights[Math.floor(lineHeights.length / 2)] || 10;
  const maxParagraphGap = Math.max(5, medianLineHeight * 0.75);
  const blocks = [];

  for (const line of lines) {
    let matchingBlock = null;
    for (let index = blocks.length - 1; index >= 0; index -= 1) {
      const previousLine = blocks[index][blocks[index].length - 1];
      if (!sameColumnLine(previousLine, line)) {
        continue;
      }
      const verticalGap = line.top - previousLine.bottom;
      if (verticalGap <= maxParagraphGap) {
        matchingBlock = blocks[index];
      }
      break;
    }

    if (matchingBlock) {
      matchingBlock.push(line);
    } else {
      blocks.push([line]);
    }
  }

  return blocks.map((block) => block.flatMap((line) => line.entries).sort((left, right) => left.index - right.index));
}

const SUMMARY_STOP_WORDS = new Set([
  "about",
  "after",
  "also",
  "because",
  "before",
  "being",
  "between",
  "could",
  "from",
  "into",
  "paper",
  "show",
  "shows",
  "that",
  "their",
  "there",
  "these",
  "this",
  "through",
  "using",
  "with",
  "would",
]);

function summaryTokens(value) {
  return new Set(
    normalizedEvidenceValue(value)
      .match(/[a-z][a-z0-9]{2,}/g)
      ?.filter((token) => !SUMMARY_STOP_WORDS.has(token)) || [],
  );
}

function fuzzyBlockContextWords(block, queryTokens) {
  const lines = wordLineGroups(block);
  if (lines.length <= 10) {
    return block.map((entry) => entry.word);
  }

  const queryTokenSet = new Set(queryTokens);
  const scoredLines = lines.map((line, index) => {
    const sharedTokens = new Set(
      line.entries
        .map((entry) => entry.token)
        .filter((token) => queryTokenSet.has(token)),
    );
    return { index, score: sharedTokens.size };
  });
  const bestLine = scoredLines.reduce(
    (best, item) => (item.score > best.score ? item : best),
    scoredLines[0],
  );
  const maxContextLines = 8;
  let firstLine = Math.max(0, bestLine.index - 2);
  let lastLine = Math.min(lines.length - 1, bestLine.index + maxContextLines - 3);

  while (lastLine - firstLine + 1 < maxContextLines && firstLine > 0) {
    firstLine -= 1;
  }
  while (lastLine - firstLine + 1 < maxContextLines && lastLine < lines.length - 1) {
    lastLine += 1;
  }

  const contextEntries = lines
    .slice(firstLine, lastLine + 1)
    .flatMap((line) => line.entries)
    .sort((left, right) => left.index - right.index);
  const contextIndexes = new Set(contextEntries.map((entry) => entry.index));
  const blockEntries = lines
    .flatMap((line) => line.entries)
    .sort((left, right) => left.index - right.index);
  const contextPositions = blockEntries
    .map((entry, index) => (contextIndexes.has(entry.index) ? index : null))
    .filter((index) => index !== null);

  if (!contextPositions.length) {
    return contextEntries.map((entry) => entry.word);
  }
  return sentenceEntriesForMatch(
    blockEntries,
    Math.min(...contextPositions),
    Math.max(...contextPositions) + 1,
    { maxExpansionWords: 24, maxWords: 140 },
  ).map((entry) => entry.word);
}

function summaryEvidenceScore(item, highlight) {
  const evidenceHint = summaryItemEvidenceHint(item);
  const text = summaryItemText(item);
  const highlightText = [highlight.snippet, highlight.comment, highlight.reason].filter(Boolean).join(" ");
  if (evidenceHint && highlight.snippet?.toLowerCase().includes(evidenceHint.toLowerCase().slice(0, 80))) {
    return 1;
  }

  const itemTokens = summaryTokens([evidenceHint, text].filter(Boolean).join(" "));
  const highlightTokens = summaryTokens(highlightText);
  if (!itemTokens.size || !highlightTokens.size) {
    return 0;
  }

  let shared = 0;
  for (const token of itemTokens) {
    if (highlightTokens.has(token)) {
      shared += 1;
    }
  }
  return shared / itemTokens.size;
}

function evidenceHighlightIndexForItem(item) {
  const highlights = state.selectedPaper?.highlights || [];
  let bestIndex = null;
  let bestScore = 0;
  highlights.forEach((highlight, index) => {
    if (!highlight.page_number || !highlight.rects?.length) {
      return;
    }
    const score = summaryEvidenceScore(item, highlight);
    if (score > bestScore) {
      bestScore = score;
      bestIndex = index;
    }
  });
  return bestScore >= 0.18 ? bestIndex : null;
}

function highlightIndexForId(highlightId) {
  const normalizedId = String(highlightId || "").trim();
  if (!normalizedId) {
    return null;
  }
  const index = (state.selectedPaper?.highlights || []).findIndex((highlight) => highlight.id === normalizedId);
  return index === -1 ? null : index;
}

function linkedHighlightIndexesForItem(item, options = {}) {
  const indexes = [];
  for (const highlightId of summaryItemHighlightIds(item)) {
    const index = highlightIndexForId(highlightId);
    if (index !== null && !indexes.includes(index)) {
      indexes.push(index);
    }
  }
  if (!indexes.length && options.includeFallback !== false) {
    const fallbackIndex = evidenceHighlightIndexForItem(item);
    if (fallbackIndex !== null) {
      indexes.push(fallbackIndex);
    }
  }
  return indexes;
}

function figureReferenceKeys(value) {
  const references = [];
  const pattern = /\b(?:fig(?:ure)?\.?|table)\s*([0-9]+[a-z]?)\b/gi;
  for (const match of String(value || "").matchAll(pattern)) {
    const prefix = match[0].toLowerCase().startsWith("t") ? "table" : "figure";
    references.push(`${prefix}${match[1].toLowerCase()}`);
  }
  return references;
}

function figureKey(figure) {
  return normalizedEvidenceValue([figure?.label, figure?.title].filter(Boolean).join(" ")).replace(/\s+/g, "");
}

function figureEvidenceTargetForItem(item) {
  const references = figureReferenceKeys([summaryItemText(item), summaryItemEvidenceHint(item)].join(" "));
  if (!references.length) {
    return null;
  }

  const figure = (state.selectedPaper?.figures || []).find((candidate) => {
    const key = figureKey(candidate);
    return references.some((reference) => key.includes(reference));
  });
  if (!figure?.id) {
    return null;
  }

  const kind = String(figure.type || figure.label || "").toLowerCase().includes("table") ? "Table" : "Figure";
  return { type: "figure", figureId: figure.id, label: kind };
}

function fuzzyParagraphEvidenceTarget(tokens, options = {}) {
  const queryTokens = tokens.filter((token) => !SUMMARY_STOP_WORDS.has(token));
  if (queryTokens.length < 4) {
    return null;
  }

  let bestTarget = null;
  let bestScore = 0;
  for (const [pageNumber, words] of currentPageWords().entries()) {
    const wordEntries = words
      .map((word, index) => ({ word, index, token: normalizedEvidenceValue(word.text) }))
      .filter((item) => item.token);
    for (const block of paragraphBlocksForWordEntries(wordEntries)) {
      const blockTokens = new Set(block.map((entry) => entry.token).filter((token) => !SUMMARY_STOP_WORDS.has(token)));
      let shared = 0;
      for (const token of queryTokens) {
        if (blockTokens.has(token)) {
          shared += 1;
        }
      }
      const score = shared / queryTokens.length;
      if (score > bestScore) {
        const contextWords = fuzzyBlockContextWords(block, queryTokens);
        bestScore = score;
        bestTarget = {
          type: "text",
          label: "Text",
          pageNumber,
          rects: mergeWordRects(contextWords, "pdfRect"),
          flash: Boolean(options.flash),
        };
      }
    }
  }

  return bestScore >= 0.32 ? bestTarget : null;
}

function fuzzySentenceEvidenceTarget(tokens, options = {}) {
  const queryTokens = tokens.filter((token) => !SUMMARY_STOP_WORDS.has(token));
  if (queryTokens.length < 4) {
    return null;
  }

  let bestTarget = null;
  let bestScore = 0;
  for (const [pageNumber, words] of currentPageWords().entries()) {
    const wordEntries = evidenceWordEntries(words);
    for (const block of sentenceBlocksForWordEntries(wordEntries)) {
      const blockTokens = new Set(
        block
          .flatMap((entry) => wordEvidenceTokens(entry.word))
          .filter((token) => !SUMMARY_STOP_WORDS.has(token)),
      );
      let shared = 0;
      for (const token of queryTokens) {
        if (blockTokens.has(token)) {
          shared += 1;
        }
      }
      const score = shared / queryTokens.length;
      if (score > bestScore) {
        bestScore = score;
        bestTarget = {
          type: "text",
          label: "Text",
          pageNumber,
          rects: mergeWordRects(block.map((entry) => entry.word), "pdfRect"),
          flash: Boolean(options.flash),
        };
      }
    }
  }

  return bestScore >= 0.38 ? bestTarget : null;
}

function textEvidenceTargetForValue(value, options = {}) {
  const tokens = evidenceTokens(value, options.maxTokens || 80);
  if (tokens.length < 4) {
    return null;
  }

  for (const [pageNumber, words] of currentPageWords().entries()) {
    const wordEntries = evidenceWordEntries(words);
    const tokenEntries = evidenceTokenEntries(wordEntries);
    const span = matchedTokenSpan(tokenEntries, tokens);
    if (span) {
      const matchedTokenEntries = tokenEntries.slice(span.start, span.end);
      const matchedWordIndexes = matchedTokenEntries.map((entry) => entry.index);
      const firstWordIndex = Math.min(...matchedWordIndexes);
      const lastWordIndex = Math.max(...matchedWordIndexes) + 1;
      const matchedEntries = options.expandToParagraph
        ? paragraphWordsForMatch(wordEntries, firstWordIndex, lastWordIndex)
        : options.expandToSentence
          ? sentenceWordsForMatch(wordEntries, firstWordIndex, lastWordIndex)
          : uniqueWordsFromEntries(matchedTokenEntries);
      return {
        type: "text",
        label: "Text",
        pageNumber,
        rects: mergeWordRects(matchedEntries, "pdfRect"),
        flash: Boolean(options.flash),
      };
    }
  }

  if (options.expandToSentence || options.expandToParagraph) {
    const fuzzyTarget = options.expandToSentence
      ? fuzzySentenceEvidenceTarget(tokens, options)
      : fuzzyParagraphEvidenceTarget(tokens, options);
    if (fuzzyTarget) {
      return fuzzyTarget;
    }
  }

  if (options.allowPageFallback !== false) {
    const query = normalizedEvidenceValue(value).slice(0, 120);
    if (query.length < 24) {
      return null;
    }
    for (const [pageNumber, pageText] of state.pageTexts.entries()) {
      if (normalizedEvidenceValue(pageText).includes(query)) {
        return { type: "page", label: "Text", pageNumber };
      }
    }
  }
  return null;
}

function textEvidenceTargetForItem(item, options = {}) {
  const evidenceHint = summaryItemEvidenceHint(item);
  if (options.exactEvidence) {
    const exactOptions = {
      ...options,
      allowPageFallback: false,
      expandToParagraph: false,
      expandToSentence: false,
    };
    const evidenceTarget = textEvidenceTargetForValue(evidenceHint, exactOptions);
    if (evidenceTarget) {
      return evidenceTarget;
    }

    for (const highlightIndex of linkedHighlightIndexesForItem(item)) {
      const highlight = (state.selectedPaper?.highlights || [])[highlightIndex];
      const highlightTarget = textEvidenceTargetForValue(highlight?.snippet || "", {
        ...exactOptions,
        maxTokens: 140,
      });
      if (highlightTarget) {
        return highlightTarget;
      }
    }

    return textEvidenceTargetForValue(summaryItemText(item), { ...exactOptions, maxTokens: 80 });
  }

  return textEvidenceTargetForValue(evidenceHint, options)
    || textEvidenceTargetForValue(summaryItemText(item), { ...options, maxTokens: 36 });
}

function summaryEvidenceTargetForItem(item, options = {}) {
  const figureTarget = options.allowFigure === false ? null : figureEvidenceTargetForItem(item);
  if (figureTarget) {
    return figureTarget;
  }

  const textTarget = textEvidenceTargetForItem(item, options);
  if (textTarget) {
    return textTarget;
  }

  const highlightIndex = linkedHighlightIndexesForItem(item)[0] ?? null;
  if (highlightIndex === null) {
    return null;
  }

  const highlight = (state.selectedPaper?.highlights || [])[highlightIndex];
  const highlightOptions = options.exactEvidence
    ? { ...options, allowPageFallback: false, expandToParagraph: false, expandToSentence: false, maxTokens: 140 }
    : { ...options, expandToParagraph: true };
  return textEvidenceTargetForValue(highlight?.snippet || "", highlightOptions)
    || { type: "highlight", label: "Text", highlightIndex, flash: Boolean(options.flash) };
}

function renderListPanel(target, items, options = {}) {
  const values = (items || []).filter((item) => summaryItemText(item));
  const evidenceTargets = [];
  setHtml(
    target,
      values.length
      ? `<ul>${values.map((item, index) => {
        const text = summaryItemText(item);
        const target = options.linkEvidence ? summaryEvidenceTargetForItem(item, options) : null;
        const targetIndex = target ? state.summaryEvidenceTargets.length + evidenceTargets.length : null;
        if (target) {
          evidenceTargets.push(target);
        }
        if (options.rowEvidence) {
          const localTargetIndex = target ? evidenceTargets.length - 1 : null;
          const evidenceHint = summaryItemEvidenceHint(item);
          const evidenceHtml = options.showEvidence && evidenceHint
            ? `<blockquote class="takeaway-evidence">${escapeHtml(evidenceHint)}</blockquote>`
            : "";
          const linkedHighlights = options.showHighlightLinks
            ? linkedHighlightIndexesForItem(item).map((highlightIndex) => {
              const highlight = (state.selectedPaper?.highlights || [])[highlightIndex];
              if (!highlight) {
                return "";
              }
              const labelId = highlightLabelId(highlight.label);
              return `<button class="summary-highlight-chip label label-${escapeHtml(labelId)}" data-summary-highlight-index="${highlightIndex}"${customHighlightStyle(highlight)} type="button">${escapeHtml(highlightLabelText(highlight.label))}</button>`;
            }).filter(Boolean).join("")
            : "";
          const highlightLinksHtml = linkedHighlights
            ? `<div class="takeaway-highlight-links">${linkedHighlights}</div>`
            : "";
          const attrs = target === null
            ? ""
            : ` class="summary-evidence-row" data-summary-evidence-index="${targetIndex}" data-summary-local-evidence-index="${localTargetIndex}" data-summary-row-index="${index}" data-summary-item-text="${escapeHtml(text)}" data-summary-item-evidence="${escapeHtml(evidenceHint)}" role="button" tabindex="0"`;
          return `<li${attrs}><span>${escapeHtml(text)}</span>${evidenceHtml}${highlightLinksHtml}</li>`;
        }
        const evidenceButton = target === null
          ? ""
          : `<button class="summary-proof-button" data-summary-evidence-index="${targetIndex}" type="button">${escapeHtml(target.label || "Proof")}</button>`;
        return `<li class="${evidenceButton ? "has-proof" : ""}"><span>${escapeHtml(text)}</span>${evidenceButton}</li>`;
      }).join("")}</ul>`
      : `<div class="muted-box">No items</div>`,
  );
  state.summaryEvidenceTargets.push(...evidenceTargets);
  target?.querySelectorAll("[data-summary-highlight-index]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      jumpToHighlight(Number(button.dataset.summaryHighlightIndex));
    });
  });
  target?.querySelectorAll("[data-summary-evidence-index]").forEach((button) => {
    const localIndex = button.dataset.summaryLocalEvidenceIndex;
    let localTarget = localIndex === undefined ? null : evidenceTargets[Number(localIndex)];
    const rowIndex = button.dataset.summaryRowIndex;
    const currentTarget = () => {
      if (specificEvidenceTarget(localTarget)) {
        return localTarget;
      }
      if (rowIndex !== undefined) {
        const rowItemIndex = Number(rowIndex);
        const currentItem = values[rowItemIndex]
          || (state.selectedPaper?.key_takeaways || [])[rowItemIndex]
          || {
            text: button.dataset.summaryItemText || button.textContent || "",
            evidence_hint: button.dataset.summaryItemEvidence || "",
        };
        const resolvedTarget = summaryEvidenceTargetForItem(currentItem, options);
        if (resolvedTarget) {
          localTarget = resolvedTarget;
          return resolvedTarget;
        }
      }
      return localTarget || state.summaryEvidenceTargets[Number(button.dataset.summaryEvidenceIndex)] || null;
    };
    const jump = () => {
      const target = currentTarget();
      if (target) {
        jumpToEvidenceTarget(target);
        return;
      }
      jumpToSummaryEvidence(Number(button.dataset.summaryEvidenceIndex));
    };
    button.addEventListener("click", jump);
    const preview = () => {
      previewEvidenceTarget(currentTarget());
    };
    button.addEventListener("pointerenter", preview);
    button.addEventListener("mouseenter", preview);
    button.addEventListener("mouseover", preview);
    button.addEventListener("pointerleave", clearSelectionPreview);
    button.addEventListener("mouseleave", clearSelectionPreview);
    button.addEventListener("mouseout", clearSelectionPreview);
    button.addEventListener("focus", preview);
    button.addEventListener("blur", clearSelectionPreview);
    button.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }
      event.preventDefault();
      jump();
    });
  });
}

function specificEvidenceTarget(target) {
  if (!target) {
    return false;
  }
  if (target.type === "highlight") {
    return target.highlightIndex !== null && target.highlightIndex !== undefined;
  }
  if (target.type === "figure") {
    return Boolean(target.figureId);
  }
  return target.type === "text" && Boolean(target.pageNumber) && Boolean(target.rects?.length);
}

function previewEvidenceTarget(target) {
  if (!target) {
    return;
  }

  if (target.type === "highlight") {
    const highlight = (state.selectedPaper?.highlights || [])[target.highlightIndex];
    if (!highlight?.page_number || !highlight.rects?.length) {
      return;
    }
    showSelectionPreview({
      pageNumber: highlight.page_number,
      rects: highlight.rects,
    }, { className: "summary-hover-rect" });
    return;
  }

  if (target.type !== "text" || !target.pageNumber || !target.rects?.length) {
    return;
  }

  showSelectionPreview({
    pageNumber: target.pageNumber,
    rects: target.rects,
  }, { className: "summary-hover-rect" });
}

function renderBackgroundNotes(notes) {
  const items = notes || [];
  els.backgroundSection?.classList.toggle("hidden", !items.length);
  if (els.backgroundNotes) {
    renderListPanel(els.backgroundNotes, items);
  }
}

function renderHighlights(highlights) {
  if (!highlights.length) {
    setHtml(els.highlightList, `<div class="muted-box">No highlights</div>`);
    return;
  }

  let currentSection = null;
  let manualHeadingShown = false;
  const html = [];
  highlights.forEach((highlight, index) => {
    if (highlight.source === "manual" && !manualHeadingShown) {
      html.push(`<div class="narrative-heading manual-heading"><strong>Manual highlights</strong><span>Personal evidence outside the standalone narrative.</span></div>`);
      manualHeadingShown = true;
    } else if (highlight.source !== "manual" && highlight.section_index !== currentSection) {
      currentSection = highlight.section_index;
      const heading = state.selectedPaper?.narrative_sections?.[currentSection]?.heading || "Narrative";
      html.push(`<h3 class="narrative-heading">${escapeHtml(heading)}</h3>`);
    }
    const sourceStatus = highlight.navigation_available ? "" : `<small>Source unavailable</small>`;
    const highlightIndex = highlight.highlightIndex ?? index;
    const labelId = highlightLabelId(highlight.label);
    const comment = highlight.comment
      ? `<p class="highlight-comment">${escapeHtml(highlight.comment)}</p>`
      : "";
    html.push(`
      <button class="highlight-card" data-highlight-index="${highlightIndex}" data-highlight-id="${escapeHtml(highlight.id || "")}" type="button">
        <span class="label label-${escapeHtml(labelId)}"${customHighlightStyle(highlight)}>${escapeHtml(highlightLabelText(highlight.label))}</span>
        <strong>${escapeHtml(highlight.text || highlight.snippet || "")}</strong>
        ${sourceStatus}
      </button>
    `);
  });
  setHtml(els.highlightList, html.join(""));

  els.highlightList?.querySelectorAll("[data-highlight-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const highlightIndex = Number(button.dataset.highlightIndex);
      jumpToHighlight(highlightIndex);
    });
  });
}

function normalizeCitationReference(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function citationChatText(citation) {
  const rawReferences = Array.isArray(citation.raw_references)
    ? citation.raw_references.map(normalizeCitationReference).filter(Boolean)
    : [normalizeCitationReference(citation.raw_reference)].filter(Boolean);
  if (rawReferences.length) {
    return rawReferences.join("\n");
  }

  const parts = [
    citation.authors,
    citation.title,
    citation.year,
  ]
    .map(normalizeCitationReference)
    .filter(Boolean);
  if (parts.length) {
    return parts.join(". ");
  }

  const context = citation.contexts?.[0]?.sentence || "";
  return [citation.label, context]
    .map((value) => String(value || "").replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join(" ");
}

function addCitationToChat(citation) {
  if (!citation || !els.chatInput) {
    return;
  }

  state.pendingCitationContext = citation;
  const citationText = citationChatText(citation);
  if (citationText && !els.chatInput.value.includes(citationText)) {
    els.chatInput.value = [els.chatInput.value.trim(), citationText].filter(Boolean).join("\n");
  }
  resizeChatInput();
  els.chatInput.focus();
  showToast("Citation added to chat");
}

function isFigureSelected(figureId) {
  return state.selectedFigures.some((figure) => figure.id === figureId);
}

function syncSelectedFigures() {
  const figures = state.selectedPaper?.figures || [];
  state.selectedFigures = state.selectedFigures
    .map((figure) => figures.find((item) => item.id === figure.id))
    .filter(Boolean);
}

function selectedFigureContext() {
  return state.selectedFigures.map((figure) => ({
    id: figure.id,
    page_number: figure.page_number,
    type: figure.type,
    label: figure.label,
    title: figure.title,
    caption: figure.caption,
    explanation: figure.explanation,
    why_it_matters: figure.why_it_matters,
    uncertainty: figure.uncertainty,
  }));
}

function renderChatFigureFocus() {
  if (!els.chatFigureFocus) {
    return;
  }
  if (!state.selectedFigures.length) {
    els.chatFigureFocus.classList.add("hidden");
    setHtml(els.chatFigureFocus, "");
    return;
  }

  els.chatFigureFocus.classList.remove("hidden");
  setHtml(
    els.chatFigureFocus,
    state.selectedFigures
      .map((figure) => `
        <span class="figure-focus-chip">
          <img src="${escapeHtml(figure.image_url || "")}" alt="" />
          <span>${escapeHtml(figureTitle(figure))}</span>
          <button data-remove-chat-figure="${escapeHtml(figure.id)}" type="button" aria-label="Remove figure">×</button>
        </span>
      `)
      .join(""),
  );
  els.chatFigureFocus.querySelectorAll("[data-remove-chat-figure]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedFigures = state.selectedFigures.filter((figure) => figure.id !== button.dataset.removeChatFigure);
      renderChatFigureFocus();
    });
  });
}

function addFigureToChat(figure) {
  if (!figure?.id || isFigureSelected(figure.id)) {
    return;
  }
  state.selectedFigures.push(figure);
  renderChatFigureFocus();
  els.chatInput?.focus();
  showToast("Figure added to chat");
}

function citationsByPage(citations) {
  const map = new Map();
  for (const [citationIndex, citation] of (citations || []).entries()) {
    for (const context of citation.contexts || []) {
      if (!context.page_number || !context.rects?.length) {
        continue;
      }
      const pageCitations = map.get(context.page_number) || [];
      pageCitations.push({ citation, citationIndex, context });
      map.set(context.page_number, pageCitations);
    }
  }
  return map;
}

function citationRectKey(rect) {
  return (rect || []).map((value) => Number(value).toFixed(2)).join(",");
}

function citationGroupLabel(item) {
  return normalizeCitationReference(item.context?.marker || item.citation?.label || "Citation");
}

function groupedCitationRects(citations) {
  const groups = new Map();
  for (const item of citations) {
    for (const rect of item.context.rects || []) {
      const label = citationGroupLabel(item);
      const key = `${item.context.page_number || ""}|${label}|${citationRectKey(rect)}`;
      if (!groups.has(key)) {
        groups.set(key, { label, rect, items: [] });
      }
      groups.get(key).items.push(item);
    }
  }
  return Array.from(groups.values());
}

function uniqueValues(values) {
  const seen = new Set();
  const result = [];
  for (const value of values) {
    const normalized = normalizeCitationReference(value);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function uniqueCitationItems(items) {
  const seen = new Set();
  const result = [];
  for (const item of items) {
    const citation = item.citation || {};
    const key = normalizeCitationReference(citation.id || citation.raw_reference || citation.label || citation.title);
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(item);
  }
  return result;
}

function citationContextKey(context) {
  return [
    context.page_number || "",
    context.marker || "",
    normalizeCitationReference(context.sentence || ""),
  ].join("|");
}

function citationChoiceTitle(citation) {
  return normalizeCitationReference(citation.raw_reference || citation.title || citation.label || "Citation");
}

function citationChoiceMeta(citation) {
  return [
    citation.label,
    citation.year,
  ]
    .map(normalizeCitationReference)
    .filter(Boolean)
    .join(" · ");
}

function citationForGroup(group) {
  const uniqueItems = uniqueCitationItems(group.items);
  if (uniqueItems.length === 1) {
    return uniqueItems[0].citation;
  }

  const firstCitation = uniqueItems[0]?.citation || {};
  const references = uniqueValues(uniqueItems.map((item) => item.citation?.raw_reference || ""));
  const titles = uniqueValues(uniqueItems.map((item) => item.citation?.title || ""));
  const contexts = [];
  const seenContexts = new Set();
  for (const item of group.items) {
    const key = citationContextKey(item.context);
    if (!seenContexts.has(key)) {
      seenContexts.add(key);
      contexts.push(item.context);
    }
  }

  return {
    ...firstCitation,
    id: `citation-group-${group.label}-${references.join("|")}`,
    label: group.label,
    title: titles.length ? `${group.label} (${titles.length} references)` : group.label,
    authors: "",
    year: "",
    raw_reference: references.join("\n"),
    raw_references: references,
    grouped_citations: uniqueItems.map((item) => item.citation),
    contexts,
    resolved: uniqueItems.every((item) => item.citation?.resolved),
  };
}

function selectHighlight(highlightIndex) {
  state.activeHighlightIndex = highlightIndex;
  els.highlightList?.querySelectorAll(".highlight-card").forEach((node) => node.classList.remove("active"));
  els.pdfViewer?.querySelectorAll(".highlight-rect").forEach((node) => node.classList.remove("active"));
  const card = els.highlightList?.querySelector(`[data-highlight-index="${highlightIndex}"]`);
  if (card) {
    const behavior = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
      ? "auto"
      : "smooth";
    card.classList.add("active");
    card.scrollIntoView({ behavior, block: "center" });
  }
  els.pdfViewer?.querySelectorAll(`[data-highlight-index="${highlightIndex}"]`).forEach((node) => {
    node.classList.add("active");
  });
}

function clearActiveHighlight() {
  state.activeHighlightIndex = null;
  els.highlightList?.querySelectorAll(".highlight-card").forEach((node) => node.classList.remove("active"));
  els.pdfViewer?.querySelectorAll(".highlight-rect").forEach((node) => node.classList.remove("active"));
  syncHighlightNavigation();
}

function flashUnavailableHighlight(highlightIndex) {
  const card = els.highlightList?.querySelector(`[data-highlight-index="${highlightIndex}"]`);
  if (!card) {
    return;
  }
  card.classList.remove("source-unavailable-flash");
  void card.offsetWidth;
  card.classList.add("source-unavailable-flash");
  window.setTimeout(() => card.classList.remove("source-unavailable-flash"), 700);
}

function setHighlightHover(highlightIndex, isHovered) {
  els.pdfViewer?.querySelectorAll(`[data-highlight-index="${highlightIndex}"]`).forEach((node) => {
    node.classList.toggle("hover", isHovered);
  });
}

function visibleHighlightIndexes() {
  return filteredHighlights(state.selectedPaper?.highlights || []).map((highlight) => highlight.highlightIndex);
}

function scrollReaderRectIntoView(nodeRect, block = "center") {
  if (!nodeRect || !els.readerPanel) {
    return;
  }

  const panelRect = els.readerPanel.getBoundingClientRect();
  const top = nodeRect.top - panelRect.top + els.readerPanel.scrollTop;
  const left = nodeRect.left - panelRect.left + els.readerPanel.scrollLeft;
  const targetTop = block === "start"
    ? top
    : top - (els.readerPanel.clientHeight - nodeRect.height) / 2;
  const targetLeft = left - (els.readerPanel.clientWidth - nodeRect.width) / 2;
  els.readerPanel.scrollTop = Math.max(0, targetTop);
  els.readerPanel.scrollLeft = Math.max(0, targetLeft);
}

function scrollReaderNodeIntoView(node, block = "center") {
  scrollReaderRectIntoView(node?.getBoundingClientRect(), block);
}

const highlightNavigationController = createHighlightNavigationController({
  getHighlight: (highlightIndex) => (
    state.selectedPaper?.overlay_highlights
    || state.selectedPaper?.highlights
    || []
  )[highlightIndex],
  getVisibleHighlightIndexes: visibleHighlightIndexes,
  getActiveHighlightIndex: () => state.activeHighlightIndex,
  getSourceNodes: (highlightIndex) => (
    els.pdfViewer?.querySelectorAll(`[data-highlight-index="${highlightIndex}"]`) || []
  ),
  selectHighlight,
  closeCompetingPopovers: () => {
    window.getSelection()?.removeAllRanges();
    hideSelectionPopover();
    hideCitationPopover();
    hideFigurePopover();
  },
  centerSource: (rect) => scrollReaderRectIntoView(rect),
  openHighlightPopover,
  hideHighlightPopover,
  flashUnavailableHighlight,
  notifySourceUnavailable: () => showToast("Source location unavailable for this Highlight"),
  updateButtons: ({ previousDisabled, nextDisabled }) => {
    if (els.previousHighlightButton) {
      els.previousHighlightButton.disabled = previousDisabled;
    }
    if (els.nextHighlightButton) {
      els.nextHighlightButton.disabled = nextDisabled;
    }
  },
});

function jumpToHighlight(highlightIndex) {
  highlightNavigationController.activate(highlightIndex);
}

function syncHighlightNavigation() {
  highlightNavigationController.syncButtons();
}

function stepHighlight(delta) {
  highlightNavigationController.step(delta);
}

function jumpToEvidenceTarget(target) {
  if (!target) {
    return;
  }

  if (target.type === "highlight") {
    const highlight = (state.selectedPaper?.highlights || [])[target.highlightIndex];
    if (highlight?.page_number && highlight.rects?.length) {
      selectHighlight(target.highlightIndex);
      showSelectionPreview({
        pageNumber: highlight.page_number,
        rects: highlight.rects,
      }, { flash: Boolean(target.flash), className: "summary-active-rect" });
      const firstRect = els.pdfViewer?.querySelector(".selection-preview-rect");
      if (firstRect) {
        scrollReaderNodeIntoView(firstRect);
        return;
      }
    }
    jumpToHighlight(target.highlightIndex);
    return;
  }

  if (target.type === "figure") {
    const figure = (state.selectedPaper?.figures || []).find((item) => item.id === target.figureId);
    const node = Array.from(els.pdfViewer?.querySelectorAll("[data-figure-id]") || [])
      .find((item) => item.dataset.figureId === target.figureId);
    if (node && figure) {
      scrollReaderNodeIntoView(node);
      showFigurePopover(figure, node.getBoundingClientRect());
    }
    return;
  }

  if (target.type === "text" && target.pageNumber && target.rects?.length) {
    showSelectionPreview({
      pageNumber: target.pageNumber,
      rects: target.rects,
    }, { flash: Boolean(target.flash) });
    const firstRect = els.pdfViewer?.querySelector(".selection-preview-rect");
    if (firstRect) {
      scrollReaderNodeIntoView(firstRect);
      return;
    }
  }

  if (target.pageNumber) {
    jumpToPage(target.pageNumber);
  }
}

function jumpToSummaryEvidence(targetIndex) {
  jumpToEvidenceTarget(state.summaryEvidenceTargets[targetIndex]);
}

function jumpToPage(pageNumber) {
  if (!pageNumber) {
    return;
  }
  const page = els.pdfViewer?.querySelector(`[data-page-number="${pageNumber}"]`);
  if (page) {
    scrollReaderNodeIntoView(page, "start");
  }
}

function pageReferenceSelection(pageNumber) {
  const pageSize = pageSizeFor(pageNumber);
  if (pageSize?.width && pageSize?.height) {
    const marginX = Math.max(8, pageSize.width * 0.025);
    const marginY = Math.max(8, pageSize.height * 0.025);
    return {
      pageNumber,
      rects: [[
        marginX,
        marginY,
        Math.max(marginX + 4, pageSize.width - marginX),
        Math.max(marginY + 4, pageSize.height - marginY),
      ]],
    };
  }

  const page = els.pdfViewer?.querySelector(`[data-page-number="${pageNumber}"]`);
  if (!page) {
    return { pageNumber };
  }

  const inset = 10;
  return {
    pageNumber,
    previewRects: [[
      inset,
      inset,
      Math.max(inset + 4, page.clientWidth - inset),
      Math.max(inset + 4, page.clientHeight - inset),
    ]],
  };
}

function jumpToChatPageReference(pageNumber) {
  if (!pageNumber) {
    return;
  }
  const page = els.pdfViewer?.querySelector(`[data-page-number="${pageNumber}"]`);
  if (!page) {
    return;
  }

  jumpToPage(pageNumber);
  showSelectionPreview(pageReferenceSelection(pageNumber), {
    className: "chat-page-reference-rect",
    flash: true,
    durationMs: 2200,
  });
}

function highlightsByPage(highlights) {
  const map = new Map();
  for (const [index, highlight] of (highlights || []).entries()) {
    const hasSourceArea = highlight.rects?.length || highlight.source?.bbox_pct?.length === 4;
    if (!highlight.page_number || !hasSourceArea) {
      continue;
    }
    const pageHighlights = map.get(highlight.page_number) || [];
    pageHighlights.push({ ...highlight, highlightIndex: highlight.highlightIndex ?? index });
    map.set(highlight.page_number, pageHighlights);
  }
  return map;
}

function figuresByPage(figures) {
  const map = new Map();
  for (const figure of figures || []) {
    if (!figure?.page_number || !Array.isArray(figure.bbox_pct)) {
      continue;
    }
    const pageFigures = map.get(figure.page_number) || [];
    pageFigures.push(figure);
    map.set(figure.page_number, pageFigures);
  }
  return map;
}

async function renderPdf(paper, options = {}) {
  const shouldResetViewport = options.resetViewport !== false;
  const token = ++state.renderToken;
  state.pageTexts = new Map();
  state.pageWords = new Map();
  state.textSelectionDrag = null;
  hideSelectionPopover();
  hideCitationPopover();
  hideFigurePopover();
  hideHighlightPopover();
  clearActiveHighlight();
  els.readerEmpty?.classList.add("hidden");
  els.pdfViewer?.classList.remove("hidden");
  setHtml(els.pdfViewer, `<div class="loading">Rendering PDF</div>`);
  if (shouldResetViewport) {
    resetPaperViewport();
  }

  const previousDocument = state.pdfDocument;
  const previousLoadingTask = state.pdfLoadingTask;
  state.pdfDocument = null;
  state.pdfLoadingTask = pdfjsLib.getDocument(`/api/papers/${paper.id}/file`);
  previousLoadingTask?.destroy?.();
  if (previousDocument) {
    await previousDocument.destroy();
  }
  const pdfDoc = await state.pdfLoadingTask.promise;
  if (token !== state.renderToken) {
    await pdfDoc.destroy();
    return;
  }
  state.pdfDocument = pdfDoc;
  state.pdfLoadingTask = null;
  const overlayHighlights = (paper.overlay_highlights || paper.highlights || []).map((highlight, index) => ({ ...highlight, highlightIndex: highlight.highlightIndex ?? index }));
  const pageHighlights = highlightsByPage(overlayHighlights.filter((highlight) => highlight.origin === "manual" || state.activeHighlightFacet === "all" || highlightLabelId(highlight.label) === state.activeHighlightFacet));
  const pageCitations = citationsByPage(paper.citations);
  const pageFigures = figuresByPage(paper.figures || []);
  const pageSizes = new Map((paper.page_sizes || []).map((page) => [page.page_number, page]));

  const pages = [];
  const pageFragment = document.createDocumentFragment();
  for (let pageNumber = 1; pageNumber <= pdfDoc.numPages; pageNumber += 1) {
    if (token !== state.renderToken) {
      return;
    }

    const page = await pdfDoc.getPage(pageNumber);
    const baseViewport = page.getViewport({ scale: 1 });
    const maxWidth = Math.min(940, Math.max(520, (els.pdfViewer?.clientWidth || 940) - 48));
    const scale = (maxWidth / baseViewport.width) * state.pdfZoom;
    const viewport = page.getViewport({ scale });

    const wrapper = document.createElement("div");
    wrapper.className = "pdf-page";
    wrapper.dataset.pageNumber = String(pageNumber);
    wrapper.style.width = `${viewport.width}px`;
    wrapper.style.height = `${viewport.height}px`;

    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    canvas.width = Math.floor(viewport.width * window.devicePixelRatio);
    canvas.height = Math.floor(viewport.height * window.devicePixelRatio);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;
    context.scale(window.devicePixelRatio, window.devicePixelRatio);
    wrapper.appendChild(canvas);

    const textLayer = document.createElement("div");
    textLayer.className = "text-layer";
    textLayer.style.setProperty("--scale-factor", String(scale));
    wrapper.appendChild(textLayer);

    const overlay = document.createElement("div");
    overlay.className = "overlay-layer";
    wrapper.appendChild(overlay);
    pageFragment.appendChild(wrapper);

    pages.push({ page, pageNumber, viewport, context, textLayer, overlay });
  }

  if (token !== state.renderToken) {
    return;
  }
  setHtml(els.pdfViewer, "");
  els.pdfViewer?.appendChild(pageFragment);

  for (const { page, pageNumber, viewport, context, textLayer, overlay } of pages) {
    if (token !== state.renderToken) {
      return;
    }

    await page.render({ canvasContext: context, viewport }).promise;
    if (token !== state.renderToken) {
      return;
    }

    await renderTextLayer(page, textLayer, viewport, pageNumber);
    if (token !== state.renderToken) {
      return;
    }

    renderPageFigures(overlay, pageFigures.get(pageNumber) || [], viewport);
    renderPageHighlights(overlay, pageHighlights.get(pageNumber) || [], pageSizes.get(pageNumber), viewport);
    renderPageCitations(overlay, pageCitations.get(pageNumber) || [], pageSizes.get(pageNumber), viewport);
  }

  if (state.selectedPaper?.id === paper.id) {
    renderPaperDetails(state.selectedPaper);
  }
  if (shouldResetViewport) {
    resetPaperViewport();
  }
}

async function renderTextLayer(page, textLayer, viewport, pageNumber) {
  const textContent = await page.getTextContent();
  const pageText = textContent.items
    .map((item) => item.str || "")
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  state.pageTexts.set(pageNumber, pageText);

  const layer = new pdfjsLib.TextLayer({
    textContentSource: textContent,
    container: textLayer,
    viewport,
  });
  await layer.render();
  collectTextLayerWords(textLayer, pageNumber);
}

async function renderPdfPreservingScroll(paper) {
  const anchor = pdfScrollAnchor();
  await renderPdf(paper, { resetViewport: false });
  restorePdfScrollAnchor(anchor);
}

function renderPdfAnnotationOverlays(paper, options = {}) {
  const pageNodes = Array.from(els.pdfViewer?.querySelectorAll(".pdf-page[data-page-number]") || []);
  if (!pageNodes.length) {
    return false;
  }

  const readerScrollLeft = els.readerPanel?.scrollLeft || 0;
  const readerScrollTop = els.readerPanel?.scrollTop || 0;
  const pageFigures = figuresByPage(paper.figures || []);
  const overlayHighlights = (paper.overlay_highlights || paper.highlights || []).map((highlight, index) => ({ ...highlight, highlightIndex: highlight.highlightIndex ?? index }));
  const pageHighlights = highlightsByPage(overlayHighlights.filter((highlight) => highlight.origin === "manual" || state.activeHighlightFacet === "all" || highlightLabelId(highlight.label) === state.activeHighlightFacet));
  const pageCitations = citationsByPage(paper.citations);
  const pageSizes = new Map((paper.page_sizes || []).map((page) => [page.page_number, page]));

  for (const pageNode of pageNodes) {
    const overlay = pageNode.querySelector(".overlay-layer");
    if (!overlay) {
      return false;
    }

    const removeSelector = options.figuresOnly ? ".figure-rect" : ".figure-rect, .highlight-rect, .citation-rect";
    overlay.querySelectorAll(removeSelector).forEach((node) => node.remove());
    const pageNumber = Number(pageNode.dataset.pageNumber);
    const viewport = {
      width: pageNode.clientWidth || Number.parseFloat(pageNode.style.width) || 0,
      height: pageNode.clientHeight || Number.parseFloat(pageNode.style.height) || 0,
    };
    renderPageFigures(overlay, pageFigures.get(pageNumber) || [], viewport);
    if (!options.figuresOnly) {
      renderPageHighlights(overlay, pageHighlights.get(pageNumber) || [], pageSizes.get(pageNumber), viewport);
      renderPageCitations(overlay, pageCitations.get(pageNumber) || [], pageSizes.get(pageNumber), viewport);
    }
  }

  if (els.readerPanel) {
    els.readerPanel.scrollLeft = readerScrollLeft;
    els.readerPanel.scrollTop = readerScrollTop;
  }
  return true;
}

function renderPdfFigureOverlays(paper) {
  return renderPdfAnnotationOverlays(paper, { figuresOnly: true });
}

async function refreshReaderAnnotations(paper) {
  if (renderPdfAnnotationOverlays(paper)) {
    return;
  }
  await renderPdfPreservingScroll(paper);
}

async function refreshFigureAnnotations(paper) {
  if (renderPdfFigureOverlays(paper)) {
    return;
  }
  await renderPdfPreservingScroll(paper);
}

function renderPageHighlights(overlay, highlights, pageSize, viewport) {
  if (!pageSize) {
    return;
  }

  const scaleX = viewport.width / pageSize.width;
  const scaleY = viewport.height / pageSize.height;
  for (const highlight of highlights) {
    const labelId = highlightLabelId(highlight.label);
    const color = highlightColor(highlight);
    for (const rect of highlightSourceRects(highlight, pageSize)) {
      const [x0, y0, x1, y1] = rect;
      const node = document.createElement("div");
      node.className = `highlight-rect label-${labelId}`;
      node.title = `${highlightLabelText(highlight.label)}: ${highlight.text || highlight.snippet || ""}`;
      node.dataset.highlightIndex = String(highlight.highlightIndex);
      if (safeHexColor(highlight.color) && color) {
        node.style.background = color;
      }
      node.style.left = `${x0 * scaleX}px`;
      node.style.top = `${y0 * scaleY}px`;
      node.style.width = `${Math.max(6, (x1 - x0) * scaleX)}px`;
      node.style.height = `${Math.max(6, (y1 - y0) * scaleY)}px`;
      node.addEventListener("click", (event) => {
        event.stopPropagation();
        if (event.detail === 0 || node.dataset.suppressClick === "true") {
          delete node.dataset.suppressClick;
          return;
        }
        jumpToHighlight(highlight.highlightIndex);
      });
      node.addEventListener("mouseenter", () => {
        setHighlightHover(highlight.highlightIndex, true);
      });
      node.addEventListener("mouseleave", (event) => {
        const relatedHighlightIndex = event.relatedTarget?.closest?.(".highlight-rect")?.dataset.highlightIndex;
        if (relatedHighlightIndex !== String(highlight.highlightIndex)) {
          setHighlightHover(highlight.highlightIndex, false);
        }
      });
      overlay.appendChild(node);
    }
  }
}

function validFigureBox(figure) {
  const values = (figure?.bbox_pct || []).map(Number);
  if (values.length !== 4 || values.some((value) => !Number.isFinite(value))) {
    return null;
  }

  const [left, top, right, bottom] = values.map((value) => clamp(value, 0, 100));
  if (right <= left || bottom <= top) {
    return null;
  }
  return [left, top, right, bottom];
}

function figureTitle(figure) {
  return String(figure?.label || figure?.title || "Visual").replace(/\s+/g, " ").trim();
}

function renderPageFigures(overlay, figures, viewport) {
  for (const figure of figures) {
    const box = validFigureBox(figure);
    if (!box) {
      continue;
    }

    const [left, top, right, bottom] = box;
    const node = document.createElement("button");
    const isActive = state.activeFigure?.id && state.activeFigure.id === figure.id;
    node.className = `figure-rect ${isActive ? "active" : ""}`;
    node.type = "button";
    node.dataset.figureId = figure.id || "";
    node.title = `${figureTitle(figure)}: ${figure.why_it_matters || figure.explanation || figure.caption || ""}`;
    node.style.left = `${(left / 100) * viewport.width}px`;
    node.style.top = `${(top / 100) * viewport.height}px`;
    node.style.width = `${Math.max(14, ((right - left) / 100) * viewport.width)}px`;
    node.style.height = `${Math.max(14, ((bottom - top) / 100) * viewport.height)}px`;

    node.addEventListener("click", (event) => {
      event.stopPropagation();
      showFigurePopover(figure, node.getBoundingClientRect());
    });
    overlay.appendChild(node);
  }
}

function renderPageCitations(overlay, citations, pageSize, viewport) {
  if (!pageSize) {
    return;
  }

  const scaleX = viewport.width / pageSize.width;
  const scaleY = viewport.height / pageSize.height;
  for (const group of groupedCitationRects(citations)) {
    const [x0, y0, x1, y1] = group.rect;
    const citation = citationForGroup(group);
    const referenceCount = citation.grouped_citations?.length || 1;
    const node = document.createElement("button");
    node.className = "citation-rect";
    node.type = "button";
    node.title = referenceCount > 1
      ? `${group.label}: ${referenceCount} references`
      : `${citation.label || "Citation"}: ${citation.title || ""}`;
    node.style.left = `${x0 * scaleX}px`;
    node.style.top = `${y0 * scaleY}px`;
    node.style.width = `${Math.max(8, (x1 - x0) * scaleX)}px`;
    node.style.height = `${Math.max(8, (y1 - y0) * scaleY)}px`;
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      showCitationPopover(citation, node.getBoundingClientRect());
    });
    overlay.appendChild(node);
  }
}

async function loadSelectedPaper() {
  if (state.uploadPromise) {
    return state.uploadPromise;
  }

  const files = Array.from(els.pdfInput?.files || []);
  if (!files.length) {
    showToast("Choose one or more PDFs first");
    return null;
  }

  showToast(`Loading ${files.length} PDF${files.length === 1 ? "" : "s"}`, true);
  showReaderLoading();

  state.uploadPromise = (async () => {
    const uploadedPapers = [];

    for (const [index, file] of files.entries()) {
      const formData = new FormData();
      formData.append("file", file);
      showToast(`Loading ${index + 1}/${files.length}: ${file.name}`, true);
      const paper = await requestJson("/api/upload", {
        method: "POST",
        body: formData,
      });
      uploadedPapers.push(paper);
    }

    prependPaperSummaries(uploadedPapers);
    renderPaperList();

    const selectedPaper = uploadedPapers[0] || null;
    if (selectedPaper) {
      if (state.selectedPaper?.id === selectedPaper.id && state.pdfDocument) {
        applySelectedPaperUpdate(selectedPaper);
        await refreshReaderAnnotations(selectedPaper);
      } else {
        setSelectedPaper(selectedPaper);
        await renderPdf(selectedPaper);
      }
    }

    if (els.pdfInput) {
      els.pdfInput.value = "";
    }
    hideToast();
    showToast(
      files.length === 1
        ? "PDF loaded. Click Analyze when ready."
        : `${files.length} PDFs loaded. Select a paper or click Analyze for the first one.`,
    );
    return selectedPaper;
  })()
    .finally(() => {
      state.uploadPromise = null;
    });

  return state.uploadPromise;
}

async function startSelectedPaperAnalysis(event) {
  event.preventDefault();
  if (!requireOpenAiKey()) {
    return;
  }

  let paper = state.uploadPromise ? await state.uploadPromise : state.selectedPaper;
  if (!paper && els.pdfInput?.files?.length) {
    paper = await loadSelectedPaper();
  }
  if (!paper) {
    showToast("Choose a PDF first");
    return;
  }
  if (paper.analysis_status === "analyzing") {
    showToast("Analysis is already running");
    pollPaperAnalysis(paper.id);
    return;
  }

  const isReanalysis = paper.analysis_status === "complete";
  if (isReanalysis && !window.confirm("Reanalysis replaces the generated narrative after a complete new analysis succeeds. Manual highlights will be preserved. Continue?")) {
    return;
  }
  showToast("Analysis is running. You can keep reading.", true);
  paper = await requestJson(`/api/papers/${paper.id}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider: selectedProvider(),
      api_key: requestApiKey() || null,
      reanalyze: isReanalysis,
      ...textModelRequestOptions(),
    }),
  });
  setSelectedPaper(paper, { preserveWorkspace: isReanalysis });
  if (paper.reanalysis_status === "analyzing") {
    hideToast();
    showToast("Reanalysis started. The current narrative remains available.");
    pollPaperAnalysis(paper.id);
  } else if (paper.analysis_status === "complete") {
    await refreshReaderAnnotations(paper);
    hideToast();
    if (paperNeedsPolling(paper)) {
      pollPaperAnalysis(paper.id);
    }
  } else {
    hideToast();
    showToast("Analysis started. Keep reading while it runs.");
    pollPaperAnalysis(paper.id);
  }
}

function paperNeedsPolling(paper) {
  if (!paper || paper.analysis_status === "error" || paper.reanalysis_status === "error") {
    return false;
  }
  return paper.analysis_status === "analyzing"
    || paper.reanalysis_status === "analyzing"
    || paper.citation_status === "pending"
    || paper.citation_status === "analyzing";
}

function pollPaperAnalysis(paperId) {
  if (state.analysisPoll) {
    window.clearTimeout(state.analysisPoll);
  }
  if (!state.selectedPaper || state.selectedPaper.id !== paperId || !paperNeedsPolling(state.selectedPaper)) {
    state.analysisPoll = null;
    return;
  }

  state.analysisPoll = window.setTimeout(async () => {
    try {
      const paper = await requestJson(`/api/papers/${paperId}`);
      if (!state.selectedPaper || state.selectedPaper.id !== paperId) {
        return;
      }
      const previousRevision = state.selectedPaper.analysis_revision || 0;
      state.selectedPaper = paper;
      if ((paper.analysis_revision || 0) > previousRevision) {
        resetChat();
        state.activeHighlightFacet = "all";
      } else {
        syncSelectedFigures();
      }
      upsertPaperSummary(paper);
      renderPaperList();
      renderPaperDetails(paper);
      renderChatFigureFocus();
      syncPaperActions();
      if (paper.reanalysis_status === "error") {
        hideToast();
        showToast(paper.reanalysis_error || "Reanalysis failed");
      } else if (paper.analysis_status === "error") {
        hideToast();
        showToast(paper.analysis_error || "Analysis failed");
      } else if (paper.analysis_status === "complete") {
        await refreshReaderAnnotations(paper);
        renderPaperDetails(paper);
        hideToast();
        if (paperNeedsPolling(paper)) {
          pollPaperAnalysis(paperId);
        }
      } else if (paperNeedsPolling(paper)) {
        pollPaperAnalysis(paperId);
      }
    } catch (error) {
      showToast(error.message || String(error));
    }
  }, 2500);
}



function renderChat() {
  if (!els.chatMessages) {
    return;
  }

  if (!state.chatMessages.length) {
    setHtml(els.chatMessages, "");
    return;
  }

  els.chatMessages.replaceChildren();
  for (const message of state.chatMessages) {
    const role = message.role === "user" ? "user" : "assistant";
    const article = document.createElement("article");
    article.className = `chat-message ${role}`;

    const label = document.createElement("strong");
    label.className = "chat-message-role";
    label.textContent = role === "user" ? "You" : "Assistant";

    const body = document.createElement("div");
    body.className = "chat-markdown";
    renderChatMarkdown(body, message.content, { linkPageReferences: role === "assistant" });

    article.append(label, body);
    els.chatMessages.appendChild(article);
  }

  els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
}

function renderChatMarkdown(target, value, options = {}) {
  const unsafeHtml = marked.parse(String(value || ""));
  target.innerHTML = DOMPurify.sanitize(unsafeHtml, {
    ALLOWED_TAGS: [
      "a",
      "blockquote",
      "br",
      "code",
      "del",
      "em",
      "h1",
      "h2",
      "h3",
      "h4",
      "hr",
      "li",
      "ol",
      "p",
      "pre",
      "strong",
      "table",
      "tbody",
      "td",
      "th",
      "thead",
      "tr",
      "ul",
    ],
    ALLOWED_ATTR: ["href", "title"],
  });
  target.querySelectorAll("a[href]").forEach((link) => {
    const href = link.getAttribute("href") || "";
    if (!/^https?:\/\//i.test(href) && !href.startsWith("#")) {
      link.removeAttribute("href");
      return;
    }
    link.target = "_blank";
    link.rel = "noreferrer";
  });

  if (!options.linkPageReferences) {
    return;
  }
  linkifyChatPageReferences(target, { pageCount: currentPageCount() });
  target.querySelectorAll("[data-chat-page-reference]").forEach((button) => {
    button.addEventListener("click", () => {
      jumpToChatPageReference(Number(button.dataset.chatPageReference));
    });
  });
}

function currentPageCount() {
  const pageNumbers = [];
  for (const page of state.selectedPaper?.page_sizes || []) {
    const pageNumber = Number(page.page_number);
    if (pageNumber) {
      pageNumbers.push(pageNumber);
    }
  }
  els.pdfViewer?.querySelectorAll(".pdf-page[data-page-number]").forEach((page) => {
    const pageNumber = Number(page.dataset.pageNumber);
    if (pageNumber) {
      pageNumbers.push(pageNumber);
    }
  });
  return pageNumbers.length ? Math.max(...pageNumbers) : 0;
}

function pageSizeFor(pageNumber) {
  return (state.selectedPaper?.page_sizes || []).find((page) => page.page_number === pageNumber);
}

function roundRectValue(value) {
  return Math.round(value * 100) / 100;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function cleanSelectedText(words) {
  return words
    .map((word) => word.text)
    .join(" ")
    .replace(/\s+([,.;:!?%)\]])/g, "$1")
    .replace(/([([])\s+/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function textLayerWords(textLayer, pageNumber) {
  const page = textLayer.closest(".pdf-page");
  const pageSize = pageSizeFor(pageNumber);
  if (!page || !pageSize) {
    return [];
  }

  const pageRect = page.getBoundingClientRect();
  const scaleX = pageSize.width / pageRect.width;
  const scaleY = pageSize.height / pageRect.height;
  const words = [];

  textLayer.querySelectorAll("span").forEach((span) => {
    const text = span.textContent || "";
    const matches = Array.from(text.matchAll(/\S+/g));
    if (!matches.length) {
      return;
    }

    const spanRect = span.getBoundingClientRect();
    if (spanRect.width < 1 || spanRect.height < 1) {
      return;
    }

    const textLength = Math.max(text.length, 1);
    for (const match of matches) {
      const startRatio = match.index / textLength;
      const endRatio = (match.index + match[0].length) / textLength;
      const x0 = spanRect.left - pageRect.left + spanRect.width * startRatio;
      const x1 = spanRect.left - pageRect.left + spanRect.width * endRatio;
      const y0 = spanRect.top - pageRect.top;
      const y1 = spanRect.bottom - pageRect.top;
      words.push({
        text: match[0],
        cssRect: [x0, y0, x1, y1].map(roundRectValue),
        pdfRect: [
          roundRectValue(x0 * scaleX),
          roundRectValue(y0 * scaleY),
          roundRectValue(x1 * scaleX),
          roundRectValue(y1 * scaleY),
        ],
      });
    }
  });

  return words;
}

function collectTextLayerWords(textLayer, pageNumber) {
  state.pageWords.set(pageNumber, textLayerWords(textLayer, pageNumber));
}

function currentPageWords() {
  const pageWords = new Map(state.pageWords);
  els.pdfViewer?.querySelectorAll(".pdf-page[data-page-number]").forEach((page) => {
    const pageNumber = Number(page.dataset.pageNumber);
    if (!pageNumber) {
      return;
    }
    const textLayer = page.querySelector(".text-layer");
    if (!textLayer) {
      return;
    }
    const words = textLayerWords(textLayer, pageNumber);
    if (words.length) {
      state.pageWords.set(pageNumber, words);
      pageWords.set(pageNumber, words);
    }
  });
  return pageWords;
}

function distanceToRect(x, y, rect) {
  const dx = x < rect[0] ? rect[0] - x : x > rect[2] ? x - rect[2] : 0;
  const dy = y < rect[1] ? rect[1] - y : y > rect[3] ? y - rect[3] : 0;
  return dx * dx + dy * dy;
}

function nearestWordIndex(words, x, y) {
  let bestIndex = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  words.forEach((word, index) => {
    const distance = distanceToRect(x, y, word.cssRect);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

function mergeWordRects(words, rectKey) {
  return wordLineGroups(words.map((word, index) => ({ word, index }))).map((line) => {
    const rects = line.entries.map((entry) => entry.word[rectKey]);
    return [
      roundRectValue(Math.min(...rects.map((rect) => rect[0]))),
      roundRectValue(Math.min(...rects.map((rect) => rect[1]))),
      roundRectValue(Math.max(...rects.map((rect) => rect[2]))),
      roundRectValue(Math.max(...rects.map((rect) => rect[3]))),
    ];
  });
}

function clientRectForWords(page, words) {
  const pageRect = page.getBoundingClientRect();
  const rects = mergeWordRects(words, "cssRect");
  return {
    left: pageRect.left + Math.min(...rects.map((rect) => rect[0])),
    top: pageRect.top + Math.min(...rects.map((rect) => rect[1])),
    width: Math.max(...rects.map((rect) => rect[2])) - Math.min(...rects.map((rect) => rect[0])),
    height: Math.max(...rects.map((rect) => rect[3])) - Math.min(...rects.map((rect) => rect[1])),
  };
}

function clearSelectionPreview() {
  els.pdfViewer?.querySelectorAll(".selection-preview-rect").forEach((node) => node.remove());
}

function selectionPreviewRects(selection, page) {
  if (selection.previewRects?.length) {
    return selection.previewRects;
  }

  const pageSize = pageSizeFor(selection.pageNumber);
  if (!pageSize) {
    return [];
  }
  const pageRect = page.getBoundingClientRect();
  const scaleX = pageRect.width / pageSize.width;
  const scaleY = pageRect.height / pageSize.height;
  return (selection.rects || []).map((rect) => [
    roundRectValue(rect[0] * scaleX),
    roundRectValue(rect[1] * scaleY),
    roundRectValue(rect[2] * scaleX),
    roundRectValue(rect[3] * scaleY),
  ]);
}

function showSelectionPreview(selection, options = {}) {
  clearSelectionPreview();
  if (!selection?.pageNumber) {
    return;
  }

  const page = els.pdfViewer?.querySelector(`[data-page-number="${selection.pageNumber}"]`);
  const overlay = page?.querySelector(".overlay-layer");
  if (!overlay) {
    return;
  }

  const previewNodes = [];
  for (const rect of selectionPreviewRects(selection, page)) {
    const [x0, y0, x1, y1] = rect;
    const node = document.createElement("div");
    node.className = [
      "selection-preview-rect",
      options.flash ? "summary-flash-rect" : "",
      options.className || "",
    ].filter(Boolean).join(" ");
    node.style.left = `${x0}px`;
    node.style.top = `${y0}px`;
    node.style.width = `${Math.max(4, x1 - x0)}px`;
    node.style.height = `${Math.max(4, y1 - y0)}px`;
    overlay.appendChild(node);
    previewNodes.push(node);
  }

  if (options.durationMs) {
    window.setTimeout(() => {
      previewNodes.forEach((node) => node.remove());
    }, options.durationMs);
  }
}

function selectionRectsForPage(range, page, pageNumber) {
  const pageSize = pageSizeFor(pageNumber);
  if (!pageSize) {
    return [];
  }

  const pageRect = page.getBoundingClientRect();
  const scaleX = pageSize.width / pageRect.width;
  const scaleY = pageSize.height / pageRect.height;
  return Array.from(range.getClientRects())
    .map((rect) => {
      const left = Math.max(rect.left, pageRect.left);
      const top = Math.max(rect.top, pageRect.top);
      const right = Math.min(rect.right, pageRect.right);
      const bottom = Math.min(rect.bottom, pageRect.bottom);
      if (right - left < 2 || bottom - top < 2) {
        return null;
      }
      return [
        roundRectValue((left - pageRect.left) * scaleX),
        roundRectValue((top - pageRect.top) * scaleY),
        roundRectValue((right - pageRect.left) * scaleX),
        roundRectValue((bottom - pageRect.top) * scaleY),
      ];
    })
    .filter(Boolean);
}

function selectedTextFromPdf() {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
    return null;
  }

  const text = selection.toString().replace(/\s+/g, " ").trim();
  if (text.length < 2 || text.length > 700) {
    return null;
  }

  const range = selection.getRangeAt(0);
  const container = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
    ? range.commonAncestorContainer
    : range.commonAncestorContainer.parentElement;
  const page = container?.closest?.(".pdf-page");
  if (!page) {
    return null;
  }

  const rect = range.getBoundingClientRect();
  if (!rect.width && !rect.height) {
    return null;
  }

  const pageNumber = Number(page.dataset.pageNumber) || null;
  const rects = selectionRectsForPage(range, page, pageNumber);
  if (!rects.length) {
    return null;
  }
  return {
    text,
    pageNumber,
    pageText: state.pageTexts.get(pageNumber) || "",
    rect,
    rects,
  };
}

function pagePointFromEvent(event, page) {
  const pageRect = page.getBoundingClientRect();
  return {
    x: clamp(event.clientX - pageRect.left, 0, pageRect.width),
    y: clamp(event.clientY - pageRect.top, 0, pageRect.height),
  };
}

function customSelectionFromDrag(drag, event) {
  const words = state.pageWords.get(drag.pageNumber) || [];
  if (!words.length) {
    return null;
  }

  const end = pagePointFromEvent(event, drag.page);
  const startIndex = nearestWordIndex(words, drag.x, drag.y);
  const endIndex = nearestWordIndex(words, end.x, end.y);
  if (startIndex === null || endIndex === null) {
    return null;
  }

  const firstIndex = Math.min(startIndex, endIndex);
  const lastIndex = Math.max(startIndex, endIndex);
  const selectedWords = words.slice(firstIndex, lastIndex + 1);
  const text = cleanSelectedText(selectedWords);
  if (text.length < 2 || text.length > 900) {
    return null;
  }

  return {
    text,
    pageNumber: drag.pageNumber,
    pageText: state.pageTexts.get(drag.pageNumber) || "",
    rects: mergeWordRects(selectedWords, "pdfRect"),
    previewRects: mergeWordRects(selectedWords, "cssRect"),
    rect: clientRectForWords(drag.page, selectedWords),
  };
}

function startTextSelection(event) {
  if (event.button !== 0 || event.target.closest?.(".citation-rect, .figure-rect")) {
    return;
  }

  const page = event.target.closest?.(".pdf-page");
  const pageNumber = Number(page?.dataset.pageNumber) || null;
  if (!page || !pageNumber || !(state.pageWords.get(pageNumber) || []).length) {
    return;
  }

  const point = pagePointFromEvent(event, page);
  state.textSelectionDrag = {
    page,
    pageNumber,
    x: point.x,
    y: point.y,
    clientX: event.clientX,
    clientY: event.clientY,
    overlayTarget: event.target.closest?.(".highlight-rect") || null,
  };
  window.getSelection()?.removeAllRanges();
  hideSelectionPopover();
  hideCitationPopover();
  hideFigurePopover();
  hideHighlightPopover();
  clearActiveHighlight();
  event.preventDefault();
}

function updateTextSelection(event) {
  const drag = state.textSelectionDrag;
  if (!drag) {
    return;
  }

  const distance = Math.hypot(event.clientX - drag.clientX, event.clientY - drag.clientY);
  if (distance < 4) {
    clearSelectionPreview();
    return;
  }

  drag.overlayTarget?.setAttribute("data-suppress-click", "true");

  const selection = customSelectionFromDrag(drag, event);
  if (selection) {
    showSelectionPreview(selection);
  }
}

function finishTextSelection(event) {
  const drag = state.textSelectionDrag;
  state.textSelectionDrag = null;
  if (!drag) {
    return;
  }

  const distance = Math.hypot(event.clientX - drag.clientX, event.clientY - drag.clientY);
  if (distance < 4) {
    clearSelectionPreview();
    return;
  }

  const selection = customSelectionFromDrag(drag, event);
  if (selection) {
    showSelectionPopoverFor(selection);
  } else {
    clearSelectionPreview();
  }
}

function renderSelectionHighlightCategories() {
  if (!els.highlightCategorySelect) {
    return;
  }

  const options = highlightCategoryOptions(state.selectedPaper?.highlights || []);
  setHtml(
    els.highlightCategorySelect,
    `${options
      .map((option) => `<option value="${escapeHtml(option.id)}">${escapeHtml(option.label)}</option>`)
      .join("")}
      <option value="__new__">New category</option>`,
  );

  const preferred = state.activeHighlightFacet !== "all" ? state.activeHighlightFacet : "problem";
  els.highlightCategorySelect.value = options.some((option) => option.id === preferred)
    ? preferred
    : options[0]?.id || "__new__";
  syncSelectionHighlightForm();
}

function resetSelectionHighlightForm() {
  els.selectionHighlightForm?.classList.add("hidden");
  if (els.highlightTextInput) {
    els.highlightTextInput.value = state.activeSelection?.text || "";
  }
  if (els.highlightCategoryInput) {
    els.highlightCategoryInput.value = "";
  }
  if (els.highlightColorInput) {
    els.highlightColorInput.value = DEFAULT_HIGHLIGHT_COLORS.important;
  }
  renderSelectionHighlightCategories();
}

function syncSelectionHighlightForm() {
  const isNewCategory = els.highlightCategorySelect?.value === "__new__";
  els.highlightCategoryInput?.classList.toggle("hidden", !isNewCategory);
  els.highlightColorInput?.classList.toggle("hidden", !isNewCategory);
  if (isNewCategory) {
    els.highlightCategoryInput?.focus();
  }
}

function showSelectionPopoverFor(selection) {
  if (!selection || !els.selectionPopover) {
    hideSelectionPopover();
    return;
  }
  hideCitationPopover();
  hideFigurePopover();
  hideHighlightPopover();
  clearActiveHighlight();

  state.activeSelection = {
    text: selection.text,
    pageNumber: selection.pageNumber,
    pageText: selection.pageText,
    rects: selection.rects,
  };
  showSelectionPreview(selection);
  resetSelectionHighlightForm();

  const popover = els.selectionPopover;
  popover.classList.remove("hidden");
  const top = Math.max(8, selection.rect.top - popover.offsetHeight - 8);
  const left = Math.min(
    window.innerWidth - popover.offsetWidth - 8,
    Math.max(8, selection.rect.left + selection.rect.width / 2 - popover.offsetWidth / 2),
  );
  popover.style.top = `${top}px`;
  popover.style.left = `${left}px`;
}

function showSelectionPopover() {
  showSelectionPopoverFor(selectedTextFromPdf());
}

function hideSelectionPopover() {
  state.activeSelection = null;
  clearSelectionPreview();
  els.selectionHighlightForm?.classList.add("hidden");
  els.selectionPopover?.classList.add("hidden");
}

function isEditableTarget(target) {
  const element = target?.nodeType === Node.ELEMENT_NODE ? target : target?.parentElement;
  return Boolean(element?.closest?.("input, textarea, select, [contenteditable]"));
}

function activeSelectionCopyText() {
  return String(state.activeSelection?.text || "").replace(/\s+/g, " ").trim();
}

function copyActiveSelection(event = null) {
  const text = activeSelectionCopyText();
  if (!text) {
    return false;
  }

  if (event?.clipboardData) {
    event.clipboardData.setData("text/plain", text);
    event.preventDefault();
    showToast("Copied selected text");
    return true;
  }

  if (!navigator.clipboard?.writeText) {
    showToast("Copy unavailable");
    return true;
  }

  navigator.clipboard.writeText(text)
    .then(() => showToast("Copied selected text"))
    .catch(() => showToast("Copy failed"));
  return true;
}

function renderHighlightPopover(highlight) {
  const explanation = String(highlight?.text || highlight?.snippet || "").trim();
  const page = highlight?.page_number ? `p. ${highlight.page_number}` : "unplaced";
  const figure = highlight?.source?.type === "figure"
    ? (state.selectedPaper?.figures || []).find((item) => item.id === highlight.source.visual_id)
    : null;
  setHtml(
    els.highlightPopover,
    `
      <div class="highlight-popover-copy">
        <div class="highlight-popover-heading">
          <span class="label label-${escapeHtml(highlightLabelId(highlight?.label))}"${customHighlightStyle(highlight)}>${escapeHtml(highlightLabelText(highlight?.label))}</span>
          <span>${escapeHtml(page)}</span>
          <button class="highlight-popover-close" data-close-highlight type="button" aria-label="Close">×</button>
        </div>
        <p>${escapeHtml(explanation || "No explanation available yet.")}</p>
      </div>
      <div class="popover-actions">
        ${figure
          ? '<button data-add-highlight-figure type="button">Add figure to chat</button>'
          : '<button data-explain-highlight type="button">Explain in chat</button>'}
        ${highlight?.origin === "manual" ? '<button data-remove-highlight type="button">Remove</button>' : ''}
      </div>
    `,
  );
}

function openHighlightPopover(highlightIndex, rect) {
  if (!state.selectedPaper || !els.highlightPopover || !rect) {
    return;
  }

  const highlight = (state.selectedPaper.overlay_highlights || state.selectedPaper.highlights || [])[highlightIndex];
  if (!highlight) {
    hideHighlightPopover();
    return;
  }

  renderHighlightPopover(highlight);
  const popover = els.highlightPopover;
  popover.classList.remove("hidden");
  const top = Math.max(8, rect.top - popover.offsetHeight - 8);
  const left = Math.min(
    window.innerWidth - popover.offsetWidth - 8,
    Math.max(8, rect.left + rect.width / 2 - popover.offsetWidth / 2),
  );
  popover.style.top = `${top}px`;
  popover.style.left = `${left}px`;
}

function hideHighlightPopover() {
  els.highlightPopover?.classList.add("hidden");
}

function figureTextBlock(label, text) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  return value ? `<p><b>${escapeHtml(label)}:</b> ${escapeHtml(value)}</p>` : "";
}

function renderFigurePopover(figure) {
  setHtml(
    els.figurePopover,
    `
      <div class="figure-popover-copy">
        <div class="figure-popover-heading figure-popover-drag-handle">
          <span class="label label-important">${escapeHtml(figure?.type || "visual")}</span>
          <span>p. ${Number(figure?.page_number) || "?"}</span>
          <button class="figure-popover-close" data-close-figure type="button" aria-label="Close">×</button>
        </div>
        <strong>${escapeHtml(figureTitle(figure))}</strong>
        ${figureTextBlock("Big picture", figure?.why_it_matters)}
        ${figureTextBlock("What it shows / results", figure?.explanation)}
      </div>
      <button data-add-active-figure type="button">Add figure to chat</button>
    `,
  );
}

function selectFigure(figureId) {
  els.pdfViewer?.querySelectorAll(".figure-rect").forEach((node) => {
    node.classList.toggle("active", node.dataset.figureId === figureId);
  });
}

function showFigurePopover(figure, rect) {
  if (!figure || !els.figurePopover) {
    hideFigurePopover();
    return;
  }

  hideSelectionPopover();
  hideCitationPopover();
  hideHighlightPopover();
  clearActiveHighlight();
  state.activeFigure = figure;
  selectFigure(figure.id || "");
  renderFigurePopover(figure);

  const popover = els.figurePopover;
  popover.classList.remove("hidden");
  const top = Math.max(8, rect.top - popover.offsetHeight - 8);
  const left = Math.min(
    window.innerWidth - popover.offsetWidth - 8,
    Math.max(8, rect.left + rect.width / 2 - popover.offsetWidth / 2),
  );
  popover.style.top = `${top}px`;
  popover.style.left = `${left}px`;
}

function hideFigurePopover() {
  state.activeFigure = null;
  state.figurePopoverDrag = null;
  els.figurePopover?.classList.add("hidden");
  els.pdfViewer?.querySelectorAll(".figure-rect.active").forEach((node) => node.classList.remove("active"));
}

function startFigurePopoverDrag(event) {
  const handle = event.target.closest?.(".figure-popover-drag-handle");
  if (!handle || event.target.closest?.("button") || !els.figurePopover) {
    return;
  }

  event.preventDefault();
  const rect = els.figurePopover.getBoundingClientRect();
  state.figurePopoverDrag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    left: rect.left,
    top: rect.top,
  };
  els.figurePopover.setPointerCapture?.(event.pointerId);
}

function moveFigurePopover(event) {
  const drag = state.figurePopoverDrag;
  if (!drag || !els.figurePopover) {
    return;
  }

  const nextLeft = clamp(drag.left + event.clientX - drag.startX, 8, window.innerWidth - els.figurePopover.offsetWidth - 8);
  const nextTop = clamp(drag.top + event.clientY - drag.startY, 8, window.innerHeight - els.figurePopover.offsetHeight - 8);
  els.figurePopover.style.left = `${nextLeft}px`;
  els.figurePopover.style.top = `${nextTop}px`;
}

function finishFigurePopoverDrag(event) {
  const drag = state.figurePopoverDrag;
  if (!drag) {
    return;
  }

  els.figurePopover?.releasePointerCapture?.(drag.pointerId || event.pointerId);
  state.figurePopoverDrag = null;
}

function renderCitationPopover(citation) {
  const choices = citation.grouped_citations?.length ? citation.grouped_citations : [citation];

  setHtml(
    els.citationPopover,
    `
      <div class="citation-choice-list">
        ${choices
          .map((choice, index) => `
            <button class="citation-choice" data-citation-choice="${index}" type="button">
              <span>${escapeHtml(citationChoiceMeta(choice))}</span>
              <strong>${escapeHtml(citationChoiceTitle(choice))}</strong>
            </button>
          `)
          .join("")}
      </div>
    `,
  );
}

function showCitationPopover(citation, rect) {
  if (!citation || !els.citationPopover) {
    hideCitationPopover();
    return;
  }

  hideSelectionPopover();
  hideFigurePopover();
  hideHighlightPopover();
  clearActiveHighlight();
  state.activeCitation = citation;
  renderCitationPopover(citation);
  const popover = els.citationPopover;
  popover.classList.remove("hidden");
  const top = Math.max(8, rect.top - popover.offsetHeight - 8);
  const left = Math.min(
    window.innerWidth - popover.offsetWidth - 8,
    Math.max(8, rect.left + rect.width / 2 - popover.offsetWidth / 2),
  );
  popover.style.top = `${top}px`;
  popover.style.left = `${left}px`;
}

function hideCitationPopover() {
  state.activeCitation = null;
  els.citationPopover?.classList.add("hidden");
}

function applySelectedPaperUpdate(paper) {
  state.selectedPaper = paper;
  upsertPaperSummary(paper);
  syncPaperActions();
  renderPaperList();
  renderPaperDetails(paper);
}

function selectedPaperWithFigurePayload(payload) {
  const figures = payload.figures || [];
  return {
    ...state.selectedPaper,
    figures,
    figure_warnings: payload.warnings || [],
    figure_provider_used: payload.provider_used || "unknown",
    figure_analysis_status: payload.status || "idle",
    figure_analysis_error: payload.error || "",
    figure_analysis_completed_pages: payload.completed_pages || 0,
    figure_analysis_total_pages: payload.total_pages || 0,
    figure_count: figures.length,
  };
}

async function saveHighlights(manualHighlights, message) {
  if (!state.selectedPaper) {
    return;
  }

  const paper = await requestJson(`/api/papers/${state.selectedPaper.id}/highlights`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ manual_highlights: manualHighlights }),
  });
  applySelectedPaperUpdate(paper);
  await renderPdfPreservingScroll(paper);
  showToast(message);
}

function selectedHighlightCategory() {
  const value = els.highlightCategorySelect?.value || "problem";
  if (value !== "__new__") {
    const option = highlightCategoryOptions(state.selectedPaper?.highlights || [])
      .find((item) => item.id === value);
    return {
      label: value,
      color: option && !DEFAULT_HIGHLIGHT_COLORS[highlightLabelId(value)] ? option.color : "",
    };
  }

  const label = String(els.highlightCategoryInput?.value || "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  return {
    label,
    color: safeHexColor(els.highlightColorInput?.value) || DEFAULT_HIGHLIGHT_COLORS.important,
  };
}

async function addActiveSelectionHighlight() {
  if (!state.selectedPaper || !state.activeSelection) {
    hideSelectionPopover();
    return;
  }

  const category = selectedHighlightCategory();
  if (!category.label) {
    showToast("Name the new category");
    els.highlightCategoryInput?.focus();
    return;
  }

  const highlight = {
    label: category.label,
    snippet: (els.highlightTextInput?.value || state.activeSelection.text).replace(/\s+/g, " ").trim(),
    reason: "manual",
    page_number: state.activeSelection.pageNumber,
    rects: state.activeSelection.rects || [],
    reground: true,
  };
  if (!highlight.snippet) {
    showToast("Highlight text is empty");
    els.highlightTextInput?.focus();
    return;
  }
  if (category.color) {
    highlight.color = category.color;
  }

  const highlights = [...(state.selectedPaper.manual_highlights || []), highlight];
  hideSelectionPopover();
  window.getSelection()?.removeAllRanges();
  await saveHighlights(highlights, "Highlight added");
}

async function removeActiveHighlight() {
  if (!state.selectedPaper || state.activeHighlightIndex === null) {
    hideHighlightPopover();
    return;
  }

  const highlight = (state.selectedPaper.overlay_highlights || state.selectedPaper.highlights || [])[state.activeHighlightIndex];
  if (!highlight?.id) {
    hideHighlightPopover();
    return;
  }
  hideHighlightPopover();
  clearActiveHighlight();
  const source = highlight.origin === "manual" ? "manual" : "generated";
  const paper = await requestJson(`/api/papers/${state.selectedPaper.id}/highlights/${encodeURIComponent(highlight.id)}?source=${source}`, { method: "DELETE" });
  applySelectedPaperUpdate(paper);
  await renderPdfPreservingScroll(paper);
  showToast("Highlight removed");
}

async function explainSelection(selection, beforeRequest) {
  if (!state.selectedPaper || !selection) {
    return;
  }
  if (!requireOpenAiKey()) {
    return;
  }

  beforeRequest?.();
  window.getSelection()?.removeAllRanges();

  const label = selection.pageNumber ? `p. ${selection.pageNumber}` : "selected text";
  const userMessage = `Explain "${selection.text}" (${label})`;
  state.chatMessages.push({ role: "user", content: userMessage });
  const pending = { role: "assistant", content: "Explaining..." };
  state.chatMessages.push(pending);
  renderChat();

  const payload = await requestJson(`/api/papers/${state.selectedPaper.id}/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      selected_text: selection.text,
      page_number: selection.pageNumber,
      page_text: selection.pageText,
      provider: selectedProvider(),
      api_key: requestApiKey() || null,
      ...textModelRequestOptions(),
    }),
  });

  pending.content = payload.answer || "No explanation returned.";
  renderChat();
}

async function explainActiveSelection() {
  if (!state.selectedPaper || !state.activeSelection) {
    hideSelectionPopover();
    return;
  }

  await explainSelection(state.activeSelection, hideSelectionPopover);
}

async function explainActiveHighlight() {
  if (!state.selectedPaper || state.activeHighlightIndex === null) {
    hideHighlightPopover();
    return;
  }

  const highlight = (state.selectedPaper.overlay_highlights || state.selectedPaper.highlights || [])[state.activeHighlightIndex];
  const text = highlight?.text || highlight?.snippet || "";
  if (!text) {
    hideHighlightPopover();
    return;
  }

  await explainSelection(
    {
      text,
      pageNumber: highlight.page_number || null,
      pageText: state.pageTexts.get(highlight.page_number) || "",
    },
    hideHighlightPopover,
  );
}

function resetChat() {
  state.chatMessages = [];
  state.pendingCitationContext = null;
  state.selectedFigures = [];
  if (els.chatInput) {
    els.chatInput.value = "";
    resizeChatInput();
    els.chatInput.focus();
  }
  renderChat();
  renderChatFigureFocus();
}

async function sendChatMessage(content, forceWeb = false, citationContext = null) {
  if (!state.selectedPaper) {
    showToast("Select a paper first");
    return;
  }
  if (!requireOpenAiKey()) {
    return;
  }
  if (!citationContext && state.selectedPaper.analysis_status === "analyzing") {
    showToast("Analysis is still running");
    return;
  }
  if (!citationContext && state.selectedPaper.analysis_status !== "complete") {
    showToast("Analyze this paper before chatting");
    return;
  }

  state.chatMessages.push({ role: "user", content });
  renderChat();
  if (els.chatInput) {
    els.chatInput.value = "";
    resizeChatInput();
  }

  const pending = { role: "assistant", content: "Thinking..." };
  state.chatMessages.push(pending);
  renderChat();

  const payload = await requestJson(`/api/papers/${state.selectedPaper.id}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: state.chatMessages.filter((message) => message.content !== "Thinking..."),
      use_web: forceWeb || Boolean(els.webToggle?.checked),
      provider: selectedProvider(),
      api_key: requestApiKey() || null,
      citation_context: citationContext,
      figure_context: selectedFigureContext(),
      ...textModelRequestOptions(),
    }),
  });

  pending.content = payload.answer || "No answer returned.";
  if (payload.warnings?.length) {
    pending.content += `\n\n${payload.warnings.join("\n")}`;
  }
  if (citationContext && state.pendingCitationContext?.id === citationContext.id) {
    state.pendingCitationContext = null;
  }
  renderChat();
}



els.uploadForm?.addEventListener("submit", (event) => {
  startSelectedPaperAnalysis(event).catch((error) => {
    hideToast();
    showToast(error.message || String(error));
  });
});

els.previousHighlightButton?.addEventListener("click", () => stepHighlight(-1));
els.nextHighlightButton?.addEventListener("click", () => stepHighlight(1));

els.pdfInput?.addEventListener("change", () => {
  loadSelectedPaper().catch((error) => {
    hideToast();
    showToast(error.message || String(error));
  });
});

els.providerSelect?.addEventListener("change", () => {
  syncApiKeyInput();
  setModelOptions(state.settings || {});
  refreshProviderModels().catch((error) => showToast(error.message || String(error)));
});
els.apiKeyInput?.addEventListener("change", () => {
  refreshProviderModels().catch((error) => showToast(error.message || String(error)));
});
els.textModelInput?.addEventListener("change", () => {
  handleModelSelectChange(els.textModelInput, selectedTextModel());
  saveModelSettings();
});
els.visionModelInput?.addEventListener("change", () => {
  handleModelSelectChange(els.visionModelInput, selectedVisionModel());
  saveModelSettings();
});
document.addEventListener("click", (event) => {
  const effortOption = event.target.closest?.("[data-effort-option]");
  if (effortOption) {
    selectEffortOption(effortOption);
    return;
  }

  const effortButton = event.target.closest?.("[data-effort-button]");
  if (effortButton) {
    toggleEffortPicker(effortButton);
    return;
  }

  if (!event.target.closest?.(".effort-picker")) {
    closeEffortPickers();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeEffortPickers();
  }
  if (
    (event.metaKey || event.ctrlKey)
    && event.key.toLowerCase() === "c"
    && !event.altKey
    && !isEditableTarget(event.target)
    && copyActiveSelection()
  ) {
    event.preventDefault();
  }
});
[
  els.textEffortSelect,
  els.visionEffortSelect,
].forEach((control) => {
  control?.addEventListener("change", saveModelSettings);
});

els.pdfViewer?.addEventListener("pointerdown", startTextSelection);
window.addEventListener("pointermove", updateTextSelection);
window.addEventListener("pointerup", finishTextSelection);

els.selectionPopover?.addEventListener("mousedown", (event) => {
  event.stopPropagation();
});

els.copySelectionButton?.addEventListener("click", () => {
  copyActiveSelection();
});

els.explainSelectionButton?.addEventListener("click", () => {
  explainActiveSelection().catch((error) => {
    state.chatMessages.push({ role: "assistant", content: error.message || String(error) });
    renderChat();
  });
});

els.addSelectionHighlightButton?.addEventListener("click", () => {
  renderSelectionHighlightCategories();
  els.selectionHighlightForm?.classList.remove("hidden");
});

els.highlightCategorySelect?.addEventListener("change", syncSelectionHighlightForm);

els.selectionHighlightForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  addActiveSelectionHighlight().catch((error) => showToast(error.message || String(error)));
});

document.addEventListener("copy", (event) => {
  if (!isEditableTarget(event.target)) {
    copyActiveSelection(event);
  }
});

document.addEventListener("mousedown", (event) => {
  if (!els.selectionPopover?.contains(event.target) && !els.pdfViewer?.contains(event.target)) {
    hideSelectionPopover();
  }
  if (!els.citationPopover?.contains(event.target) && !event.target.closest?.(".citation-rect")) {
    hideCitationPopover();
  }
  if (!els.figurePopover?.contains(event.target) && !event.target.closest?.(".figure-rect")) {
    hideFigurePopover();
  }
  const highlightActivator = event.target.closest?.(
    ".highlight-rect, .highlight-card, #previous-highlight-button, #next-highlight-button",
  );
  if (!els.highlightPopover?.contains(event.target) && !highlightActivator) {
    highlightNavigationController.closePopover();
  }
});

els.citationPopover?.addEventListener("mousedown", (event) => {
  event.preventDefault();
});

els.highlightPopover?.addEventListener("mousedown", (event) => {
  event.preventDefault();
});

els.figurePopover?.addEventListener("mousedown", (event) => {
  event.preventDefault();
});

els.figurePopover?.addEventListener("pointerdown", startFigurePopoverDrag);
window.addEventListener("pointermove", moveFigurePopover);
window.addEventListener("pointerup", finishFigurePopoverDrag);

els.highlightPopover?.addEventListener("click", (event) => {
  if (event.target.closest?.("[data-close-highlight]")) {
    highlightNavigationController.closePopover();
    return;
  }
  if (event.target.closest?.("[data-add-highlight-figure]")) {
    const highlight = (state.selectedPaper?.overlay_highlights || state.selectedPaper?.highlights || [])[state.activeHighlightIndex];
    const figure = (state.selectedPaper?.figures || []).find((item) => item.id === highlight?.source?.visual_id);
    addFigureToChat(figure);
    hideHighlightPopover();
    return;
  }
  if (event.target.closest?.("[data-explain-highlight]")) {
    explainActiveHighlight().catch((error) => {
      state.chatMessages.push({ role: "assistant", content: error.message || String(error) });
      renderChat();
    });
    return;
  }
  if (event.target.closest?.("[data-remove-highlight]")) {
    removeActiveHighlight().catch((error) => showToast(error.message || String(error)));
  }
});

els.figurePopover?.addEventListener("click", (event) => {
  if (event.target.closest?.("[data-close-figure]")) {
    hideFigurePopover();
    return;
  }
  if (event.target.closest?.("[data-add-active-figure]")) {
    addFigureToChat(state.activeFigure);
    hideFigurePopover();
  }
});

els.citationPopover?.addEventListener("click", (event) => {
  const choiceButton = event.target.closest?.("[data-citation-choice]");
  if (choiceButton) {
    const choices = state.activeCitation?.grouped_citations?.length
      ? state.activeCitation.grouped_citations
      : [state.activeCitation];
    addCitationToChat(choices[Number(choiceButton.dataset.citationChoice)]);
    hideCitationPopover();
  }
});

els.refreshButton?.addEventListener("click", () => {
  refreshPapersFromCache().catch((error) => {
    hideToast();
    showToast(error.message || String(error));
  });
});

els.leftPanelToggle?.addEventListener("click", () => {
  state.leftPanelCollapsed = !state.leftPanelCollapsed;
  syncPanelToggles();
});

els.rightPanelToggle?.addEventListener("click", () => {
  state.rightPanelCollapsed = !state.rightPanelCollapsed;
  syncPanelToggles();
});

els.pdfZoomOutButton?.addEventListener("click", () => {
  setPdfZoom(state.pdfZoom - PDF_ZOOM_STEP).catch((error) => showToast(error.message || String(error)));
});

els.pdfZoomInButton?.addEventListener("click", () => {
  setPdfZoom(state.pdfZoom + PDF_ZOOM_STEP).catch((error) => showToast(error.message || String(error)));
});

els.chatForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const content = els.chatInput?.value.trim() || "";
  if (!content) {
    return;
  }
  sendChatMessage(content, false, state.pendingCitationContext).catch((error) => {
    state.chatMessages.push({ role: "assistant", content: error.message || String(error) });
    renderChat();
  });
});

els.chatResetButton?.addEventListener("click", resetChat);
els.chatInput?.addEventListener("input", resizeChatInput);
els.chatInput?.addEventListener("keydown", submitChatOnEnter);
syncPanelToggles();
resizeChatInput();

els.summaryResizeHandle?.addEventListener("pointerdown", startSummaryPanelResize);
els.summaryResizeHandle?.addEventListener("keydown", (event) => {
  if (!["ArrowUp", "ArrowDown"].includes(event.key)) {
    return;
  }

  event.preventDefault();
  const direction = event.key === "ArrowUp" ? -1 : 1;
  const panelTop = els.assistantPanel?.getBoundingClientRect().top || 0;
  setSummaryPanelSplit(panelTop + currentSummaryPanelHeight() + direction * 24);
});

els.chatResizeHandle?.addEventListener("pointerdown", startTakeawaysPanelResize);
els.chatResizeHandle?.addEventListener("keydown", (event) => {
  if (!["ArrowUp", "ArrowDown"].includes(event.key)) {
    return;
  }

  event.preventDefault();
  const direction = event.key === "ArrowUp" ? -1 : 1;
  const panelTop = els.takeawaysSection?.getBoundingClientRect().top || 0;
  setTakeawaysPanelSplit(panelTop + currentTakeawaysHeight() + direction * 24);
});

loadSettings()
  .then(() => loadPapers())
  .catch((error) => showToast(error.message || String(error)));
