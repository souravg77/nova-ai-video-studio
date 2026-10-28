/* NOVA Studio dashboard — real media import, preview, timeline and render. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const api = (p, o) => fetch("/api" + p, o).then(r => r.json());

  const GRADS = ["grad-a", "grad-b", "grad-c", "grad-d"];

  // ---- App state -----------------------------------------------------
  const state = {
    project: "My First Video Project",
    // media: {id, kind, name, url, thumb, w, h, dur}
    media: [],
    // scenes reference a media id (or null -> colour slate). Starts empty;
    // the user builds the video from their own imported photos/clips.
    scenes: [],
    selected: -1,
    mediaTab: "photos",
    vspeed: 1.0, vpause: 0.5,
    subtitles: true, subStyle: "Modern (White)", subSize: "Medium",
    exp: { res: "HD 1080p", fps: "30 fps", codec: "H.264 (MP4)" },
    playing: false, t: 0,
    voices: [],
  };

  const mediaById = (id) => state.media.find(m => m.id === id);
  const curScene = () =>
    (state.selected >= 0 && state.selected < state.scenes.length)
      ? state.scenes[state.selected] : null;
  const fmt = (s) => {
    s = Math.max(0, Math.round(s));
    const h = String(Math.floor(s / 3600)).padStart(2, "0");
    const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
    const ss = String(s % 60).padStart(2, "0");
    return `${h}:${m}:${ss}`;
  };
  const totalDur = () => state.scenes.reduce((a, s) => a + s.dur, 0);

  // thumb/background HTML for a scene (real image if it has media)
  function sceneThumbHTML(s) {
    const m = mediaById(s.mediaId);
    if (m) return `<img src="${m.thumb || m.url}" alt="">`;
    return "";
  }
  function sceneThumbClass(s) {
    return mediaById(s.mediaId) ? "" : s.grad;
  }

  // ---- Renderers -----------------------------------------------------
  function renderMedia() {
    const el = $("#mediaList");
    const kind = { photos: "image", audio: "audio", videos: "video" }[state.mediaTab];
    const items = state.media.filter(m => m.kind === kind);
    if (!items.length) {
      const msg = kind === "image" ? "No photos yet. Click Import to add images."
        : kind === "audio" ? "No audio yet. Import a narration/music track."
        : "No videos yet. Import footage to use as scenes.";
      el.innerHTML = `<div class="empty">${msg}</div>`;
      return;
    }
    el.innerHTML = items.map(m => {
      const thumb = m.kind === "audio"
        ? `<div class="mi-thumb grad-d" style="display:grid;place-items:center">♪</div>`
        : `<div class="mi-thumb"><img src="${m.thumb || m.url}" alt=""></div>`;
      const sub = m.kind === "image" ? `${m.w || "?"} × ${m.h || "?"}`
        : m.kind === "video" ? `video · ${m.dur ? m.dur.toFixed(1) + "s" : ""}`
          : `audio · ${m.dur ? m.dur.toFixed(1) + "s" : ""}`;
      return `<div class="media-item" data-mid="${m.id}" title="Click to add as a scene">
        ${thumb}<div><div class="mi-name">${m.name}</div><div class="mi-sub">${sub}</div></div></div>`;
    }).join("");
    $$("#mediaList .media-item").forEach(it =>
      it.onclick = () => addSceneFromMedia(it.dataset.mid));
  }

  function renderScenes() {
    $("#sceneCount").textContent = state.scenes.length;
    $("#cpScenes").textContent = state.scenes.length + " scenes";
    $("#cpDur").textContent = fmt(totalDur());
    $("#sceneList").innerHTML = state.scenes.map((s, i) => `
      <div class="scene-card ${i === state.selected ? "active" : ""}" data-i="${i}">
        <div class="sc-num">${i + 1}</div>
        <div class="sc-thumb ${sceneThumbClass(s)}">${sceneThumbHTML(s)}</div>
        <div><div class="sc-name">${s.title}</div><div class="sc-sub">${s.name}</div></div>
        <div class="sc-dur">${fmt(s.dur).slice(3)}</div>
      </div>`).join("");
    $$("#sceneList .scene-card").forEach(c =>
      c.onclick = () => selectScene(+c.dataset.i));
  }

  function renderTimeline() {
    const total = totalDur() || 1;
    const ruler = $("#tlRuler"); ruler.innerHTML = "";
    for (let s = 0; s <= total; s += 5) {
      const d = document.createElement("div");
      d.className = "tick"; d.style.left = (s / total * 100) + "%";
      d.textContent = fmt(s).slice(3);
      ruler.appendChild(d);
    }
    $("#trackVideo").innerHTML = state.scenes.map(s => {
      const m = mediaById(s.mediaId);
      const inner = m ? `<img src="${m.thumb || m.url}" alt="">` : "";
      return `<div class="tl-clip ${m ? "" : s.grad}" style="flex:${s.dur}">
        ${inner}<span class="cl-name">${s.title}</span></div>`;
    }).join("");
    const bars = Array.from({ length: 80 }, (_, i) =>
      `<i style="height:${20 + Math.abs(Math.sin(i * 0.7)) * 70}%"></i>`).join("");
    const wf = $("#waveform");
    if (wf) wf.outerHTML = `<div class="wave-bars" id="waveform">${bars}</div>`;
    $("#trackSubs").innerHTML = state.scenes.map(s =>
      `<div class="sub-block" style="flex:${s.dur}">${s.caption}</div>`).join("");
    const tr = $("#trackTrans"); tr.innerHTML = "";
    let acc = 0;
    state.scenes.slice(0, -1).forEach(s => {
      acc += s.dur;
      const d = document.createElement("div");
      d.className = "trans-diamond";
      d.style.position = "absolute"; d.style.left = (acc / total * 100) + "%";
      d.style.top = "50%"; d.style.transform = "translate(-50%,-50%) rotate(45deg)";
      tr.appendChild(d);
    });
    $("#totTime").textContent = fmt(totalDur());
    updatePlayhead();
  }

  function updatePlayhead() {
    const total = totalDur() || 1;
    const frac = Math.min(1, state.t / total);
    const trackLeft = 150;
    const w = $(".tl-body").clientWidth - trackLeft;
    $("#playhead").style.left = (trackLeft + frac * w) + "px";
    $("#curTime").textContent = fmt(state.t);
  }

  function selectScene(i) {
    const img = $("#pvImg"), vid = $("#pvVid"), frame = $("#pvFrame"),
      empty = $("#pvEmpty");
    img.style.display = "none"; vid.style.display = "none";
    frame.style.display = "none"; empty.style.display = "none";
    // Empty project (no scenes yet): show the import prompt + clear panel.
    if (i < 0 || i >= state.scenes.length) {
      state.selected = -1;
      empty.style.display = "grid";
      $("#pvCaption").textContent = "";
      $("#shName").textContent = "No scene selected";
      $("#shDur").textContent = "—";
      const sh0 = $(".sh-thumb"); sh0.className = "sh-thumb"; sh0.innerHTML = "";
      renderScenes();
      return;
    }
    state.selected = i;
    const s = state.scenes[i];
    renderScenes();
    // preview: real image/video if present, else gradient
    const m = mediaById(s.mediaId);
    if (m && m.kind === "image") {
      img.src = m.url; img.style.display = "block";
    } else if (m && m.kind === "video") {
      vid.src = m.url; vid.style.display = "block";
    } else {
      frame.className = "pv-frame " + s.grad; frame.style.display = "block";
    }
    $("#pvCaption").textContent = s.caption;
    // right panel
    $("#shName").textContent = `${s.title} - ${s.name}`;
    $("#shDur").textContent = fmt(s.dur).slice(3);
    const sh = $(".sh-thumb");
    sh.className = "sh-thumb " + sceneThumbClass(s);
    sh.innerHTML = sceneThumbHTML(s);
    $("#kbToggle").checked = s.kenburns;
    $("#zoom").value = s.zoom; $("#zoomVal").textContent = s.zoom.toFixed(2);
    $("#pan").value = s.pan; $("#panVal").textContent = ["Slow", "Medium", "Fast"][s.pan];
    $("#dur").value = s.dur; $("#durVal").textContent = s.dur.toFixed(1) + "s";
  }

  function addSceneFromMedia(mid, silent) {
    const m = mediaById(mid);
    if (!m) return;
    if (m.kind === "audio") {
      state.audioId = mid;
      if (!silent) toast(`Using "${m.name}" as the audio track.`);
      return;
    }
    const n = state.scenes.length + 1;
    state.scenes.push({
      id: n, title: "Scene " + n, name: m.name, caption: m.name,
      narration: "", dur: Math.max(3, Math.min(10, m.dur || 5)),
      zoom: 1.12, pan: 0, kenburns: m.kind === "image",
      mediaId: mid, grad: GRADS[(n - 1) % 4],
    });
    renderScenes(); renderTimeline();
    if (!silent) { selectScene(state.scenes.length - 1); toast(`Added "${m.name}" as Scene ${n}.`); }
  }

  // ---- Interactions --------------------------------------------------
  function wire() {
    $$(".nav-item").forEach(n => n.onclick = () => {
      $$(".nav-item").forEach(x => x.classList.remove("active"));
      n.classList.add("active");
      const view = n.dataset.view;
      if (view === "models") { loadModels(); $("#modelsModal").classList.add("show"); }
    });
    $("#modelsClose").onclick = () => $("#modelsModal").classList.remove("show");
    $$("#mediaTabs .tab").forEach(t => t.onclick = () => {
      $$("#mediaTabs .tab").forEach(x => x.classList.remove("active"));
      t.classList.add("active"); state.mediaTab = t.dataset.tab; renderMedia();
    });
    $$("#propTabs .ptab").forEach(t => t.onclick = () => {
      $$("#propTabs .ptab").forEach(x => x.classList.remove("active"));
      t.classList.add("active");
    });
    $("#kbToggle").onchange = (e) => {
      const s = curScene(); if (!s) return;
      s.kenburns = e.target.checked;
      $("#kbSeg").style.opacity = e.target.checked ? "1" : ".45";
    };
    $$("#kbSeg .seg-btn").forEach(b => b.onclick = () => {
      const s = curScene(); if (!s) return;
      $$("#kbSeg .seg-btn").forEach(x => x.classList.remove("active"));
      b.classList.add("active");
      const kb = b.dataset.seg === "panzoom";
      s.kenburns = kb;
      $("#kbToggle").checked = kb;
    });
    const bindRange = (id, label, fn, store) => {
      $(id).oninput = (e) => {
        const v = parseFloat(e.target.value);
        $(label).textContent = fn(v);
        if (store) store(v);
      };
    };
    bindRange("#zoom", "#zoomVal", v => v.toFixed(2),
      v => { const s = curScene(); if (s) s.zoom = v; });
    bindRange("#pan", "#panVal", v => ["Slow", "Medium", "Fast"][v],
      v => { const s = curScene(); if (s) s.pan = v; });
    bindRange("#dur", "#durVal", v => v.toFixed(1) + "s", v => {
      const s = curScene(); if (!s) return;
      s.dur = v; renderTimeline(); renderScenes();
    });
    bindRange("#vspeed", "#vspeedVal", v => v.toFixed(1) + "x", v => state.vspeed = v);
    bindRange("#vpause", "#vpauseVal", v => v.toFixed(1) + "s", v => state.vpause = v);
    $("#subToggle").onchange = e => state.subtitles = e.target.checked;
    $("#subStyle").onchange = e => state.subStyle = e.target.value;
    $("#subSize").onchange = e => state.subSize = e.target.value;
    $("#expRes").onchange = e => state.exp.res = e.target.value;
    $("#expFps").onchange = e => state.exp.fps = e.target.value;
    $("#expCodec").onchange = e => state.exp.codec = e.target.value;
    $("#playBtn").onclick = togglePlay;
    $("#prevBtn").onclick = () => selectScene(Math.max(0, state.selected - 1));
    $("#nextBtn").onclick = () => selectScene(Math.min(state.scenes.length - 1, state.selected + 1));
    $("#importBtn").onclick = doImport;
    $("#addSceneBtn").onclick = doImport;
    $("#filePicker").onchange = onImportFiles;
    $("#testVoiceBtn").onclick = testVoice;
    $("#renderBtn").onclick = renderVideo;
    $("#exportBtn").onclick = renderVideo;
    // accept all media types in the picker
    $("#filePicker").setAttribute("accept", "image/*,video/*,audio/*");
  }

  let playTimer = null;
  function togglePlay() {
    state.playing = !state.playing;
    $("#playBtn").innerHTML = state.playing ? "&#10073;&#10073;" : "&#9654;";
    if (state.playing) {
      playTimer = setInterval(() => {
        state.t += 0.25;
        if (state.t >= totalDur()) { state.t = 0; }
        let acc = 0, idx = 0;
        for (let i = 0; i < state.scenes.length; i++) {
          acc += state.scenes[i].dur;
          if (state.t < acc) { idx = i; break; }
        }
        if (idx !== state.selected) selectScene(idx);
        updatePlayhead();
      }, 250);
    } else { clearInterval(playTimer); }
  }

  // ---- Import --------------------------------------------------------
  // Uses the native OS file dialog inside the desktop app (robust in the
  // app window); falls back to the HTML file input in a plain browser.
  const hasNative = () =>
    !!(window.pywebview && window.pywebview.api && window.pywebview.api.pick_files);

  async function doImport() {
    if (hasNative()) {
      let paths = [];
      try { paths = await window.pywebview.api.pick_files("all"); }
      catch (e) { paths = []; }
      if (!paths || !paths.length) return;
      showOverlay("Importing media…", `Adding ${paths.length} file(s)…`, true);
      try {
        const res = await api("/import_paths", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ paths }),
        });
        handleImported(res);
      } catch (err) { failOverlay("Import failed: " + err); }
    } else {
      $("#filePicker").click();     // browser fallback -> onImportFiles
    }
  }

  async function onImportFiles(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (!files.length) return;
    showOverlay("Importing media…", `Uploading ${files.length} file(s)…`, true);
    const fd = new FormData();
    files.forEach(f => fd.append("files", f));
    try {
      const res = await api("/upload", { method: "POST", body: fd });
      handleImported(res);
    } catch (err) { failOverlay("Upload failed: " + err); }
  }

  function handleImported(res) {
    let added = [], failed = 0;
    (res.files || []).forEach(f => {
      if (f.ok === false || !f.id) { failed++; return; }
      const m = { id: f.id, kind: f.kind, name: f.name, url: f.url,
        thumb: `/api/thumb/${f.id}`, w: f.w, h: f.h, dur: f.dur };
      state.media.push(m); added.push(m);
    });
    renderMedia();
    // Auto-add images/videos as scenes so they appear immediately in the
    // timeline and preview; audio becomes the narration/music track.
    added.forEach(m => {
      if (m.kind === "audio") { state.audioId = m.id; }
      else { addSceneFromMedia(m.id, true); }
    });
    hideOverlay();
    const firstVisual = added.find(m => m.kind !== "audio");
    if (firstVisual) {
      const idx = state.scenes.findIndex(s => s.mediaId === firstVisual.id);
      if (idx >= 0) selectScene(idx);
    }
    if (failed) toast(`Imported ${added.length}, skipped ${failed} unsupported.`);
  }

  // ---- Backend calls -------------------------------------------------
  async function loadBackend() {
    try {
      const hw = await api("/hardware");
      $("#cpuPct").textContent = (hw.cpu_pct ?? 0) + "%";
      $("#gpuPct").textContent = hw.has_gpu ? "active" : "0%";
      if (hw.render_ready)
        $("#cpuCard").querySelector("i").textContent =
          `Optimized for your system (${hw.cpu_name || "CPU"})`;
      $("#gpuCard").querySelector("i").textContent = hw.talking_head_blocker ||
        "Requires NVIDIA GPU (CUDA) and approved models.";
    } catch (e) {}
    try {
      const v = await api("/voices");
      state.voices = v.voices || [];
      $("#voiceSel").innerHTML = state.voices.length
        ? state.voices.map(x => `<option>${x}</option>`).join("")
        : `<option>Piper (none installed)</option>`;
    } catch (e) {}
  }

  async function testVoice() {
    const btn = $("#testVoiceBtn");
    const s = curScene();
    const sample = s ? (s.narration || s.caption) : "This is a NOVA voice preview.";
    btn.disabled = true; btn.textContent = "Testing…";
    try {
      const r = await api("/audition", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: sample, speed: state.vspeed }),
      });
      toast(r.ok ? "Voice sample ready." : ("Voice unavailable: " + (r.message || "")));
    } catch (e) { toast("Voice test failed."); }
    btn.disabled = false; btn.innerHTML = "&#9834; Test Voice";
  }

  async function renderVideo() {
    if (!state.scenes.length) {
      toast("Import at least one photo or video first, then press Render.");
      return;
    }
    showOverlay("Rendering video…", "Starting…", true);
    const payload = {
      project: state.project,
      scenes: state.scenes.map(s => ({
        media_id: s.mediaId, caption: s.caption,
        narration: s.narration || s.caption,
        duration_s: s.dur, motion: s.kenburns ? "kenburns" : "none",
      })),
      width: res2w(state.exp.res), height: res2h(state.exp.res),
      fps: parseInt(state.exp.fps), want_subtitles: state.subtitles,
      want_narration: state.voices.length > 0,
    };
    try {
      const start = await api("/render", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!start.job_id) return failOverlay(start.message || "Could not start render.");
      pollJob(start.job_id);
    } catch (e) { failOverlay("Render request failed: " + e); }
  }

  function pollJob(id) {
    const iv = setInterval(async () => {
      try {
        const j = await api("/job/" + id);
        setOverlay(j.stage || "Working…", (j.progress * 100) || 0);
        if (j.state === "completed") {
          clearInterval(iv);
          doneOverlay(j.output_url, j.output_path, j.has_audio, j.has_subtitles, j.duration_s);
        } else if (j.state === "failed") {
          clearInterval(iv);
          failOverlay(j.blocker || "Render failed.", j.fallback);
        }
      } catch (e) {}
    }, 700);
  }

  const res2w = r => ({ "HD 1080p": 1920, "HD 720p": 1280, "4K 2160p": 3840 }[r] || 1920);
  const res2h = r => ({ "HD 1080p": 1080, "HD 720p": 720, "4K 2160p": 2160 }[r] || 1080);

  // ---- Overlay -------------------------------------------------------
  function showOverlay(title, sub, spin) {
    $("#overlay").classList.add("show");
    $("#ovTitle").textContent = title;
    $("#ovSub").textContent = sub || "";
    $("#ovBar").style.width = "0%";
    $("#ovSpinner").classList.toggle("hide", !spin);
    $("#ovActions").innerHTML = "";
  }
  function setOverlay(stage, pct) {
    $("#ovSub").textContent = stage;
    $("#ovBar").style.width = Math.min(100, pct) + "%";
  }
  function doneOverlay(url, path, audio, subs, dur) {
    $("#ovSpinner").classList.add("hide");
    $("#ovTitle").textContent = "✓ Render complete";
    $("#ovSub").textContent = `Validated MP4 · ${dur ? dur.toFixed(1) + "s" : ""}` +
      (audio ? " · narration" : "") + (subs ? " · subtitles" : "");
    $("#ovBar").style.width = "100%";
    // Play the result inline in the preview (stays inside the app window).
    const vid = $("#pvVid"), img = $("#pvImg"), frame = $("#pvFrame"), empty = $("#pvEmpty");
    img.style.display = "none"; frame.style.display = "none"; empty.style.display = "none";
    vid.src = url; vid.controls = true; vid.style.display = "block";
    $("#ovActions").innerHTML =
      `<button class="btn primary" id="ovPlay">Play in preview</button>
       <button class="btn ghost" id="ovOpen">Open / Save…</button>
       <button class="btn ghost" id="ovClose">Close</button>`;
    $("#ovClose").onclick = hideOverlay;
    $("#ovPlay").onclick = () => { hideOverlay(); try { vid.play(); } catch (e) {} };
    $("#ovOpen").onclick = () => {
      // Open the finished file in the OS default player (native app), or fall
      // back to opening the stream URL in the browser build.
      if (window.pywebview && window.pywebview.api && window.pywebview.api.open_path && path) {
        window.pywebview.api.open_path(path);
      } else {
        window.location.href = url;
      }
    };
    $("#savedLabel").textContent = "Rendered just now";
  }
  function failOverlay(msg, fallback) {
    $("#ovSpinner").classList.add("hide");
    $("#ovTitle").textContent = "Render stopped";
    $("#ovSub").textContent = msg + (fallback ? "\n\nFallback: " + fallback : "");
    $("#ovBar").style.width = "0%";
    $("#ovActions").innerHTML = `<button class="btn ghost" id="ovClose">Close</button>`;
    $("#ovClose").onclick = hideOverlay;
  }
  function hideOverlay() { $("#overlay").classList.remove("show"); }
  function toast(msg) {
    showOverlay(msg, "", false);
    $("#ovActions").innerHTML = `<button class="btn ghost" id="ovClose">OK</button>`;
    $("#ovClose").onclick = hideOverlay;
  }

  // ---- AI Models -----------------------------------------------------
  let modelsPoll = null;
  async function loadModels() {
    try {
      const st = await api("/models/status");
      renderModels(st);
      // Poll while any model is downloading.
      const anyRunning = Object.values(st).some(m => m.state === "running");
      if (anyRunning && !modelsPoll) {
        modelsPoll = setInterval(async () => {
          const s2 = await api("/models/status");
          renderModels(s2);
          if (!Object.values(s2).some(m => m.state === "running")) {
            clearInterval(modelsPoll); modelsPoll = null;
            await api("/models/refresh", { method: "POST" });
            loadBackend();   // voices/readiness may have changed
          }
        }, 1200);
      }
    } catch (e) {
      $("#modelsList").innerHTML = `<div class="empty">Could not load model status.</div>`;
    }
  }

  function renderModels(st) {
    const order = ["script", "voice"];
    $("#modelsList").innerHTML = order.map(key => {
      const m = st[key]; if (!m) return "";
      const kindLabel = key === "script" ? "Script writer (LLM)" : "Narration voice";
      let right;
      if (m.installed) {
        right = `<span class="ok" style="font-weight:600">✓ Installed</span>`;
      } else if (m.state === "running") {
        right = `<div style="width:160px"><div class="ov-prog"><i style="width:${Math.round(m.progress*100)}%"></i></div>
                 <div class="mi-sub" style="margin-top:4px">${m.stage || "Downloading…"}</div></div>`;
      } else if (m.state === "failed") {
        right = `<button class="btn ghost sm" data-dl="${key}">Retry</button>`;
      } else {
        right = `<button class="btn primary sm" data-dl="${key}">Download (~${m.approx_mb} MB)</button>`;
      }
      const err = m.state === "failed" ? `<div class="mi-sub no">${m.message}</div>` : "";
      return `<div style="display:flex;justify-content:space-between;align-items:center;
                padding:12px 0;border-bottom:1px solid var(--line)">
        <div><div style="font-weight:600">${kindLabel}</div>
          <div class="mi-sub">${m.label} · ${m.runtime}</div>${err}</div>
        <div>${right}</div></div>`;
    }).join("") +
    `<div class="mi-sub" style="margin-top:12px">Files download to your NovaStudio
       models folder. Nothing is sent anywhere; downloads only fetch the model.</div>`;
    $$("#modelsList [data-dl]").forEach(b => b.onclick = () => downloadModel(b.dataset.dl));
  }

  async function downloadModel(key) {
    await api("/models/download", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    });
    loadModels();   // starts polling
  }

  // ---- Init ----------------------------------------------------------
  function init() {
    renderMedia();
    renderScenes();
    renderTimeline();
    selectScene(state.scenes.length ? 0 : -1);
    wire();
    loadBackend();
    loadModels();
    window.addEventListener("resize", updatePlayhead);
  }
  document.addEventListener("DOMContentLoaded", init);
})();
