/* NOVA Studio dashboard — front-end logic.
 *
 * Talks to the Python backend through pywebview's `window.pywebview.api`
 * (the NovaApi class in src/nova_studio/desktop.py). When opened in a plain
 * browser for preview, a mock API stands in so the UI stays interactive.
 */
(function () {
  "use strict";

  // ---- backend bridge (pywebview) with a browser mock fallback ----------
  const MockApi = {
    async hardware() {
      return { summary: "Preview mode (no backend) · CPU-only",
               cpu: "Preview CPU", ram_gb: 16, has_cuda: false,
               cpu_pct: 42, gpu_pct: 0 };
    },
    async voices() { return { engines: [{ id: "piper", name: "Piper (English)", available: true }] }; },
    async import_photos() { return { ok: false, message: "Preview mode: import runs in the installed app." }; },
    async render() {
      return { ok: false, message: "Preview mode: rendering runs in the installed app." };
    },
    async job_status() { return { state: "idle" }; },
    async test_voice() { return { ok: false, message: "Preview mode." }; },
  };

  function api() {
    return (window.pywebview && window.pywebview.api) ? window.pywebview.api : MockApi;
  }

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  // ---- app state --------------------------------------------------------
  const state = {
    scene: 0,
    scenes: [
      { name: "Scene 1", sub: "The Beginning", dur: 10, thumb: "t1", caption: "The journey begins…", narration: "The journey begins." },
      { name: "Scene 2", sub: "The Journey", dur: 10, thumb: "t2", caption: "Exploring new places…", narration: "Exploring new places." },
      { name: "Scene 3", sub: "The Future", dur: 10, thumb: "t3", caption: "A brighter tomorrow…", narration: "A brighter tomorrow." },
    ],
    kenBurns: true, kbMode: "pan", zoom: 1.15, pan: 0, dur: 10,
    voice: "Piper (English)", vSpeed: 1.0, vPause: 0.5,
    subsOn: true, subStyle: "Modern (White)", subSize: "Medium",
    res: "HD 1080p", fps: "30 fps", codec: "H.264 (MP4)",
    playing: false, t: 7, rendering: false,
  };

  function toast(msg, ms = 2600) {
    const el = $("#toast"); el.textContent = msg; el.classList.add("show");
    clearTimeout(toast._t); toast._t = setTimeout(() => el.classList.remove("show"), ms);
  }

  // ---- waveform bars ----------------------------------------------------
  function buildWave() {
    const w = $("#waveTrack"); if (!w) return;
    let h = "";
    for (let i = 0; i < 90; i++) {
      const v = 18 + Math.abs(Math.sin(i * 0.5) * Math.cos(i * 0.17)) * 70
                + (Math.random() * 14);
      h += `<i style="height:${Math.min(96, v)}%"></i>`;
    }
    w.innerHTML = h;
  }

  // ---- timeline ruler ---------------------------------------------------
  function buildRuler() {
    const r = $("#tlRuler"); if (!r) return;
    const total = state.scenes.reduce((a, s) => a + s.dur, 0);
    let h = "";
    for (let s = 0; s <= total; s += 5) {
      h += `<span style="left:${(s / total) * 100}%">${mmss(s)}</span>`;
    }
    r.innerHTML = h;
  }
  const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.round(s % 60)).padStart(2, "0")}`;
  const hhmmss = (s) => `00:${mmss(s)}`;

  // ---- nav --------------------------------------------------------------
  $$(".nav-item").forEach(n => n.addEventListener("click", () => {
    $$(".nav-item").forEach(x => x.classList.remove("active"));
    n.classList.add("active");
    toast(`${n.textContent.trim()} view`);
  }));

  // ---- media tabs -------------------------------------------------------
  $$("#mediaTabs .tab").forEach(t => t.addEventListener("click", () => {
    $$("#mediaTabs .tab").forEach(x => x.classList.remove("active"));
    t.classList.add("active");
  }));

  // ---- properties tabs --------------------------------------------------
  $$("#propTabs .ptab").forEach(t => t.addEventListener("click", () => {
    $$("#propTabs .ptab").forEach(x => x.classList.remove("active"));
    t.classList.add("active");
  }));

  // ---- scene selection --------------------------------------------------
  function selectScene(i) {
    state.scene = i;
    $$(".scene-card").forEach(c => c.classList.toggle("active", +c.dataset.scene === i));
    const sc = state.scenes[i];
    $("#propSceneName").textContent = `${sc.name} - ${sc.sub}`;
    $$(".sh-thumb").forEach(e => e.className = "sh-thumb " + sc.thumb);
    $("#dur").value = sc.dur; $("#durVal").textContent = sc.dur.toFixed(1) + "s";
    $(".pp-scene").className = "pp-scene " + sc.thumb;
  }
  $$(".scene-card").forEach(c =>
    c.addEventListener("click", () => selectScene(+c.dataset.scene)));

  // ---- Ken Burns + sliders ---------------------------------------------
  $("#kenBurns").addEventListener("change", e => {
    state.kenBurns = e.target.checked;
    toast("Ken Burns " + (state.kenBurns ? "on" : "off"));
  });
  $$("#kbMode .seg-btn").forEach(b => b.addEventListener("click", () => {
    $$("#kbMode .seg-btn").forEach(x => x.classList.remove("active"));
    b.classList.add("active"); state.kbMode = b.dataset.kb;
  }));
  bindRange("#zoom", "#zoomVal", v => { state.zoom = +v; return (+v).toFixed(2); });
  bindRange("#pan", "#panVal", v => { state.pan = +v; return ["Slow", "Medium", "Fast"][+v]; });
  bindRange("#dur", "#durVal", v => {
    state.dur = +v; state.scenes[state.scene].dur = +v; buildRuler();
    return (+v).toFixed(1) + "s";
  });
  bindRange("#vSpeed", "#vSpeedVal", v => { state.vSpeed = +v; return (+v).toFixed(1) + "x"; });
  bindRange("#vPause", "#vPauseVal", v => { state.vPause = +v; return (+v).toFixed(1) + "s"; });

  function bindRange(sel, lblSel, fmt) {
    const el = $(sel), lbl = $(lblSel);
    if (!el) return;
    el.addEventListener("input", () => { lbl.textContent = fmt(el.value); });
  }

  // ---- selects ----------------------------------------------------------
  bindSelect("#voiceSel", v => state.voice = v);
  bindSelect("#subStyle", v => state.subStyle = v);
  bindSelect("#subSize", v => state.subSize = v);
  bindSelect("#expRes", v => state.res = v);
  bindSelect("#expFps", v => state.fps = v);
  bindSelect("#expCodec", v => state.codec = v);
  $("#subsOn").addEventListener("change", e => state.subsOn = e.target.checked);
  function bindSelect(sel, set) {
    const el = $(sel); if (el) el.addEventListener("change", () => set(el.value));
  }

  // ---- transport (preview playback UI) ---------------------------------
  const total = () => state.scenes.reduce((a, s) => a + s.dur, 0);
  function updateTime() {
    $("#curTime").textContent = hhmmss(state.t);
    $("#totTime").textContent = hhmmss(total());
    const pct = (state.t / total()) * 100;
    $("#scrubFill").style.width = pct + "%";
    $(".scrub-knob").style.left = pct + "%";
    $("#tlPlayhead").style.left = `calc(130px + (100% - 130px) * ${state.t / total()})`;
  }
  $("#playBtn").addEventListener("click", togglePlay);
  function togglePlay() {
    state.playing = !state.playing;
    $("#playBtn").textContent = state.playing ? "⏸" : "▶";
    if (state.playing) tick();
  }
  function tick() {
    if (!state.playing) return;
    state.t += 0.1;
    if (state.t >= total()) { state.t = 0; state.playing = false; $("#playBtn").textContent = "▶"; }
    updateTime();
    if (state.playing) setTimeout(tick, 100);
  }
  $("#prevBtn").addEventListener("click", () => { state.t = 0; updateTime(); });
  $("#nextBtn").addEventListener("click", () => { state.t = total(); updateTime(); });

  // ---- import, test voice, export, render ------------------------------
  $("#importBtn").addEventListener("click", async () => {
    toast("Opening file picker…");
    const r = await api().import_photos();
    toast(r.ok ? `Imported ${r.count || ""} file(s)` : r.message);
  });
  $("#testVoice").addEventListener("click", async () => {
    toast("Synthesising preview…");
    const r = await api().test_voice({ text: "This is a NOVA voice preview.",
      speed: state.vSpeed });
    toast(r.ok ? "Voice preview ready" : r.message);
  });
  $("#exportBtn").addEventListener("click", () => doRender(true));
  $("#renderBtn").addEventListener("click", () => doRender(false));

  async function doRender(exportOnly) {
    if (state.rendering) { toast("A render is already running."); return; }
    state.rendering = true;
    const btn = $("#renderBtn"); const old = btn.innerHTML;
    btn.innerHTML = "⏳ Rendering…"; btn.classList.add("dis");
    $("#savedLabel").textContent = "Rendering…";
    toast("Rendering video…");
    try {
      const payload = {
        scenes: state.scenes.map(s => ({
          caption: s.caption, narration: s.narration, duration_s: s.dur,
          motion: state.kenBurns ? "kenburns" : "none", thumb: s.thumb,
        })),
        want_narration: true, want_subtitles: state.subsOn,
        voice: state.voice, speed: state.vSpeed, pause: state.vPause,
        resolution: state.res, fps: state.fps, codec: state.codec,
      };
      const r = await api().render(payload);
      if (r.ok) {
        $("#savedLabel").textContent = "Rendered ✓";
        toast("Render complete — " + (r.output || "video ready"));
        if (r.video_url) playOutput(r.video_url);
      } else {
        $("#savedLabel").textContent = "Render blocked";
        toast(r.message || "Render failed.");
      }
    } catch (e) {
      toast("Render error: " + e);
    } finally {
      state.rendering = false; btn.innerHTML = old; btn.classList.remove("dis");
    }
  }

  function playOutput(url) {
    const v = $("#previewVideo");
    v.src = url; v.classList.add("on");
    $("#previewPlaceholder").style.display = "none";
    v.play().catch(() => {});
  }

  // ---- hardware / voices refresh from backend --------------------------
  async function refreshStatus() {
    try {
      const hw = await api().hardware();
      if (hw.cpu_pct != null) $("#cpuPct").textContent = hw.cpu_pct + "%";
      if (hw.gpu_pct != null) $("#gpuPct").textContent = hw.gpu_pct + "%";
      // Honest talking-head card: supported only with CUDA.
      const gpuCard = $("#gpuCard");
      if (hw.has_cuda) {
        gpuCard.className = "status-card ok";
        $(".sc-ic", gpuCard).textContent = "✓";
        $(".sc-title", gpuCard).textContent = "Talking-head generation ready";
        $(".sc-sub", gpuCard).textContent = "Compatible NVIDIA GPU detected.";
      }
    } catch (e) { /* preview mode */ }
  }

  function boot() {
    buildWave(); buildRuler(); updateTime(); selectScene(0); refreshStatus();
  }
  // pywebview injects the API slightly after load.
  if (window.pywebview && window.pywebview.api) boot();
  else { window.addEventListener("pywebviewready", boot); boot(); }
})();
