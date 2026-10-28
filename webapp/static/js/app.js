/* NOVA Studio dashboard — working front-end wired to the local NOVA engine. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const api = (p, o) => fetch("/api" + p, o).then(r => r.json());

  const GRADS = ["grad-a", "grad-b", "grad-c", "grad-d"];

  // ---- App state -----------------------------------------------------
  const state = {
    project: "My First Video Project",
    scenes: [
      { id: 1, title: "Scene 1", name: "The Beginning", caption: "The journey begins…",
        dur: 10, zoom: 1.15, pan: 0, kenburns: true, grad: "grad-a" },
      { id: 2, title: "Scene 2", name: "The Journey", caption: "Exploring new places…",
        dur: 10, zoom: 1.2, pan: 1, kenburns: true, grad: "grad-b" },
      { id: 3, title: "Scene 3", name: "The Future", caption: "A brighter tomorrow…",
        dur: 10, zoom: 1.1, pan: 0, kenburns: true, grad: "grad-c" },
    ],
    photos: [
      { name: "scene_01.jpg", sub: "1920 × 1080", grad: "grad-a" },
      { name: "scene_02.jpg", sub: "1920 × 1080", grad: "grad-b" },
      { name: "scene_03.jpg", sub: "1920 × 1080", grad: "grad-c" },
    ],
    selected: 0,
    voice: "Piper (English)",
    vspeed: 1.0, vpause: 0.5,
    subtitles: true, subStyle: "Modern (White)", subSize: "Medium",
    exp: { res: "HD 1080p", fps: "30 fps", codec: "H.264 (MP4)" },
    playing: false, t: 7,
    hardware: null, voices: null,
  };

  const fmt = (s) => {
    s = Math.max(0, Math.round(s));
    const h = String(Math.floor(s / 3600)).padStart(2, "0");
    const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
    const ss = String(s % 60).padStart(2, "0");
    return `${h}:${m}:${ss}`;
  };
  const totalDur = () => state.scenes.reduce((a, s) => a + s.dur, 0);

  // ---- Renderers -----------------------------------------------------
  function renderMedia(tab) {
    const el = $("#mediaList");
    if (tab === "photos") {
      el.innerHTML = state.photos.map(p => `
        <div class="media-item">
          <div class="mi-thumb ${p.grad}"></div>
          <div><div class="mi-name">${p.name}</div><div class="mi-sub">${p.sub}</div></div>
        </div>`).join("");
    } else if (tab === "audio") {
      el.innerHTML = `<div class="empty">No audio imported.<br>Narration is generated per scene by Voice Studio.</div>`;
    } else {
      el.innerHTML = `<div class="empty">No video clips imported.<br>Use Import to add footage.</div>`;
    }
  }

  function renderScenes() {
    $("#sceneCount").textContent = state.scenes.length;
    $("#cpScenes").textContent = state.scenes.length + " scenes";
    $("#cpDur").textContent = fmt(totalDur());
    $("#sceneList").innerHTML = state.scenes.map((s, i) => `
      <div class="scene-card ${i === state.selected ? "active" : ""}" data-i="${i}">
        <div class="sc-num">${s.id}</div>
        <div class="sc-thumb ${s.grad}"></div>
        <div><div class="sc-name">${s.title}</div><div class="sc-sub">${s.name}</div></div>
        <div class="sc-dur">${fmt(s.dur).slice(3)}</div>
      </div>`).join("");
    $$("#sceneList .scene-card").forEach(c =>
      c.onclick = () => selectScene(+c.dataset.i));
  }

  function renderTimeline() {
    const total = totalDur();
    // ruler
    const ruler = $("#tlRuler"); ruler.innerHTML = "";
    for (let s = 0; s <= total; s += 5) {
      const d = document.createElement("div");
      d.className = "tick"; d.style.left = (s / total * 100) + "%";
      d.textContent = fmt(s).slice(3);
      ruler.appendChild(d);
    }
    // video clips
    $("#trackVideo").innerHTML = state.scenes.map(s => `
      <div class="tl-clip ${s.grad}" style="flex:${s.dur}">
        <span class="cl-name">${s.title}</span></div>`).join("");
    // audio waveform bars
    const bars = Array.from({ length: 80 }, () =>
      `<i style="height:${20 + Math.abs(Math.sin(Math.random() * 6)) * 70}%"></i>`).join("");
    $("#waveform").outerHTML = `<div class="wave-bars" id="waveform">${bars}</div>`;
    // subtitles
    $("#trackSubs").innerHTML = state.scenes.map(s =>
      `<div class="sub-block" style="flex:${s.dur}">${s.caption}</div>`).join("");
    // transitions (diamond at each scene boundary)
    const tr = $("#trackTrans"); tr.innerHTML = "";
    let acc = 0;
    state.scenes.slice(0, -1).forEach(s => {
      acc += s.dur;
      const d = document.createElement("div");
      d.className = "trans-diamond";
      d.style.position = "absolute";
      d.style.left = (acc / total * 100) + "%";
      d.style.top = "50%"; d.style.transform = "translate(-50%,-50%) rotate(45deg)";
      tr.appendChild(d);
    });
    $("#totTime").textContent = fmt(total);
    updatePlayhead();
  }

  function updatePlayhead() {
    const total = totalDur();
    const frac = Math.min(1, state.t / total);
    const trackLeft = 150;
    const w = $(".tl-body").clientWidth - trackLeft;
    $("#playhead").style.left = (trackLeft + frac * w) + "px";
    $("#curTime").textContent = fmt(state.t);
  }

  function selectScene(i) {
    state.selected = i;
    const s = state.scenes[i];
    renderScenes();
    // preview
    $("#pvFrame").className = "pv-frame " + s.grad;
    $("#pvCaption").textContent = s.caption;
    // right panel
    $("#shName").textContent = `${s.title} - ${s.name}`;
    $("#shDur").textContent = fmt(s.dur).slice(3);
    $(".sh-thumb").className = "sh-thumb " + s.grad;
    $("#kbToggle").checked = s.kenburns;
    $("#zoom").value = s.zoom; $("#zoomVal").textContent = s.zoom.toFixed(2);
    $("#pan").value = s.pan; $("#panVal").textContent = ["Slow", "Medium", "Fast"][s.pan];
    $("#dur").value = s.dur; $("#durVal").textContent = s.dur.toFixed(1) + "s";
    $(".pos-thumb.grad-b, .pos-row .pos:first-child .pos-thumb").className =
      "pos-thumb " + s.grad;
  }

  // ---- Interactions --------------------------------------------------
  function wire() {
    // left nav
    $$(".nav-item").forEach(n => n.onclick = () => {
      $$(".nav-item").forEach(x => x.classList.remove("active"));
      n.classList.add("active");
    });
    // media tabs
    $$("#mediaTabs .tab").forEach(t => t.onclick = () => {
      $$("#mediaTabs .tab").forEach(x => x.classList.remove("active"));
      t.classList.add("active"); renderMedia(t.dataset.tab);
    });
    // prop tabs (just visual focus; all panels are shown in this layout)
    $$("#propTabs .ptab").forEach(t => t.onclick = () => {
      $$("#propTabs .ptab").forEach(x => x.classList.remove("active"));
      t.classList.add("active");
    });
    // Ken Burns toggle + segment
    $("#kbToggle").onchange = (e) => {
      state.scenes[state.selected].kenburns = e.target.checked;
      $("#kbSeg").style.opacity = e.target.checked ? "1" : ".45";
    };
    $$("#kbSeg .seg-btn").forEach(b => b.onclick = () => {
      $$("#kbSeg .seg-btn").forEach(x => x.classList.remove("active"));
      b.classList.add("active");
      const kb = b.dataset.seg === "panzoom";
      state.scenes[state.selected].kenburns = kb;
      $("#kbToggle").checked = kb;
    });
    // sliders -> live labels + state
    const bindRange = (id, label, fn, store) => {
      $(id).oninput = (e) => {
        const v = parseFloat(e.target.value);
        $(label).textContent = fn(v);
        if (store) store(v);
      };
    };
    bindRange("#zoom", "#zoomVal", v => v.toFixed(2),
      v => state.scenes[state.selected].zoom = v);
    bindRange("#pan", "#panVal", v => ["Slow", "Medium", "Fast"][v],
      v => state.scenes[state.selected].pan = v);
    bindRange("#dur", "#durVal", v => v.toFixed(1) + "s", v => {
      state.scenes[state.selected].dur = v; renderTimeline(); renderScenes();
    });
    bindRange("#vspeed", "#vspeedVal", v => v.toFixed(1) + "x",
      v => state.vspeed = v);
    bindRange("#vpause", "#vpauseVal", v => v.toFixed(1) + "s",
      v => state.vpause = v);
    // subtitles
    $("#subToggle").onchange = e => state.subtitles = e.target.checked;
    $("#subStyle").onchange = e => state.subStyle = e.target.value;
    $("#subSize").onchange = e => state.subSize = e.target.value;
    // export selects
    $("#expRes").onchange = e => state.exp.res = e.target.value;
    $("#expFps").onchange = e => state.exp.fps = e.target.value;
    $("#expCodec").onchange = e => state.exp.codec = e.target.value;
    // transport
    $("#playBtn").onclick = togglePlay;
    $("#prevBtn").onclick = () => selectScene(Math.max(0, state.selected - 1));
    $("#nextBtn").onclick = () => selectScene(Math.min(state.scenes.length - 1, state.selected + 1));
    // import
    $("#importBtn").onclick = () => $("#filePicker").click();
    $("#addSceneBtn").onclick = addScene;
    $("#filePicker").onchange = onImport;
    // actions
    $("#testVoiceBtn").onclick = testVoice;
    $("#renderBtn").onclick = renderVideo;
    $("#exportBtn").onclick = renderVideo;
  }

  let playTimer = null;
  function togglePlay() {
    state.playing = !state.playing;
    $("#playBtn").innerHTML = state.playing ? "&#10073;&#10073;" : "&#9654;";
    if (state.playing) {
      playTimer = setInterval(() => {
        state.t += 0.25;
        if (state.t >= totalDur()) { state.t = 0; }
        // move selected scene to match playhead
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

  function addScene() {
    const n = state.scenes.length + 1;
    state.scenes.push({
      id: n, title: "Scene " + n, name: "New scene", caption: "New scene…",
      dur: 8, zoom: 1.1, pan: 0, kenburns: true, grad: GRADS[(n - 1) % 4],
    });
    renderScenes(); renderTimeline();
  }

  function onImport(e) {
    const files = Array.from(e.target.files || []);
    files.forEach((f, i) => {
      state.photos.push({
        name: f.name, sub: "imported", grad: GRADS[(state.photos.length) % 4],
      });
    });
    renderMedia("photos");
    toast(`Imported ${files.length} photo(s).`);
  }

  // ---- Backend calls -------------------------------------------------
  async function loadBackend() {
    try {
      const hw = await api("/hardware");
      state.hardware = hw;
      $("#cpuPct").textContent = (hw.cpu_pct ?? 42) + "%";
      $("#gpuPct").textContent = hw.has_gpu ? "active" : "0%";
      // status cards reflect real capability
      if (hw.render_ready) {
        $("#cpuCard").querySelector("i").textContent =
          `Optimized for your system (${hw.cpu_name || "CPU"})`;
      }
      $("#gpuCard").querySelector("i").textContent = hw.talking_head_blocker ||
        "Requires NVIDIA GPU (CUDA) and approved models.";
    } catch (e) { /* offline preview: keep defaults */ }
    try {
      const v = await api("/voices");
      state.voices = v;
      if (v.voices && v.voices.length) {
        $("#voiceSel").innerHTML = v.voices.map(x =>
          `<option>${x}</option>`).join("");
      } else {
        $("#voiceSel").innerHTML = `<option>Piper (none installed)</option>`;
      }
    } catch (e) { /* keep default */ }
  }

  async function testVoice() {
    const btn = $("#testVoiceBtn");
    btn.disabled = true; btn.textContent = "Testing…";
    try {
      const r = await api("/audition", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: state.scenes[state.selected].caption,
          speed: state.vspeed }),
      });
      toast(r.ok ? "Voice sample ready." : ("Voice unavailable: " + (r.message || "")));
    } catch (e) { toast("Voice test failed."); }
    btn.disabled = false; btn.innerHTML = "&#9834; Test Voice";
  }

  async function renderVideo() {
    showOverlay("Rendering video…", "Starting…", true);
    const payload = {
      project: state.project,
      scenes: state.scenes.map(s => ({
        caption: s.caption, narration: s.caption,
        duration_s: s.dur, motion: s.kenburns ? "kenburns" : "none",
      })),
      width: res2w(state.exp.res), height: res2h(state.exp.res),
      fps: parseInt(state.exp.fps), want_subtitles: state.subtitles,
      want_narration: true,
    };
    try {
      const start = await api("/render", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!start.job_id) { return failOverlay(start.message || "Could not start render."); }
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
          doneOverlay(j.output_url, j.has_audio, j.has_subtitles, j.duration_s);
        } else if (j.state === "failed") {
          clearInterval(iv);
          failOverlay(j.blocker || "Render failed.", j.fallback);
        }
      } catch (e) { /* keep polling */ }
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
  function doneOverlay(url, audio, subs, dur) {
    $("#ovSpinner").classList.add("hide");
    $("#ovTitle").textContent = "✓ Render complete";
    $("#ovSub").textContent =
      `Validated MP4 · ${dur ? dur.toFixed(1) + "s" : ""}` +
      (audio ? " · narration" : "") + (subs ? " · subtitles" : "");
    $("#ovBar").style.width = "100%";
    $("#ovActions").innerHTML =
      `<a class="btn primary" href="${url}" target="_blank">Open video</a>
       <button class="btn ghost" id="ovClose">Close</button>`;
    $("#ovClose").onclick = hideOverlay;
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
  function toast(msg) { showOverlay(msg, "", false);
    $("#ovActions").innerHTML = `<button class="btn ghost" id="ovClose">OK</button>`;
    $("#ovClose").onclick = hideOverlay; }

  // ---- Init ----------------------------------------------------------
  function init() {
    renderMedia("photos");
    renderScenes();
    renderTimeline();
    selectScene(0);
    wire();
    loadBackend();
    window.addEventListener("resize", updatePlayhead);
  }
  document.addEventListener("DOMContentLoaded", init);
})();
