/* Agent42 Dashboard — Loading Indicators and Error Feedback
 *
 * All DOM manipulation uses safe APIs (createElement, textContent).
 * No innerHTML usage anywhere in this module.
 */
"use strict";

// ---------------------------------------------------------------------------
// LoadingIndicator — Spinner for buttons and containers
// ---------------------------------------------------------------------------
window.LoadingIndicator = class LoadingIndicator {
  constructor(element) {
    this.element = element;
    this.spinner = document.createElement("div");
    this.spinner.className = "spinner spinner--sm";
    this.spinner.style.display = "none";
    this._originalText = "";
    this._timeout = null;
    this._timeoutWarning = null;
  }

  show(delayMs = 200) {
    // Only show spinner after threshold to avoid flicker on fast responses
    this._timeout = setTimeout(() => {
      if (this.element.tagName === "BUTTON") {
        this._originalText = this.element.textContent;
        this.element.classList.add("btn-loading");
        this.element.prepend(this.spinner);
      } else {
        this.element.appendChild(this.spinner);
      }
      this.spinner.style.display = "inline-block";
    }, delayMs);
  }

  hide() {
    if (this._timeout) {
      clearTimeout(this._timeout);
      this._timeout = null;
    }
    this.spinner.style.display = "none";
    if (this.element.tagName === "BUTTON") {
      this.element.classList.remove("btn-loading");
    }
    if (this.spinner.parentNode) {
      this.spinner.parentNode.removeChild(this.spinner);
    }
  }
};

// ---------------------------------------------------------------------------
// ProgressIndicator — Multi-step progress bar
// ---------------------------------------------------------------------------
window.ProgressIndicator = class ProgressIndicator {
  constructor(container) {
    this.container = container;

    // Label row
    this.labelRow = document.createElement("div");
    this.labelRow.className = "progress-label";
    this.labelText = document.createElement("span");
    this.labelPercent = document.createElement("span");
    this.labelRow.appendChild(this.labelText);
    this.labelRow.appendChild(this.labelPercent);

    // Bar
    this.progressContainer = document.createElement("div");
    this.progressContainer.className = "progress-container";
    this.bar = document.createElement("div");
    this.bar.className = "progress-bar";
    this.bar.style.width = "0%";
    this.progressContainer.appendChild(this.bar);

    this.container.appendChild(this.labelRow);
    this.container.appendChild(this.progressContainer);
    this._visible = false;
  }

  show() {
    this.container.style.display = "";
    this._visible = true;
  }

  hide() {
    this.container.style.display = "none";
    this._visible = false;
  }

  update(current, total, label) {
    const pct = total > 0 ? Math.round((current / total) * 100) : 0;
    this.bar.style.width = pct + "%";
    this.labelText.textContent = label || "";
    this.labelPercent.textContent = pct + "%";

    // Color coding
    this.bar.className = "progress-bar";
    if (pct >= 100) this.bar.classList.add("progress-bar--success");
    else if (pct >= 75) this.bar.classList.add("progress-bar--warning");
  }
};

// ---------------------------------------------------------------------------
// TypingIndicator — Three-dot animation for chat
// ---------------------------------------------------------------------------
window.TypingIndicator = class TypingIndicator {
  constructor() {
    this.element = document.createElement("div");
    this.element.className = "typing-indicator";
    this.element.style.display = "none";
    for (let i = 0; i < 3; i++) {
      this.element.appendChild(document.createElement("span"));
    }
  }

  show(container) {
    if (container && !this.element.parentNode) {
      container.appendChild(this.element);
    }
    this.element.style.display = "inline-flex";
  }

  hide() {
    this.element.style.display = "none";
    if (this.element.parentNode) {
      this.element.parentNode.removeChild(this.element);
    }
  }
};

// ---------------------------------------------------------------------------
// showError — Structured error toast with action guidance
// ---------------------------------------------------------------------------
window.showError = function showError(code, message, action) {
  const container = document.getElementById("toasts");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = "toast toast-error";

  const msgEl = document.createElement("span");
  msgEl.textContent = message || "An error occurred";
  toast.appendChild(msgEl);

  if (action) {
    const actionEl = document.createElement("span");
    actionEl.className = "toast-action";
    actionEl.textContent = action;
    toast.appendChild(actionEl);
  }

  container.appendChild(toast);

  // Auto-dismiss after 5 seconds
  setTimeout(() => {
    if (toast.parentNode) toast.remove();
  }, 5000);
};

// ---------------------------------------------------------------------------
// showTimeoutWarning — Warning banner for slow requests
// ---------------------------------------------------------------------------
window.showTimeoutWarning = function showTimeoutWarning(container, onCancel) {
  // Remove any existing warning first
  const existing = container.querySelector(".timeout-warning");
  if (existing) existing.remove();

  const warning = document.createElement("div");
  warning.className = "timeout-warning";

  const text = document.createElement("span");
  text.textContent = "This is taking longer than expected...";
  warning.appendChild(text);

  if (onCancel) {
    const btn = document.createElement("button");
    btn.textContent = "Cancel";
    btn.addEventListener("click", () => {
      warning.remove();
      onCancel();
    });
    warning.appendChild(btn);
  }

  container.appendChild(warning);
  return warning;
};

// ---------------------------------------------------------------------------
// fetchWithTimeout — Wrapper for fetch with timeout warning at 25s
// ---------------------------------------------------------------------------
window.fetchWithTimeout = async function fetchWithTimeout(url, opts = {}, timeoutMs = 30000, warningMs = 25000) {
  const controller = new AbortController();
  const signal = controller.signal;

  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  let warningEl = null;

  const warningId = setTimeout(() => {
    // Show timeout warning at 25s threshold
    const toasts = document.getElementById("toasts");
    if (toasts) {
      warningEl = document.createElement("div");
      warningEl.className = "toast toast-info";
      warningEl.textContent = "Request is taking a while. Hang tight...";
      toasts.appendChild(warningEl);
    }
  }, warningMs);

  try {
    const res = await fetch(url, { ...opts, signal });
    return res;
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error("Request timed out after " + Math.round(timeoutMs / 1000) + "s");
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
    clearTimeout(warningId);
    if (warningEl && warningEl.parentNode) warningEl.remove();
  }
};
