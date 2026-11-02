/* NOVA Studio GitHub release updater and Settings navigation. */
(() => {
  "use strict";
  const APP_VERSION = "0.1.0";
  const RELEASE_API = "https://api.github.com/repos/souravg77/nova-ai-video-studio/releases/latest";
  const RELEASES_PAGE = "https://github.com/souravg77/nova-ai-video-studio/releases";
  const $ = (selector) => document.querySelector(selector);

  function versionParts(value) {
    const match = String(value || "").match(/[0-9]+(?:\.[0-9]+)*/);
    return match ? match[0].split(".").map(Number) : [];
  }

  function isNewer(latest, current) {
    const a = versionParts(latest), b = versionParts(current);
    if (!a.length || !b.length) return false;
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      const x = a[i] || 0, y = b[i] || 0;
      if (x !== y) return x > y;
    }
    return false;
  }

  function settingsPage() {
    const title = $("#pageTitle"), body = $("#pageBody"), modal = $("#pageModal");
    if (!title || !body || !modal) return;
    title.textContent = "Settings";
    body.innerHTML = `
      <section class="settings-section">
        <h3>Application updates</h3>
        <p class="fl2">Installed version: <b>v${APP_VERSION}</b></p>
        <div id="updateStatus" class="update-status" role="status">Check GitHub for the latest NOVA Studio release.</div>
        <div class="settings-actions">
          <button class="btn ghost sm" id="checkUpdatesBtn">Check for updates</button>
          <button class="btn primary sm" id="downloadUpdateBtn" style="display:none">Download installer</button>
          <a class="btn ghost sm" id="releasePageBtn" href="${RELEASES_PAGE}" target="_blank" rel="noopener">GitHub releases</a>
        </div>
        <p class="fl2" style="margin-top:12px">Updates are distributed as signed/release installer downloads. Close NOVA Studio before running the installer. Your projects and models remain in your user data folder.</p>
      </section>
      <section class="settings-section">
        <h3>About</h3>
        <p class="fl2">NOVA AI Video Studio · v${APP_VERSION}</p>
      </section>`;
    modal.classList.add("show");

    const status = $("#updateStatus");
    const check = $("#checkUpdatesBtn");
    const download = $("#downloadUpdateBtn");
    let releaseUrl = RELEASES_PAGE;

    async function checkForUpdates() {
      check.disabled = true;
      download.style.display = "none";
      status.textContent = "Checking GitHub releases…";
      try {
        const response = await fetch(RELEASE_API, {
          headers: { Accept: "application/vnd.github+json" },
          cache: "no-store",
        });
        if (response.status === 404) {
          status.textContent = "No published release found yet. Check GitHub releases for new versions.";
          return;
        }
        if (!response.ok) throw new Error(`GitHub returned HTTP ${response.status}`);
        const release = await response.json();
        const tag = release.tag_name || "";
        releaseUrl = (release.html_url || RELEASES_PAGE);
        const newer = isNewer(tag, APP_VERSION);
        status.textContent = newer
          ? `New version ${tag} is available (installed: v${APP_VERSION}). Close NOVA Studio before installing the update.`
          : `You’re up to date (latest release: ${tag || "unknown"}; installed: v${APP_VERSION}).`;
        const asset = (release.assets || []).find(item => item.name === "NOVA-Setup.exe");
        if (newer && asset && /^https:\/\/github\.com\//i.test(asset.browser_download_url || "")) {
          download.dataset.url = asset.browser_download_url;
          download.style.display = "inline-flex";
        } else if (newer) {
          status.textContent += " No NOVA-Setup.exe asset was attached; open the release page to download or build it.";
        }
      } catch (error) {
        status.textContent = `Could not check GitHub: ${error.message}. Check your internet connection and try again.`;
      } finally {
        check.disabled = false;
      }
    }

    check.onclick = checkForUpdates;
    download.onclick = () => {
      const url = download.dataset.url;
      if (!url || !url.startsWith("https://github.com/")) return;
      if (window.pywebview?.api?.open_url) {
        window.pywebview.api.open_url(url);
      } else {
        window.open(url, "_blank", "noopener");
      }
      status.textContent = "The installer is opening in your browser. Close NOVA Studio before running it.";
    };
    $("#releasePageBtn").onclick = (event) => {
      event.preventDefault();
      if (window.pywebview?.api?.open_url) window.pywebview.api.open_url(releaseUrl);
      else window.open(releaseUrl, "_blank", "noopener");
    };
    checkForUpdates();
  }

  document.addEventListener("DOMContentLoaded", () => {
    const rail = document.querySelector(".rail");
    const nav = document.querySelector(".nav");
    if (!rail || !nav) return;
    rail.style.display = "flex";
    rail.style.flexDirection = "column";
    const item = document.createElement("li");
    item.className = "nav-item settings-nav-item";
    item.innerHTML = '<span class="ni">&#9881;</span> Settings';
    item.title = "Settings and application updates";
    item.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach(element => element.classList.remove("active"));
      item.classList.add("active");
      settingsPage();
    });
    rail.appendChild(item);
  });
})();
