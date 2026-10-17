"use strict";
const $ = (selector) => document.querySelector(selector),
  $$ = (selector) => Array.from(document.querySelectorAll(selector));
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const paths = {
  overview: "M3 10 10 4l7 6v10h-5v-6H8v6H3Z",
  cameras: "M3 7h4l2-3h5l2 3h3v13H3ZM15 13a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  calibration: "M5 3v4H2v10h3v4M15 3v4h3v10h-3v4M5 12h10M10 7v10",
  network: "M6 2v5h8V2M10 7v6M3 13h14v6H3M10 19v3",
  system: "M3 4h15v5H3ZM3 14h15v5H3ZM6 6.5h1M6 16.5h1M13 6.5h2M13 16.5h2",
  docs: "M10 5C7 3 4 3 2 4v15c3-1 5-1 8 1 3-2 5-2 8-1V4c-3-1-5-1-8 1Zm0 0v15",
  Auto: "M2 3h17v12H2ZM10 15v5M6 20h8",
  Light:
    "M10 6a4 4 0 1 1 0 8 4 4 0 0 1 0-8M10 1v2M10 17v2M1 10h2M17 10h2M3 3l2 2M15 15l2 2M3 17l2-2M15 5l2-2",
  Dark: "M18 13A8 8 0 0 1 7 2 8 8 0 1 0 18 13",
  undo: "M7 4 3 8l4 4M3 8h8a6 6 0 0 1 6 6",
  redo: "m13 4 4 4-4 4M17 8H9a6 6 0 0 0-6 6",
};
const icon = (name) =>
  `<svg class="icon" viewBox="0 0 22 24" aria-hidden="true"><path d="${paths[name] || paths.cameras}"/></svg>`;
const fmt = (value, digits = 1) =>
  Number.isFinite(value) ? value.toFixed(digits) : "—";
const age = (value) =>
  !Number.isFinite(value)
    ? "— ms"
    : value < 1
      ? `${Math.round(value * 1000)} ms`
      : `${value.toFixed(1)} s`;
const date = (value) =>
  value && !Number.isNaN(Date.parse(value))
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "Time unavailable";
let state = {
    cameras: [],
    names: [],
    revision: "",
    lock_reason: "Robot state unknown · locked",
    clock: {},
    release: {},
    calibration: { cameras: {} },
  },
  session = null,
  serviceError = "",
  routeKey = "",
  pageUpdate = () => {},
  viewer = null,
  tuner = null,
  docs = null;
function updateHTML(element, html) {
  if (element.dataset.rendered !== html) {
    element.dataset.rendered = html;
    element.innerHTML = html;
  }
}
let navHTML = "";
const historySelections = new Map();
const previews = new Map(),
  selectedCalibration = new Set(),
  appliedResults = new Set();
function camera(id) {
  return state.cameras.find((c) => c.identity === id);
}
function currentRoute() {
  const parts = location.hash.slice(1).split("/").map(decodeURIComponent);
  return { page: parts[0] || "overview", id: parts[1], tab: parts[2] };
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}
async function mutation(operation, payload) {
  if (!session) throw new Error("Browser session unavailable; reconnect");
  const request_id = Array.from(
    crypto.getRandomValues(new Uint8Array(16)),
    (v) => v.toString(16).padStart(2, "0"),
  ).join("");
  const result = await api("/api/operations", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Spot-CSRF": session.csrf,
    },
    body: JSON.stringify({ operation, payload, request_id }),
  });
  for (let n = 0; n < 120; n++) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    const job = await api("/api/jobs/" + result.job_id);
    if (job.state === "rejected") throw new Error(job.error);
    if (job.state === "applied") {
      state = await api("/api/status");
      render();
      return job;
    }
  }
  throw new Error(
    "Acknowledgement pending; read current values before retrying",
  );
}
function announce(message) {
  $("#announcement").textContent = message;
}
function showError(error, target = "#page-feedback") {
  const element = $(target);
  if (element) element.textContent = error.message;
  announce(error.message);
}
function nav() {
  const route = currentRoute();
  const entries = [
    ["overview", "Overview"],
    ["cameras", "Cameras"],
  ];
  let html = "";
  for (const [path, label] of entries)
    html += `<a href="#${path}" class="${route.page === path ? "active" : ""}" title="${label}" aria-label="${label}">${icon(path)}<span class="nav-label">${label}</span></a>`;
  for (const c of state.cameras) {
    const warnings = [];
    if (c.health !== "Disabled" && !c.logical_name)
      warnings.push("Choose a code-defined name");
    if (c.health !== "Disabled" && c.logical_name && !c.calibrated)
      warnings.push("Calibration required");
    if (c.health !== "Disabled" && !c.connected)
      warnings.push(c.present ? c.fault || "Waiting for image" : "Disconnected");
    html += `<a class="camera-entry ${route.page === "camera" && route.id === c.identity ? "active" : ""}" href="#camera/${encodeURIComponent(c.identity)}" aria-label="${escapeHTML(c.name + (warnings.length ? ": " + warnings.join("; ") : ""))}"><span>${escapeHTML(c.name)}</span>${warnings.map((w) => `<span class="warning" role="img" aria-label="${escapeHTML(w)}" title="${escapeHTML(w)}">⚠</span>`).join("")}</a>`;
  }
  for (const [path, label] of [
    ["calibration", "Calibration"],
    ["network", "Network"],
    ["system", "System"],
    ["docs", "Docs"],
  ])
    html += `<a href="#${path}" class="${path === "calibration" ? "section-gap " : ""}${route.page === path ? "active" : ""}" title="${label}" aria-label="${label}">${icon(path)}<span class="nav-label">${label}</span></a>`;
  if (navHTML !== html) {
    $("#nav").innerHTML = html;
    navHTML = html;
  }
  const deployment = state.release.deployment?.last_successful_deployment;
  $("#updated").textContent = deployment?.completed_at
    ? `Updated ${date(deployment.completed_at)}`
    : "Time unavailable";
  $("#release-id").textContent =
    (state.release.release_id || "Release unavailable") +
    (state.release.deployment?.rollback ? " · rollback" : "");
}
function theme() {
  const trigger = $("#theme-trigger"),
    menu = $("#theme-menu");
  function update() {
    const preference = SpotTheme.get();
    trigger.innerHTML = icon(preference);
    trigger.setAttribute("aria-label", "Theme: " + preference);
    trigger.title = "Theme: " + preference;
    menu.innerHTML = ["Auto", "Light", "Dark"]
      .map(
        (name) =>
          `<button class="icon-button" role="menuitemradio" aria-checked="${name === preference}" aria-label="${name}" title="${name}" data-theme-choice="${name}">${icon(name)}</button>`,
      )
      .join("");
    for (const button of menu.children)
      button.onclick = () => {
        SpotTheme.set(button.dataset.themeChoice);
        menu.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
        trigger.focus();
      };
  }
  trigger.onclick = () => {
    menu.hidden = !menu.hidden;
    trigger.setAttribute("aria-expanded", String(!menu.hidden));
    if (!menu.hidden) menu.querySelector("[aria-checked=true]").focus();
  };
  menu.onkeydown = (event) => {
    if (event.key === "Escape") {
      menu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      trigger.focus();
    }
    if (
      ["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(event.key)
    ) {
      event.preventDefault();
      const buttons = Array.from(menu.children),
        index = buttons.indexOf(document.activeElement);
      buttons[
        (index + (["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : 2)) % 3
      ].focus();
    }
  };
  document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(".theme-area")) {
      menu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    }
  });
  addEventListener("spot-theme", () => {
    update();
    viewer?.draw();
  });
  update();
}
function feed(id) {
  return `<div class="feed" data-feed="${escapeHTML(id)}"><canvas width="960" height="540" aria-label="Camera image"></canvas><span class="image-state">Waiting for image</span></div>`;
}
function warningLink(c) {
  if (c.health === "Disabled")
    return '<span class="calibrated">Disabled in code</span>';
  return c.calibrated
    ? '<span class="calibrated good">✓ calibrated</span>'
    : `<a class="calibrated warning" href="#calibration">⚠ Calibration required</a>`;
}
function tabs(id, tab) {
  return `<div class="tabs"><a href="#camera/${encodeURIComponent(id)}" class="${tab !== "geometry" ? "active" : ""}">Camera</a><a href="#camera/${encodeURIComponent(id)}/geometry" class="${tab === "geometry" ? "active" : ""}">Geometry</a></div>`;
}
function historyMarkup() {
  return `<span class="history-buttons"><button id="undo" class="icon-button" aria-label="Undo" title="No acknowledged history" disabled>${icon("undo")}</button><button id="redo" class="icon-button" aria-label="Redo" title="No acknowledged history" disabled>${icon("redo")}</button></span>`;
}
function overview(page) {
  $("#page").innerHTML =
    `<h1>${page === "cameras" ? "Cameras" : "Overview"}</h1><div id="tiles" class="overview-grid"></div><p id="page-feedback" class="feedback"></p>`;
  let inventory = null;
  pageUpdate = () => {
    const signature = state.cameras.map((c) => c.identity).join();
    if (signature !== inventory) {
      inventory = signature;
      $("#tiles").innerHTML = state.cameras.length
        ? state.cameras
            .map(
              (c) =>
                `<a class="panel tile" href="#camera/${encodeURIComponent(c.identity)}" data-tile="${escapeHTML(c.identity)}"><header><strong>${escapeHTML(c.name)}</strong><span class="calibrated"></span></header>${feed(c.identity)}<div class="metrics"><span class="fps" title="Measured capture FPS; detection and preview rates are separate">— FPS</span><span class="tags">— tags</span><span class="age">— ms</span></div></a>`,
            )
            .join("")
        : '<div class="panel empty"><h2>No cameras discovered</h2><p>Connect a powered USB camera. Discovery continues automatically.</p><a href="#docs/connect">Connection guide</a></div>';
    }
    for (const c of state.cameras) {
      const tile = $(`[data-tile="${c.identity}"]`);
      if (!tile) continue;
      tile.querySelector("strong").textContent = c.name;
      tile.querySelector(".calibrated").textContent =
        c.health === "Disabled"
          ? "Disabled in code"
          : !c.logical_name
            ? "⚠ Choose camera name"
            : c.calibrated
              ? "✓ calibrated"
              : "⚠ Calibration required";
      tile.querySelector(".calibrated").className =
        "calibrated " + (c.calibrated ? "good" : "warning");
      const preview = previews.get(c.identity),
        captureFresh = c.connected && c.age_s != null && c.age_s < 0.5,
        fresh =
          c.connected &&
          c.metrics?.detect_age_s != null &&
          c.metrics.detect_age_s < 0.5;
      tile.querySelector(".fps").textContent =
        captureFresh && c.metrics?.captured && Number.isFinite(c.metrics.fps_capture)
          ? `${Math.round(c.metrics.fps_capture)} FPS`
          : "— FPS";
      tile.querySelector(".tags").textContent =
        preview?.data && !preview.data.stale && fresh
          ? preview.data.processed
            ? `${preview.data.tags.length} tags`
            : "— tags"
          : "— tags";
      tile.querySelector(".age").textContent = age(c.age_s);
    }
    $("#page-feedback").textContent = serviceError;
  };
}
function cameraSelector(id) {
  return `<select class="camera-selector" aria-label="Select camera">${state.cameras.map((c) => `<option value="${escapeHTML(c.identity)}" ${c.identity === id ? "selected" : ""}>${escapeHTML(c.name)}</option>`).join("")}</select>`;
}
async function beginCameraSetup(c) {
  await mutation("device/setup", {identity: c.identity, revision: state.revision});
  routeKey = "";
  render();
}
function namePage(c) {
  $("#page").innerHTML =
    `<h1 id="camera-title">${escapeHTML(c.name)}</h1>${cameraSelector(c.identity)}<div class="name-layout">${feed(c.identity)}<section class="panel"><h2>Camera name</h2><p class="warning">⚠ Not configured in code</p><label for="camera-name">Name</label><select id="camera-name"></select><label class="spaced"><input type="checkbox" id="preview-confirmed"> This preview matches the physical camera</label><button id="rename" class="primary">Rename</button><hr><p>Use this camera without a robot profile for tuning and calibration.</p><button id="standalone-camera">Open standalone camera setup</button><p id="naming-lock" class="lock"></p><p id="page-feedback" class="feedback"></p><a href="#docs/name">Configure camera names in robot code</a></section></div>`;
  $("#standalone-camera").onclick = async () => {
    try { await beginCameraSetup(c); } catch (error) { showError(error); }
  };
  $("#preview-confirmed").onchange = () => pageUpdate();
  $("#rename").onclick = async () => {
    const button = $("#rename");
    button.disabled = true;
    try {
      await mutation("rename", {
        identity: c.identity,
        name: $("#camera-name").value,
        revision: state.revision,
      });
      routeKey = "";
      render();
      announce("Camera renamed");
    } catch (error) {
      showError(error);
    } finally {
      button.disabled = false;
    }
  };
  pageUpdate = () => {
    const latest = camera(c.identity);
    if (latest?.logical_name) {
      routeKey = "";
      render();
      return;
    }
    $("#camera-title").textContent = latest?.name || c.name;
    const available = state.names.filter(
      (name) =>
        !state.cameras.some(
          (cam) => cam.logical_name === name && cam.identity !== c.identity,
        ),
    );
    const select = $("#camera-name"),
      signature = available.join();
    if (select.dataset.signature !== signature) {
      select.dataset.signature = signature;
      select.innerHTML = available.length
        ? available
            .map((name) => `<option>${escapeHTML(name)}</option>`)
            .join("")
        : '<option value="">No names available in robot code</option>';
    }
    $("#naming-lock").textContent =
      state.lock_reason ||
      (state.fresh
        ? "Confirm this preview matches the physical camera"
        : "Cached code names · standalone setup");
    $("#rename").disabled = Boolean(
      state.lock_reason ||
      !latest?.connected ||
      !available.length ||
      !$("#preview-confirmed").checked,
    );
  };
}
function controlMarkup(control) {
  const name = escapeHTML(control.name),
    menu = control.options?.length;
  return `<div class="control" data-control="${name}"><div class="control-heading"><label for="control-${name}">${escapeHTML(control.label)}</label><output></output></div>${menu ? `<select id="control-${name}">${control.options.map((option) => `<option value="${option.value * control.factor}">${escapeHTML(option.label)}</option>`).join("")}</select>` : `<input id="control-${name}" type="range" min="${control.min}" max="${control.max}" step="${control.step}" value="${control.value}" aria-label="${escapeHTML(control.label)}"><div class="range-labels"><span>${control.min} ${escapeHTML(control.unit)}</span><span>${control.max} ${escapeHTML(control.unit)}</span></div>`}<div class="readback"></div><small class="capability-lock"></small></div>`;
}
function detailPage(c) {
  const preferred = [
    "exposure_time_absolute",
    "exposure_absolute",
    "gain",
    "brightness",
  ];
  const primary = (c.controls || [])
    .filter((v) => preferred.includes(v.name))
    .sort((a, b) => preferred.indexOf(a.name) - preferred.indexOf(b.name));
  const advanced = (c.controls || []).filter(
    (v) => !preferred.includes(v.name),
  );
  $("#page").innerHTML =
    `${!c.logical_name ? '<div class="panel warning"><strong>Not configured with the robot.</strong> Standalone tuning and calibration; the 3D camera is at (0, 0, 0), with zero rotation. <button id="standalone-enable">Enable standalone setup</button></div>' : ""}<div class="page-heading"><h1 id="camera-title">${escapeHTML(c.name)}</h1><span id="calibrated-state">${warningLink(c)}</span></div>${cameraSelector(c.identity)}${tabs(c.identity, "camera")}<div class="camera-layout"><section class="panel config-panel"><div class="panel-heading"><h2>Config</h2>${historyMarkup()}</div><p id="config-lock" class="lock"></p>${primary.map(controlMarkup).join("")}<div class="mode-control"><label for="optical-mode">Capture resolution / rate</label><select id="optical-mode"></select></div><div id="control-feedback" class="feedback"></div><button class="reset" id="reset-defaults">Reset to code defaults</button><details><summary>Advanced</summary>${advanced.map(controlMarkup).join("")}<button id="copy-code" class="spaced">Copy settings as code</button><pre id="code-copy" hidden></pre><label class="spaced" for="replacement-identity">Replacement camera</label><select id="replacement-identity"></select><label class="spaced"><input type="checkbox" id="replacement-confirmed"> I confirmed the replacement feed</label><button id="replace-camera" class="spaced">Replace camera</button></details><button id="reconcile" class="spaced" hidden>Reconcile current values</button><p id="page-feedback" class="feedback"></p><a href="#docs/tuning">Tuning and history</a></section><div><div>${feed(c.identity)}<div class="feed-controls"><label><input id="outlines" type="checkbox" checked>Show detection outlines</label><button id="pause-image">Pause image</button><small id="frame-info">Waiting for frame</small></div></div><div class="detail-bottom"><section class="panel"><h2>Detections</h2><div class="table-scroll"><table><thead><tr><th>ID</th><th>Range</th><th>Error</th><th>Used</th></tr></thead><tbody id="detections"></tbody></table></div><div id="robot-decision">Robot decision unavailable</div><details class="spaced"><summary>Solver candidates</summary><pre id="candidate-details"></pre></details></section><div class="viewer"><canvas id="geometry-canvas" width="700" height="350" tabindex="0" aria-label="3D camera and observed tags. Arrow keys orbit; plus/minus zoom"></canvas><button class="reset-view" id="reset-view">Reset view</button><a class="frame-label" href="#camera/${encodeURIComponent(c.identity)}/geometry">Geometry · WPILib NWU</a></div></div></div></div>`;
  if (!c.logical_name) {
    $("#standalone-enable").onclick = async () => {
      try { await beginCameraSetup(c); } catch (error) { showError(error); }
    };
    $("#reset-defaults").textContent = "Reset setup values";
  }
  const allowed = () =>
    Object.fromEntries(
      (camera(c.identity)?.controls || [])
        .filter((ctrl) => ctrl.allowed)
        .map((ctrl) => [ctrl.name, ctrl.value]),
    );
  const send = async (values, revision) => {
    const result = await mutation(c.logical_name ? "tune" : "device/tune", {
      ...(c.logical_name ? {name: c.logical_name} : {identity: c.identity}),
      values,
      revision,
    });
    const latest = allowed();
    return {
      revision: result.revision,
      values: Object.fromEntries(
        Object.keys(latest).map((name) => [
          name,
          result.controls?.[name] ?? latest[name],
        ]),
      ),
    };
  };
  const activeTuner = new SpotUI.LiveTuner(
    allowed(),
    state.revision,
    send,
    () => updateControls(),
  );
  tuner = activeTuner;
  for (const root of $$("[data-control]")) {
    const input = root.querySelector("input,select"),
      name = root.dataset.control;
    input.onpointerdown = () => activeTuner.begin();
    input.oninput = () => {
      activeTuner.request(name, Number(input.value), false);
    };
    input.onchange = () => activeTuner.request(name, Number(input.value), true);
    input.onpointerup = input.onpointercancel = () => activeTuner.end();
    input.onkeydown = () => activeTuner.begin();
    input.onkeyup = input.onblur = () => activeTuner.end();
  }
  function updateControls() {
    if (!$("#config-lock") || tuner !== activeTuner) return;
    const latest = camera(c.identity) || c;
    $("#config-lock").textContent = state.lock_reason || "";
    for (const ctrl of latest.controls || []) {
      const root = $(`[data-control="${CSS.escape(ctrl.name)}"]`);
      if (!root) continue;
      const input = root.querySelector("input,select");
      input.disabled = Boolean(
        state.lock_reason ||
        !ctrl.allowed ||
        !latest.connected ||
        activeTuner.history.conflict,
      );
      input.min = ctrl.min;
      input.max = ctrl.max;
      input.step = ctrl.step;
      if (document.activeElement !== input && !activeTuner.gesture)
        input.value = ctrl.value;
      root.querySelector("output").textContent =
        `${activeTuner.gesture ? (activeTuner.requested[ctrl.name] ?? ctrl.value) : ctrl.value} ${ctrl.unit || ""}`;
      root.querySelector(".readback").textContent =
        activeTuner.inFlight || activeTuner.pending
          ? `Requested · readback ${ctrl.value} ${ctrl.unit || ""}`
          : `Readback ${ctrl.value} ${ctrl.unit || ""}`;
      root.querySelector(".capability-lock").textContent = ctrl.allowed
        ? ctrl.range_reason || ""
        : ctrl.reason || "Unavailable";
      input.title = ctrl.hardware_max != null
        ? `${ctrl.range_reason}. Driver maximum: ${ctrl.hardware_max} ${ctrl.unit}.`
        : "";
    }
    $("#control-feedback").textContent =
      activeTuner.error ||
      (activeTuner.inFlight || activeTuner.pending
        ? "Pending device acknowledgement"
        : "");
    $("#reconcile").hidden = !activeTuner.history.conflict;
    for (const direction of ["undo", "redo"]) {
      const button = $("#" + direction),
        stack =
          direction === "undo"
            ? activeTuner.history.undoStack
            : activeTuner.history.redoStack;
      button.disabled = Boolean(
        !stack.length ||
        state.lock_reason ||
        activeTuner.inFlight ||
        activeTuner.pending ||
        activeTuner.gesture ||
        activeTuner.history.conflict,
      );
      button.title =
        state.lock_reason ||
        (activeTuner.history.conflict
          ? "Reconcile current values"
          : !stack.length
            ? "No acknowledged history"
            : activeTuner.inFlight || activeTuner.pending
              ? "Operation pending"
              : direction === "undo"
                ? "Undo last acknowledged change"
                : "Redo acknowledged change");
    }
    $("#reset-defaults").disabled = Boolean(
      state.lock_reason ||
      !Object.keys(allowed()).length ||
      activeTuner.inFlight ||
      activeTuner.history.conflict,
    );
  }
  $("#reconcile").onclick = async () => {
    state = await api("/api/status");
    activeTuner.reconcile(allowed(), state.revision);
    updateControls();
  };
  for (const direction of ["undo", "redo"])
    $("#" + direction).onclick = async () => {
      try {
        await activeTuner.history.apply(direction, async (values, revision) => {
          const result = await send(values, revision);
          activeTuner.revision = result.revision;
          activeTuner.values = { ...result.values };
          activeTuner.requested = { ...result.values };
          return result;
        });
      } catch (error) {
        activeTuner.error = error.message;
        if (/conflict/i.test(error.message))
          activeTuner.history.conflict = true;
      }
      updateControls();
    };
  $("#reset-defaults").onclick = async () => {
    const before = allowed();
    activeTuner.inFlight = true;
    activeTuner.history.pending = true;
    updateControls();
    try {
      const result = await mutation(c.logical_name ? "tune" : "device/tune", {
        ...(c.logical_name ? {name: c.logical_name} : {identity: c.identity}),
        reset: true,
        revision: state.revision,
      });
      const after = allowed();
      activeTuner.revision = result.revision;
      activeTuner.values = { ...after };
      activeTuner.requested = { ...after };
      activeTuner.history.record(before, after, result.revision);
    } catch (error) {
      activeTuner.error = error.message;
    } finally {
      activeTuner.inFlight = false;
      activeTuner.history.pending = false;
      updateControls();
    }
  };
  $("#optical-mode").onchange = async () => {
    try {
      await mutation(c.logical_name ? "mode" : "device/mode", {
        ...(c.logical_name ? {name: c.logical_name} : {identity: c.identity}),
        mode_id: $("#optical-mode").value,
        revision: state.revision,
      });
      routeKey = "";
      render();
    } catch (error) {
      showError(error);
    }
  };
  $("#copy-code").onclick = async () => {
    const value = (camera(c.identity)?.controls || [])
      .map(
        (ctrl) =>
          `VisionProfiles.${ctrl.allowed ? "tuning" : "pinned"}("${ctrl.name}", ${ctrl.value}${ctrl.allowed ? "" : ", " + Boolean(ctrl.required)})`,
      )
      .join(",\n");
    const output = $("#code-copy");
    output.hidden = false;
    output.textContent = value;
    try {
      await navigator.clipboard.writeText(value);
      announce("Settings copied as code");
    } catch {
      announce("Code displayed for copying");
    }
  };
  $("#replace-camera").onclick = async () => {
    try {
      if (!$("#replacement-confirmed").checked)
        throw new Error(
          "Identify the replacement feed before replacing this camera",
        );
      await mutation("replace", {
        name: c.logical_name,
        identity: $("#replacement-identity").value,
        revision: state.revision,
      });
      announce("Physical camera calibration invalidated");
    } catch (error) {
      showError(error);
    }
  };
  $("#outlines").onchange = () => drawFeeds();
  $("#pause-image").onclick = () => {
    const preview = previews.get(c.identity);
    if (!preview) return;
    preview.paused = !preview.paused;
    if (preview.paused)
      preview.held = {
        ...preview.data,
        bitmap: preview.bitmap,
        geometry: camera(c.identity)?.geometry,
        field: state.field,
        heldAt: performance.now(),
      };
    else {
      preview.held = null;
      preview.bitmap?.close();
      preview.bitmap = null;
      preview.data = null;
    }
    $("#pause-image").textContent = preview.paused
      ? "Resume image"
      : "Pause image";
    drawFeeds();
  };
  lazyViewer(c.identity, false);
  pageUpdate = () => {
    const latest = camera(c.identity) || c;
    $("#camera-title").textContent = latest.name;
    $("#pause-image").textContent = previews.get(c.identity)?.paused
      ? "Resume image"
      : "Pause image";
    $("#calibrated-state").innerHTML = warningLink(latest);
    if (activeTuner) {
      activeTuner.observe(allowed(), state.revision);
      updateControls();
    }
    const mode = $("#optical-mode");
    const signature = JSON.stringify(latest.allowed_modes);
    if (mode.dataset.signature !== signature) {
      mode.dataset.signature = signature;
      mode.innerHTML = (latest.allowed_modes || [])
        .map(
          (m) =>
            `<option value="${escapeHTML(m.id)}" ${m.supported ? "" : "disabled"}>${m.width} × ${m.height} · ${m.fps} FPS · ${escapeHTML(m.pixel_format)}${m.supported ? "" : " · unsupported"}</option>`,
        )
        .join("");
    }
    mode.value = latest.mode_id || "";
    mode.disabled = Boolean(
      state.lock_reason || !latest.connected || activeTuner?.inFlight,
    );
    const replacement = $("#replacement-identity"),
      replacementSignature = state.cameras
        .filter(
          (cam) =>
            cam.connected && (!cam.logical_name || cam.identity === c.identity),
        )
        .map((cam) => cam.identity)
        .join();
    if (replacement.dataset.signature !== replacementSignature) {
      replacement.dataset.signature = replacementSignature;
      replacement.innerHTML = state.cameras
        .filter(
          (cam) =>
            cam.connected && (!cam.logical_name || cam.identity === c.identity),
        )
        .map(
          (cam) =>
            `<option value="${cam.identity}">${escapeHTML(cam.name)} · ${escapeHTML(cam.display_id || "")}</option>`,
        )
        .join("");
    }
    $("#replace-camera").disabled = Boolean(
      !latest.logical_name || state.lock_reason || !replacement.options.length,
    );
    updateDetections(c.identity);
    viewer?.draw();
  };
}
function updateDetections(id) {
  const preview = previews.get(id),
    data = preview?.paused ? preview.held : preview?.data,
    fresh =
      data &&
      data.processed &&
      !data.stale &&
      (preview?.paused ||
        (camera(id)?.age_s < 0.5 &&
          data.generation === state.applied_generation));
  const tags = fresh ? data.tags || [] : [],
    candidates = fresh ? data.candidates || [] : [];
  const best = candidates.reduce(
    (a, b) => (!a || b.error_px < a.error_px ? b : a),
    null,
  );
  if ($("#detections"))
    $("#detections").innerHTML = tags.length
      ? tags
          .map(
            (tag) =>
              `<tr><td>${tag.id}</td><td>${tag.distance_m != null ? fmt(tag.distance_m) + " m" : "—"}</td><td>${tag.error_px != null ? fmt(tag.error_px, 2) + " px" : "—"}</td><td title="${escapeHTML(tag.reason)}">${tag.used ? "✓" : "—"}</td></tr>`,
          )
          .join("")
      : '<tr><td colspan="4">' +
        (fresh
          ? "No tags in this frame"
          : "Waiting for current detection frame") +
        "</td></tr>";
  if ($("#candidate-details"))
    $("#candidate-details").textContent = JSON.stringify(candidates, null, 2);
  const decision = state.robot_decisions?.[camera(id)?.logical_name];
  if ($("#robot-decision"))
    $("#robot-decision").textContent =
      decision &&
      decision.capture_epoch === data?.capture_epoch &&
      decision.sequence === data?.sequence
        ? `Robot: ${decision.state} · fusion ${decision.fusion_enabled ? "enabled" : "off"} · frame ${decision.fused ? "fused" : "not fused"}`
        : "Robot decision unavailable for this frame";
}
async function lazyViewer(id, geometry) {
  if (!window.SpotViewer) {
    await new Promise((resolve, reject) => {
      const existing = $("script[data-viewer]");
      if (existing) {
        existing.addEventListener("load", resolve, { once: true });
        existing.addEventListener("error", reject, { once: true });
        return;
      }
      const script = document.createElement("script");
      script.src = "/viewer.js";
      script.dataset.viewer = "true";
      script.onload = resolve;
      script.onerror = reject;
      document.head.append(script);
    }).catch(() => {});
  }
  if (
    !window.SpotViewer ||
    !$("#geometry-canvas") ||
    currentRoute().id !== id ||
    (currentRoute().tab === "geometry") !== geometry
  )
    return;
  viewer?.destroy();
  viewer = new SpotViewer($("#geometry-canvas"), () => {
    const c = camera(id),
      preview = previews.get(id);
    return {
      camera: c,
      geometry: geometry
        ? geometryPreview(c)
        : preview?.paused
          ? preview.held?.geometry
          : c?.geometry,
      field: preview?.paused ? preview.held?.field : state.field,
      data: preview?.paused ? preview.held : preview?.data,
      inspection: geometry,
    };
  });
  $("#reset-view").onclick = () => viewer.reset();
  viewer.draw();
}
let geometryNumbers = [];
function geometryPreview(c) {
  if (!c?.geometry) return null;
  const values =
    geometryNumbers.length === 6
      ? geometryNumbers.map((edit) =>
          Number.isFinite(edit.previewValue) ? edit.previewValue : edit.ack,
        )
      : [
          ...c.geometry.translation,
          ...SpotViewer.angles(c.geometry.quaternion),
        ];
  return {
    translation: values.slice(0, 3),
    quaternion: SpotViewer.quaternion(values[3], values[4], values[5]),
  };
}
function geometryPage(c) {
  $("#page").innerHTML =
    `<h1>${escapeHTML(c.name)}</h1>${cameraSelector(c.identity)}${tabs(c.identity, "geometry")}<div class="camera-layout"><section class="panel geometry-panel"><div class="panel-heading"><h2>Geometry</h2>${historyMarkup()}</div><p class="lock">${c.logical_name ? "Transform pinned by robot code" : "Not configured with the robot · local origin only"}</p><label class="inspection"><input id="inspection-preview" type="checkbox"> Inspection preview</label><div id="geometry-fields"></div><button id="geometry-reset" class="reset">Reset to code defaults</button><p class="feedback" id="page-feedback"></p><small>0.01 m / 1°. Shift: coarse. Alt: fine.</small><p><a href="#docs/geometry">Measuring camera geometry</a></p></section><div><div class="viewer geometry-view"><canvas id="geometry-canvas" width="1000" height="720" tabindex="0" aria-label="Robot geometry in WPILib NWU. Arrow keys orbit; plus/minus zoom"></canvas><button id="reset-view" class="reset-view">Reset view</button><span class="frame-label">Inspection · production geometry from robot code</span></div><div class="transform-readout" id="transform-readout"></div></div></div>`;
  geometryNumbers = [];
  lazyViewer(c.identity, true).then(() => {
    if (!$("#geometry-fields")) return;
    const angles = c.geometry
        ? SpotViewer.angles(c.geometry.quaternion)
        : [null, null, null],
      values = c.geometry
        ? [...c.geometry.translation, ...angles]
        : [null, null, null, null, null, null];
    $("#geometry-fields").innerHTML = ["X", "Y", "Z", "Yaw", "Pitch", "Roll"]
      .map(
        (name, index) =>
          `<div class="number-field"><label for="geometry-${index}">${name}</label><div class="number-box"><input id="geometry-${index}" type="text" inputmode="decimal" autocomplete="off" aria-label="${name}" disabled><span class="unit">${index < 3 ? "m" : "°"}</span><span class="steppers"><button data-step="1" aria-label="Increase ${name}" disabled>▴</button><button data-step="-1" aria-label="Decrease ${name}" disabled>▾</button></span></div><span class="feedback" id="geometry-error-${index}"></span></div>`,
      )
      .join("");
    values.forEach((value, index) => {
      const input = $("#geometry-" + index),
        edit = new SpotUI.NumberEdit(value ?? 0, {
          min: index < 3 ? -10 : -360,
          max: index < 3 ? 10 : 360,
          revision: state.revision,
          preview: (value) => {
            edit.previewValue = value;
            viewer?.draw();
            readout();
          },
          commit: async (value) => ({ value, revision: state.revision }),
        });
      edit.previewValue = value ?? 0;
      geometryNumbers.push(edit);
      input.value = value == null ? "" : edit.text;
      const feedback = () => {
        $("#geometry-error-" + index).textContent = edit.error;
      };
      input.onfocus = () => edit.focus();
      input.oninput = () => {
        edit.input(input.value);
        feedback();
      };
      input.onblur = () => {
        edit.focused = false;
        edit.commit().then(() => {
          if (document.activeElement !== input) input.value = edit.text;
          feedback();
        });
      };
      input.onkeydown = (event) => {
        if (event.key === "Escape") {
          edit.cancel();
          input.value = edit.text;
          feedback();
        } else if (event.key === "Enter") {
          event.preventDefault();
          edit.commit().then(feedback);
        } else if (["ArrowUp", "ArrowDown"].includes(event.key)) {
          event.preventDefault();
          if (edit.step(event.key === "ArrowUp" ? 1 : -1, event, index >= 3)) {
            input.value = edit.text;
            edit.commit().then(feedback);
          }
        }
      };
      for (const stepper of input.parentElement.querySelectorAll("[data-step]"))
        stepper.onclick = (event) => {
          if (edit.step(Number(stepper.dataset.step), event, index >= 3)) {
            input.value = edit.text;
            edit.commit().then(feedback);
          }
        };
    });
    readout();
  });
  function readout() {
    if ($("#transform-readout"))
      $("#transform-readout").textContent = geometryNumbers
        .map(
          (edit, index) =>
            `${["X", "Y", "Z", "Yaw", "Pitch", "Roll"][index]} ${fmt(edit.previewValue, index < 3 ? 3 : 1)} ${index < 3 ? "m" : "°"}`,
        )
        .join(" · ");
  }
  $("#inspection-preview").onchange = () => {
    for (const input of $$("#geometry-fields input, #geometry-fields button"))
      input.disabled = !$("#inspection-preview").checked || !c.geometry;
  };
  $("#geometry-reset").onclick = () => {
    if (!c.geometry || !window.SpotViewer) return;
    const values = [
      ...c.geometry.translation,
      ...SpotViewer.angles(c.geometry.quaternion),
    ];
    geometryNumbers.forEach((edit, index) => {
      edit.ack = values[index];
      edit.previewValue = values[index];
      edit.cancel();
      $("#geometry-" + index).value = edit.text;
    });
    viewer?.draw();
    readout();
  };
  pageUpdate = () => {
    const latest = camera(c.identity);
    if (latest?.geometry && window.SpotViewer && geometryNumbers.length) {
      const values = [
        ...latest.geometry.translation,
        ...SpotViewer.angles(latest.geometry.quaternion),
      ];
      geometryNumbers.forEach((edit, index) => {
        if (
          !$("#inspection-preview").checked ||
          edit.revision !== state.revision
        )
          edit.readback(values[index], state.revision);
        const input = $("#geometry-" + index);
        if (input && document.activeElement !== input && !edit.conflict)
          input.value = edit.text;
      });
    }
    viewer?.draw();
  };
}
function networkPage() {
  $("#page").innerHTML =
    '<h1>Network</h1><div class="two-columns"><section class="panel"><h2>Connection</h2><dl class="data-list" id="connection-data"></dl><p class="capability-lock spaced">Endpoint pinned by installation configuration</p><button id="standalone">Begin standalone setup</button><p id="page-feedback" class="feedback"></p></section><section class="panel"><h2>Link</h2><dl class="data-list" id="link-data"></dl></section></div>';
  $("#standalone").onclick = async () => {
    try {
      await mutation("standalone", {});
      announce("Standalone setup session started");
    } catch (error) {
      showError(error);
    }
  };
  pageUpdate = () => {
    const e = state.endpoint || {};
    $("#connection-data").innerHTML = dl({
      "Robot endpoint":
        e.configured || (e.team ? `Team ${e.team}` : "Unavailable"),
      "NetworkTables server": state.robot_id || "Unavailable",
      "Connection mode": e.mode || "NT4 client",
    });
    $("#link-data").innerHTML = dl({
      NetworkTables: state.connected ? "Connected" : "Disconnected",
      "Local addresses": e.local_addresses?.join(", ") || "Unavailable",
      Synchronization: state.clock.state || "Unavailable",
      Profile: state.fresh
        ? "Current robot session"
        : state.robot_id
          ? "Cached configuration"
          : "Unavailable",
      "Connection epoch": state.clock.connection_epoch || "—",
    });
    $("#standalone").disabled = state.connected;
    $("#standalone").textContent = state.standalone
      ? "Standalone setup active"
      : "Begin standalone setup";
  };
}
const dl = (values) =>
  Object.entries(values)
    .map(
      ([key, value]) =>
        `<dt>${escapeHTML(key)}</dt><dd>${escapeHTML(value)}</dd>`,
    )
    .join("");
function systemPage() {
  $("#page").innerHTML =
    '<h1>System</h1><div class="panel stats" id="system-stats"></div><div class="system-grid"><section class="panel"><h2>Camera pipelines</h2><div class="table-scroll"><table><thead><tr><th>Camera</th><th>Capture / detect</th><th>Backend</th><th>Published / withheld</th><th>Drops</th><th>Frame age</th></tr></thead><tbody id="pipeline-table"></tbody></table></div></section><section class="panel"><h2>Software</h2><dl id="software-data" class="data-list"></dl></section><section class="panel"><h2>USB devices</h2><div id="usb-data"></div></section><section class="panel"><h2>Clock and startup</h2><dl id="startup-data" class="data-list"></dl></section><section class="panel wide"><h2>Faults and support</h2><div id="fault-data"></div><div class="inline-actions spaced"><button id="support-export">Export support bundle</button><button id="state-export">Export configuration</button><label><input type="file" id="state-import" accept="application/json,.json"> Import configuration</label><button id="debug-record">Record 10 s diagnostics</button></div><p id="page-feedback" class="feedback"></p></section></div>';
  $("#support-export").onclick = () =>
    downloadJSON("/api/support", "spot-support.json");
  $("#state-export").onclick = () =>
    downloadJSON("/api/export", "spot-state.json");
  $("#debug-record").onclick = async () => {
    try {
      await mutation("debug", { seconds: 10, revision: state.revision });
      announce("Bounded diagnostics recording started");
    } catch (error) {
      showError(error);
    }
  };
  $("#state-import").onchange = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      showError(new Error("Configuration exceeds 2 MiB import bound"));
      return;
    }
    try {
      const document = JSON.parse(await file.text());
      await mutation("import", { document, revision: state.revision });
      announce("Configuration imported and acknowledged");
    } catch (error) {
      showError(error);
    }
  };
  pageUpdate = () => {
    const m = state.system || {},
      r = state.release || {},
      d = r.deployment || {};
    $("#system-stats").innerHTML = Object.entries({
      CPU: Number.isFinite(m.cpu_percent) ? `${fmt(m.cpu_percent, 0)}%` : "—",
      GPU: Number.isFinite(m.gpu_percent) ? `${fmt(m.gpu_percent, 0)}%` : "—",
      Temperature: Number.isFinite(m.temperature_c)
        ? `${fmt(m.temperature_c, 0)} °C`
        : "—",
      Memory: Number.isFinite(m.memory_used_gb)
        ? `${fmt(m.memory_used_gb)} / ${fmt(m.memory_total_gb)} GB`
        : "—",
      Uptime: age(state.uptime_s),
    })
      .map(
        ([name, value]) =>
          `<div class="stat"><strong>${value}</strong><small>${name}</small></div>`,
      )
      .join("");
    $("#pipeline-table").innerHTML = state.cameras
      .map(
        (c) =>
          `<tr><td>${escapeHTML(c.name)}</td><td>${c.connected ? `${fmt(c.metrics?.fps_capture, 0)} / ${c.metrics?.detect_age_s <= 0.5 ? fmt(c.metrics?.fps_detect, 0) : "—"} FPS` : "—"}</td><td>${escapeHTML(c.processing?.backend || "Unavailable")}${c.processing?.degraded ? " · degraded" : ""}${c.processing?.thermal_reduction ? " · thermal" : ""}${c.processing?.overload_reduction ? " · load" : ""}<br><small>${escapeHTML(c.processing?.backend_generation?.slice(0, 8) || "")}</small></td><td>${c.metrics?.published ?? "—"} / ${c.metrics?.withheld ?? "—"}<br><small>${age(c.metrics?.publish_age_s)}</small></td><td>${c.metrics?.overwritten_before_processing ?? "—"} / ${c.metrics?.driver_sequence_gaps ?? "—"}</td><td>${age(c.age_s)}</td></tr>`,
      )
      .join("");
    $("#software-data").innerHTML = dl({
      "Last successful deployment": date(
        d.last_successful_deployment?.completed_at,
      ),
      "Running release": r.release_id || "Unavailable",
      "Source commit": r.source_commit || "Unavailable",
      "Native build": r.native_sha256 || "Unavailable",
      Started: date(r.process_started_at),
      "Latest attempt": d.latest_attempt?.verification || "Unavailable",
      Rollback: d.rollback ? "Restored previous release" : "—",
    });
    $("#usb-data").innerHTML = state.cameras
      .map(
        (c) =>
          `<p><strong>${escapeHTML(c.name)}</strong><br><small>${escapeHTML(c.topology || "Missing")} · ${escapeHTML(c.capture_node || "No capture node")}<br>${escapeHTML("Saved port slot " + c.display_id + (c.unique_serial ? " · serial " + c.serial : " · duplicate/missing serial"))}</small></p>`,
      )
      .join("");
    $("#startup-data").innerHTML = dl({
      Clock: state.clock.state || "Unavailable",
      Offset: `${state.clock.offset_us ?? "—"} µs`,
      "Sync update age": age(state.clock.update_age_s),
      "Sync epoch": state.clock.sync_epoch || "—",
      Discontinuities: state.clock.discontinuities ?? "—",
      ...Object.fromEntries(
        Object.entries(state.startup || {}).map(([key, value]) => [
          key.replaceAll("_", " "),
          age(value),
        ]),
      ),
    });
    $("#fault-data").innerHTML =
      [
        serviceError,
        ...(state.faults || []),
        ...state.cameras
          .filter((c) => c.fault)
          .map((c) => c.name + ": " + c.fault),
      ]
        .filter(Boolean)
        .map((f) => `<p class="warning">${escapeHTML(f)}</p>`)
        .join("") || "<p>No active faults reported</p>";
  };
}
async function downloadJSON(path, name) {
  try {
    const result = await api(path);
    const url = URL.createObjectURL(
        new Blob([JSON.stringify(result, null, 2)], {
          type: "application/json",
        }),
      ),
      link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    showError(error);
  }
}
function calibrationPage(results) {
  $("#page").innerHTML =
    `<h1>Calibration</h1><div class="tabs"><a href="#calibration" class="${!results ? "active" : ""}">Capture</a><a href="#calibration/results" class="${results ? "active" : ""}">Results / history</a><div class="actions"><button id="pause-all">Pause all</button><button id="reset-session">Reset session</button></div></div><p class="lock" id="calibration-lock"></p><p class="feedback" id="page-feedback"></p><div id="calibration-content"></div>`;
  const action = async (operation, payload = {}) => {
    try {
      return await mutation("calibration/" + operation, {
        ...payload,
        revision: state.revision,
      });
    } catch (error) {
      showError(error);
      return null;
    }
  };
  $("#pause-all").onclick = () => action("pause-all");
  $("#reset-session").onclick = () => action("reset");
  if (results) {
    $("#calibration-content").innerHTML =
      '<section class="panel"><h2>Results</h2><div class="table-scroll"><table><thead><tr><th>Camera</th><th>Fit RMS</th><th>Validation RMS</th><th>Fit / validation views</th><th>Result</th></tr></thead><tbody id="results-table"></tbody></table></div><div class="results-actions"><button id="select-passing">Select passing</button><button id="apply-selected" class="primary">Apply selected</button><small id="apply-status"></small></div></section><section class="panel history-panel"><h2>History</h2><div id="calibration-history"></div></section>';
    $("#select-passing").onclick = () => {
      appliedResults.clear();
      for (const [id, c] of Object.entries(state.calibration.cameras || {}))
        if (c.fit?.accepted && c.holdout?.accepted) appliedResults.add(id);
      pageUpdate();
    };
    let applying = false;
    $("#apply-selected").onclick = async () => {
      if (applying) return;
      applying = true;
      const button = $("#apply-selected");
      button.disabled = true;
      $("#apply-status").textContent =
        "Awaiting durable runtime acknowledgement";
      const result = await action("apply", {
        identities: Array.from(appliedResults),
      });
      applying = false;
      pageUpdate();
      if (result && $("#apply-status"))
        $("#apply-status").textContent =
          "Applied · " + result.applied_generation;
    };
    pageUpdate = () => {
      const sessions = state.calibration.cameras || {};
      $("#calibration-lock").textContent = state.lock_reason;
      updateHTML(
        $("#results-table"),
        Object.entries(sessions)
          .map(
            ([id, c]) =>
              `<tr><td><label><input type="checkbox" data-result="${id}" ${appliedResults.has(id) ? "checked" : ""}> ${escapeHTML(camera(id)?.name || id.slice(0, 8))}</label></td><td>${fmt(c.fit?.rms_reprojection_error_px, 2)} px</td><td>${fmt(c.holdout?.rms_px, 2)} px</td><td>${c.fit_views} / ${c.holdout_views}</td><td class="${c.fit?.accepted && c.holdout?.accepted ? "good" : "warning"}">${escapeHTML(c.fit?.accepted && c.holdout?.accepted ? "✓ Pass" : c.reason || c.fit?.reason || "Capture required")}</td></tr>`,
          )
          .join("") ||
          '<tr><td colspan="5">Select cameras on Capture</td></tr>',
      );
      for (const checkbox of $$("[data-result]"))
        checkbox.onchange = () => {
          checkbox.checked
            ? appliedResults.add(checkbox.dataset.result)
            : appliedResults.delete(checkbox.dataset.result);
          pageUpdate();
        };
      $("#apply-selected").disabled = Boolean(
        state.lock_reason ||
        applying ||
        !appliedResults.size ||
        Array.from(appliedResults).some(
          (id) =>
            !sessions[id]?.fit?.accepted ||
            !sessions[id]?.holdout?.accepted ||
            sessions[id]?.solving,
        ),
      );
      const histories = (state.history || []).filter(
        (h) => h.cameras?.length || h.error,
      );
      for (const h of histories) {
        if (!historySelections.has(h.generation))
          historySelections.set(h.generation, new Set());
      }
      updateHTML(
        $("#calibration-history"),
        histories
          .map((h) => {
            const selection = historySelections.get(h.generation);
            const records = h.cameras
              .map((record) => {
                const current = camera(record.identity);
                const compatible =
                  current?.connected &&
                  current.mode_signature === record.mode_signature;
                return `<label class="spaced"><input type="checkbox" data-history="${h.generation}" data-hash="${record.hash}" ${selection.has(record.hash) ? "checked" : ""} ${!compatible || h.active || state.lock_reason ? "disabled" : ""}> ${escapeHTML(current?.name || record.identity.slice(0, 8))} · ${date(record.saved_at)} ${compatible ? "" : "· current mode unavailable or incompatible"}</label>`;
              })
              .join("<br>");
            return `<div class="spaced"><strong>${escapeHTML(h.generation.slice(0, 12))}</strong> ${h.active ? "· active" : ""}<p>${records}</p>${h.error ? `<span class="warning">${escapeHTML(h.error)}</span>` : `<button data-restore="${h.generation}" ${h.active || state.lock_reason || !selection.size ? "disabled" : ""}>Restore selected</button>`}</div>`;
          })
          .join("") || '<p class="muted">No activated calibration history</p>',
      );
      for (const checkbox of $$("[data-history]"))
        checkbox.onchange = () => {
          const selection = historySelections.get(checkbox.dataset.history);
          checkbox.checked
            ? selection.add(checkbox.dataset.hash)
            : selection.delete(checkbox.dataset.hash);
          pageUpdate();
        };
      for (const button of $$("[data-restore]"))
        button.onclick = async () => {
          try {
            await mutation("restore", {
              generation: button.dataset.restore,
              calibration_hashes: Array.from(
                historySelections.get(button.dataset.restore),
              ),
              revision: state.revision,
            });
            announce("Selected calibration group restored");
          } catch (error) {
            showError(error);
          }
        };
    };
  } else {
    const usable = state.cameras.filter((c) => c.logical_name || c.connected);
    for (const id of selectedCalibration)
      if (!usable.some((c) => c.identity === id))
        selectedCalibration.delete(id);
    $("#calibration-content").innerHTML =
      `<div class="calibration-layout"><div><div class="inline-actions"><select id="calibration-selection" aria-label="Camera to add"><option value="">Select camera</option>${usable.map((c) => `<option value="${c.identity}">${escapeHTML(c.name)}</option>`).join("")}</select><button id="add-camera">Add camera</button></div><div id="calibration-cards" class="calibration-grid spaced"></div></div><section class="panel board"><h2>Board</h2><div id="board-fields" class="board-fields"></div><button id="update-board" class="spaced">Update board</button><label class="spaced">Group capture set<select id="group-phase"><option value="fit">Fitting captures</option><option value="holdout">Validation captures</option></select></label><button id="start-all" class="primary spaced">Start automatic capture</button><p><a href="#docs/calibrate">Capture and validation guide</a></p></section></div>`;
    $("#start-all").onclick = () =>
      action("start-all", { phase: $("#group-phase").value });
    $("#add-camera").onclick = async () => {
      const id = $("#calibration-selection").value;
      if (!id) return;
      const selected = camera(id);
      if (!selected.logical_name && (!selected.standalone_setup || state.lock_reason)) {
        try { await beginCameraSetup(selected); } catch (error) { showError(error); return; }
      }
      selectedCalibration.add(id);
      const result = await action("select", {
        identities: Array.from(selectedCalibration),
      });
      if (!result) selectedCalibration.delete(id);
      routeKey = "";
      render();
    };
    const board = state.calibration.board || {},
      options = state.calibration.options || {};
    $("#board-fields").innerHTML =
      Object.entries({
        dictionary: "Dictionary",
        squares_x: "Squares X",
        squares_y: "Squares Y",
        square_length_m: "Square length (m)",
        marker_length_m: "Marker length (m)",
      })
        .map(
          ([key, label]) =>
            `<label>${label}<input id="board-${key}" type="text" inputmode="${key === "dictionary" ? "text" : "decimal"}" value="${escapeHTML(board[key])}"></label>`,
        )
        .join("") +
      `<label>Lens model<select id="board-model"><option value="plumb_bob">Plumb bob</option><option value="rational">Rational</option></select></label><label>Minimum fit views<input id="board-min-views" type="text" inputmode="numeric" value="${options.min_frames || 15}"></label>`;
    $("#board-model").value = options.model || "plumb_bob";
    $("#update-board").onclick = async () => {
      const values = Object.fromEntries(
        Object.keys(board).map((key) => [
          key,
          key === "dictionary"
            ? $("#board-" + key).value
            : Number($("#board-" + key).value),
        ]),
      );
      const result = await action("board", {
        board: values,
        options: {
          ...options,
          model: $("#board-model").value,
          min_frames: Number($("#board-min-views").value),
        },
      });
      if (result && selectedCalibration.size) {
        await action("select", { identities: Array.from(selectedCalibration) });
        routeKey = "";
        render();
      }
    };
    const sessions = state.calibration.cameras || {};
    for (const id of Object.keys(sessions)) selectedCalibration.add(id);
    $("#calibration-cards").innerHTML =
      Array.from(selectedCalibration)
        .map(
          (id) =>
            `<section class="panel calibration-card" data-calibration="${id}"><header><input type="checkbox" checked aria-label="Select ${escapeHTML(camera(id)?.name)}"><strong>${escapeHTML(camera(id)?.name || id.slice(0, 8))}</strong></header>${feed(id)}<progress class="coverage-progress" max="1" value="0" aria-label="Calibration coverage"></progress><div class="capture-stats"></div><div class="actions"><select aria-label="Capture set"><option value="fit">Fitting captures</option><option value="holdout">Validation captures</option></select><button data-cal-action="start">Start</button><button data-cal-action="capture">Capture</button><button data-cal-action="compute">Calibrate</button><button data-cal-action="validate">Validate</button></div><p class="feedback"></p></section>`,
        )
        .join("") ||
      '<p class="muted">Add a connected camera to begin.</p>';
    for (const card of $$("[data-calibration]")) {
      const id = card.dataset.calibration;
      card.querySelector("input").onchange = async (event) => {
        event.target.checked
          ? selectedCalibration.add(id)
          : selectedCalibration.delete(id);
        await action("select", { identities: Array.from(selectedCalibration) });
      };
      for (const button of card.querySelectorAll("[data-cal-action]"))
        button.onclick = () => {
          const s = state.calibration.cameras?.[id],
            a = button.dataset.calAction;
          action(a === "start" && s?.running ? "pause" : a, {
            identity: id,
            phase: card.querySelector("select").value,
            automatic: true,
          });
        };
    }
    pageUpdate = () => {
      $("#calibration-lock").textContent = state.lock_reason;
      $("#update-board").disabled = Boolean(state.lock_reason);
      $("#start-all").disabled = Boolean(
        state.lock_reason ||
        !selectedCalibration.size ||
        Object.values(state.calibration.cameras || {}).some((s) => s.solving),
      );
      for (const card of $$("[data-calibration]")) {
        const s = state.calibration.cameras?.[card.dataset.calibration];
        card.querySelector(".capture-stats").textContent = s
          ? `${s.fit_views} fit / ${s.holdout_views} validation views · ${Math.round((s.coverage?.coverage_progress || 0) * 100)}% coverage · ${s.board_detected ? "Board detected" : "Board not detected"}`
          : "Start a calibration session";
        card.querySelector(".coverage-progress").value = Math.max(
          0,
          Math.min(1, s?.coverage?.coverage_progress || 0),
        );
        card.querySelector(".feedback").textContent = s?.reason || "";
        for (const button of card.querySelectorAll("button")) {
          button.disabled = Boolean(state.lock_reason || s?.solving);
          if (button.dataset.calAction === "start")
            button.textContent = s?.running ? "Pause" : "Start";
        }
      }
    };
  }
}
async function docsPage(id) {
  if (!docs) docs = await api("/docs.json");
  if (currentRoute().page !== "docs" || currentRoute().id !== id) return;
  const topics = docs.topics,
    topic = topics.find((t) => t.id === id) || topics[0];
  $("#page").innerHTML =
    `<h1>Docs</h1><input id="docs-search" class="docs-search" type="search" placeholder="Search docs" aria-label="Search docs"><div class="docs-layout"><nav id="docs-nav" class="panel docs-nav" aria-label="Documentation topics"></nav><article class="article" id="docs-article"></article><aside class="docs-outline"><h3>On this page</h3><div id="docs-outline"></div></aside></div>`;
  const groups = ["Getting started", "Guides", "Reference"];
  function navigation(query = "") {
    $("#docs-nav").innerHTML = groups
      .map(
        (group) =>
          `<h3>${group.toUpperCase()}</h3>${topics
            .filter(
              (t) =>
                t.group === group &&
                (t.title + " " + t.text)
                  .toLowerCase()
                  .includes(query.toLowerCase()),
            )
            .map(
              (t) =>
                `<a class="${t.id === topic.id ? "active" : ""}" href="#docs/${t.id}">${escapeHTML(t.title)}</a>`,
            )
            .join("")}`,
      )
      .join("");
  }
  navigation();
  $("#docs-search").oninput = (event) => navigation(event.target.value);
  const index = topics.indexOf(topic);
  $("#docs-article").innerHTML =
    topic.html +
    `<div class="prev-next">${index ? `<a href="#docs/${topics[index - 1].id}">← ${escapeHTML(topics[index - 1].title)}</a>` : "<span></span>"}${index < topics.length - 1 ? `<a href="#docs/${topics[index + 1].id}">${escapeHTML(topics[index + 1].title)} →</a>` : ""}</div>`;
  $("#docs-outline").innerHTML = topic.headings
    .map(
      (h) =>
        `<a href="#${h.id}" data-outline="${h.id}">${escapeHTML(h.text)}</a>`,
    )
    .join("");
  for (const link of $$("[data-outline]"))
    link.onclick = (event) => {
      event.preventDefault();
      document
        .getElementById(link.dataset.outline)
        ?.scrollIntoView({ behavior: "auto" });
    };
  pageUpdate = () => {};
}
function render() {
  for (const [id, preview] of previews)
    if (!state.cameras.some((c) => c.identity === id)) {
      for (const bitmap of new Set([preview.bitmap, preview.held?.bitmap]))
        bitmap?.close();
      previews.delete(id);
    }
  nav();
  const route = currentRoute(),
    c = camera(route.id);
  const key =
    route.page +
    "/" +
    (route.id || "") +
    "/" +
    (route.tab || "") +
    (route.page === "camera" ? "/" + Boolean(c?.logical_name) + "/" + Boolean(c?.standalone_setup) : "");
  if (key !== routeKey) {
    routeKey = key;
    tuner?.dispose();
    tuner = null;
    viewer?.destroy();
    viewer = null;
    geometryNumbers = [];
    pageUpdate = () => {};
    if (["overview", "cameras"].includes(route.page)) overview(route.page);
    else if (route.page === "camera" && c) {
      if (!c.logical_name && !c.standalone_setup) namePage(c);
      else if (route.tab === "geometry") geometryPage(c);
      else detailPage(c);
    } else if (route.page === "calibration")
      calibrationPage(route.id === "results");
    else if (route.page === "network") networkPage();
    else if (route.page === "system") systemPage();
    else if (route.page === "docs")
      docsPage(route.id).catch((error) => showError(error));
    else {
      $("#page").innerHTML =
        '<h1>Camera unavailable</h1><p>The configured camera may be disconnected. <a href="#cameras">Open Cameras</a></p>';
    }
    const selector = $(".camera-selector");
    if (selector)
      selector.onchange = () => {
        location.hash =
          "camera/" +
          encodeURIComponent(selector.value) +
          (route.tab === "geometry" ? "/geometry" : "");
      };
  }
  pageUpdate();
  drawFeeds();
}
async function poll() {
  if (document.hidden) {
    setTimeout(poll, 1000);
    return;
  }
  try {
    state = await api("/api/status");
    serviceError = "";
    render();
  } catch (error) {
    serviceError = "Service unavailable · reconnecting";
    for (const preview of previews.values())
      if (preview.data) preview.data.stale = true;
    drawFeeds();
    announce(serviceError);
  }
  setTimeout(poll, 500);
}
let previewBusy = false;
async function previewPoll() {
  const started = performance.now();
  if (!document.hidden && session && !previewBusy) {
    previewBusy = true;
    const visible = $$("[data-feed]")
      .filter(
        (el) =>
          el.getBoundingClientRect().bottom > 0 &&
          el.getBoundingClientRect().top < innerHeight,
      )
      .slice(0, 8);
    await Promise.allSettled(
      visible.map(async (element) => {
        const id = element.dataset.feed;
        if (!/^[a-f0-9]{64}$/.test(id)) return;
        let view = previews.get(id);
        if (!view) {
          view = { paused: false, data: null, bitmap: null };
          previews.set(id, view);
        }
        if (view.paused) return;
        try {
          const data = await api("/api/frame/" + id);
          if (
            data.image &&
            (!view.bitmap ||
              data.capture_epoch !== view.data?.capture_epoch ||
              data.sequence !== view.data?.sequence)
          ) {
            const bytes = Uint8Array.from(atob(data.image), (c) =>
                c.charCodeAt(0),
              ),
              blob = new Blob([bytes], { type: "image/jpeg" }),
              bitmap = await createImageBitmap(blob);
            if (view.bitmap && view.bitmap !== view.held?.bitmap)
              view.bitmap.close();
            view.bitmap = bitmap;
          }
          view.data = data;
          view.received = performance.now();
        } catch {
          if (view.data) view.data.stale = true;
        }
      }),
    );
    previewBusy = false;
    drawFeeds();
    const route = currentRoute();
    if (route.page === "camera") {
      updateDetections(route.id);
      viewer?.draw();
    }
  }
  setTimeout(previewPoll, Math.max(0, 50 - (performance.now() - started)));
}
function drawFeeds() {
  for (const element of $$("[data-feed]")) {
    const id = element.dataset.feed,
      view = previews.get(id),
      data = view?.paused ? view.held : view?.data,
      bitmap = view?.paused ? view.held?.bitmap : view?.bitmap,
      canvas = element.querySelector("canvas"),
      context = canvas.getContext("2d");
    const c = camera(id),
      stale =
        !view?.paused &&
        (serviceError ||
          !c?.connected ||
          c.age_s > 0.5 ||
          data?.generation !== state.applied_generation ||
          data?.stale);
    context.clearRect(0, 0, canvas.width, canvas.height);
    if (bitmap) {
      const scale = Math.min(
          canvas.width / bitmap.width,
          canvas.height / bitmap.height,
        ),
        w = bitmap.width * scale,
        h = bitmap.height * scale;
      context.drawImage(
        bitmap,
        (canvas.width - w) / 2,
        (canvas.height - h) / 2,
        w,
        h,
      );
      if (!stale && currentRoute().page === "calibration") {
        const coverage = state.calibration.cameras?.[id]?.coverage;
        for (const particle of (coverage?.coverage_particles || []).slice(
          0,
          6912,
        )) {
          if (
            ![particle.x, particle.y, particle.progress].every(Number.isFinite)
          )
            continue;
          context.fillStyle =
            particle.progress >= 1
              ? "rgba(85,230,155,.46)"
              : "rgba(255,216,90,.7)";
          context.beginPath();
          context.arc(
            (canvas.width - w) / 2 + particle.x * w,
            (canvas.height - h) / 2 + particle.y * h,
            particle.progress >= 1 ? 1.5 : 1.7,
            0,
            Math.PI * 2,
          );
          context.fill();
        }
      }
      if (!stale && $("#outlines")?.checked !== false) {
        context.strokeStyle = "#79D6A5";
        context.fillStyle = "#79D6A5";
        context.lineWidth = 2;
        context.font = "14px Source Sans Pro";
        for (const tag of data?.tags || []) {
          context.beginPath();
          tag.corners.forEach((p, index) => {
            const x = (canvas.width - w) / 2 + (p[0] / data.width) * w,
              y = (canvas.height - h) / 2 + (p[1] / data.height) * h;
            index ? context.lineTo(x, y) : context.moveTo(x, y);
          });
          context.closePath();
          context.stroke();
          const p = tag.corners[0];
          context.fillText(
            "#" + tag.id,
            (canvas.width - w) / 2 + (p[0] / data.width) * w,
            (canvas.height - h) / 2 + (p[1] / data.height) * h - 5,
          );
        }
      }
      const coverage =
        state.calibration.cameras?.[id]?.coverage?.coverage_particles;
      if (coverage && !stale && currentRoute().page === "calibration")
        for (const dot of coverage) {
          context.fillStyle = dot.progress >= 1 ? "#79D6A5" : "#E5BA72";
          context.beginPath();
          context.arc(
            (canvas.width - w) / 2 + dot.x * w,
            (canvas.height - h) / 2 + dot.y * h,
            2,
            0,
            Math.PI * 2,
          );
          context.fill();
        }
    }
    const shownAge =
      data?.age_s +
      (performance.now() -
        (view?.paused ? view.held?.heldAt : view?.received)) /
        1000;
    const text = view?.paused
      ? `Paused · frame ${data?.sequence ?? "—"} · ${age(shownAge)}`
      : serviceError
        ? "Service disconnected · last image"
        : !c?.connected
          ? c?.health === "Disabled"
            ? "Disabled in code"
            : c?.present
              ? c.fault || "Waiting for image"
              : "Disconnected"
          : stale && bitmap
            ? "Stale image · outlines hidden"
            : !bitmap
              ? "Waiting for image"
              : "";
    element.querySelector(".image-state").textContent = text;
    if ($("#frame-info") && id === currentRoute().id)
      $("#frame-info").textContent = data
        ? `Frame ${data.sequence} · ${age(shownAge)} · ${data.width} × ${data.height}`
        : "Waiting for frame";
  }
}
addEventListener("hashchange", () => render());
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    for (const preview of previews.values())
      if (!preview.paused && preview.data) preview.data.stale = true;
    api("/api/status")
      .then((result) => {
        state = result;
        render();
      })
      .catch(() => {});
  }
});
theme();
api("/api/session")
  .then((result) => {
    session = result;
    previewPoll();
  })
  .catch((error) => announce(error.message));
poll();
