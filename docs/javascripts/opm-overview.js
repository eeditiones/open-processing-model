/* Interactive controls for the animated SVGs in the docs
 * (docs/images/opm-overview.svg, docs/images/opm-family.svg).
 *
 * Markup: <div class="opm-overview"><img src="…/opm-overview.svg" alt="…"></div>
 * Any number of these can be on one page. The SVG must carry data-scenes and
 * data-durations, mark its steps with data-scene and its progress bar with
 * data-role="progress" (see scripts/gen_overview_svg.py).
 *
 * The <img> is the fallback: it plays on its own but cannot be paused. This
 * script swaps it for the inline SVG and drives the SVG's CSS animations through
 * the Web Animations API, adding play/pause and previous/next buttons.
 *
 * Keyboard (when the figure has focus):
 *   Space or K   pause / play
 *   ← / →        previous / next step
 *   1 … 5        jump to a step
 *   Home / End   first / last step
 *   F            fullscreen on / off (where the browser supports it)
 * The step pills at the top of the SVG can be clicked as well.
 * With prefers-reduced-motion the animation starts paused.
 */
(function () {
  const ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';
  const ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>';
  const ICON_PREV = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.41 16.59 10.83 12l4.58-4.59L14 6l-6 6 6 6z"/></svg>';
  const ICON_FULL = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 14H5v5h5v-2H7zm-2-4h2V7h3V5H5zm12 7h-3v2h5v-5h-2zM14 5v2h3v3h2V5z"/></svg>';
  const ICON_EXIT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 16h3v3h2v-5H5zm3-8H5v2h5V5H8zm6 11h2v-3h3v-2h-5zm2-11V5h-2v5h5V8z"/></svg>';
  const ICON_NEXT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.59 16.59 13.17 12 8.59 7.41 10 6l6 6-6 6z"/></svg>';

  function button(cls, label, icon) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "opm-overview__btn " + cls;
    b.setAttribute("aria-label", label);
    b.title = label;
    b.innerHTML = icon;
    return b;
  }

  async function init(host) {
    if (host.dataset.ready) return;
    host.dataset.ready = "1";
    const img = host.querySelector("img");
    const src = host.dataset.src || (img && img.src);
    if (!src) return;

    let svg;
    try {
      const res = await fetch(src);
      if (!res.ok) return;
      const doc = new DOMParser().parseFromString(await res.text(), "image/svg+xml");
      if (doc.querySelector("parsererror")) return;
      svg = document.importNode(doc.documentElement, true);
    } catch (e) {
      return; // keep the <img>
    }
    if (typeof svg.getAnimations !== "function") return;

    svg.classList.add("opm-ov-js");
    svg.setAttribute("focusable", "false");

    const starts = svg.dataset.scenes.split(",").map(Number);
    const durs = svg.dataset.durations.split(",").map(Number);
    const total = durs.reduce((a, b) => a + b, 0);
    const steps = Array.from(svg.querySelectorAll("[data-scene]"));
    const labels = steps.map((s) => s.dataset.label);
    const count = starts.length;

    // controls
    const bar = document.createElement("div");
    bar.className = "opm-overview__controls";
    const prev = button("opm-overview__prev", "Previous step", ICON_PREV);
    const toggle = button("opm-overview__toggle", "Pause", ICON_PAUSE);
    const next = button("opm-overview__next", "Next step", ICON_NEXT);
    const status = document.createElement("span");
    status.className = "opm-overview__status";
    status.setAttribute("aria-live", "polite");
    const hint = document.createElement("span");
    hint.className = "opm-overview__hint";
    hint.textContent = "Space: pause · ← →: steps";
    const canFull = !!(host.requestFullscreen || host.webkitRequestFullscreen);
    const full = button("opm-overview__full", "Fullscreen", ICON_FULL);
    bar.append(prev, toggle, next);
    if (canFull) bar.append(full);
    bar.append(status, hint);
    if (canFull) hint.textContent += " · F: fullscreen";

    host.replaceChildren(svg, bar);
    host.tabIndex = 0;
    host.setAttribute("role", "group");
    host.setAttribute("aria-roledescription", "animation");
    host.setAttribute("aria-label", (svg.querySelector("title") || {}).textContent || "Animation");

    const anims = () => svg.getAnimations({ subtree: true });
    let playing = true;

    function time() {
      const p = svg.querySelector('[data-role="progress"]');
      const a = p && p.getAnimations()[0];
      const t = a && a.currentTime != null ? a.currentTime / 1000 : 0;
      return ((t % total) + total) % total;
    }

    function sceneAt(t) {
      let i = 0;
      while (i + 1 < count && t >= starts[i + 1]) i++;
      return i;
    }

    function seek(t) {
      anims().forEach((a) => { a.currentTime = t * 1000; });
    }

    function update(announce) {
      toggle.innerHTML = playing ? ICON_PAUSE : ICON_PLAY;
      toggle.setAttribute("aria-label", playing ? "Pause" : "Play");
      toggle.title = playing ? "Pause" : "Play";
      const i = sceneAt(time());
      const text = `Step ${i + 1} of ${count}: ${labels[i] || ""}${playing ? "" : " (paused)"}`;
      if (announce) status.textContent = text;
      else status.dataset.text = text;
    }

    function setPlaying(on) {
      playing = on;
      anims().forEach((a) => (on ? a.play() : a.pause()));
      update(true);
    }

    function go(i) {
      i = ((i % count) + count) % count;
      // Playing: start the step from its beginning. Paused: show it fully built.
      seek(playing ? starts[i] + 0.01 : starts[i] + durs[i] - 0.6);
      update(true);
    }

    const fsElement = () => document.fullscreenElement || document.webkitFullscreenElement;
    function toggleFullscreen() {
      if (fsElement() === host) (document.exitFullscreen || document.webkitExitFullscreen).call(document);
      else (host.requestFullscreen || host.webkitRequestFullscreen).call(host);
    }
    function onFullscreenChange() {
      const on = fsElement() === host;
      full.innerHTML = on ? ICON_EXIT : ICON_FULL;
      full.setAttribute("aria-label", on ? "Exit fullscreen" : "Fullscreen");
      full.title = on ? "Exit fullscreen" : "Fullscreen";
      if (on) host.focus({ preventScroll: true });
    }
    document.addEventListener("fullscreenchange", onFullscreenChange);
    document.addEventListener("webkitfullscreenchange", onFullscreenChange);
    full.addEventListener("click", toggleFullscreen);

    toggle.addEventListener("click", () => setPlaying(!playing));
    prev.addEventListener("click", () => go(sceneAt(time()) - 1));
    next.addEventListener("click", () => go(sceneAt(time()) + 1));
    steps.forEach((s, i) => s.addEventListener("click", () => { go(i); host.focus({ preventScroll: true }); }));

    host.addEventListener("keydown", (e) => {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.target !== host && e.target.closest("button") && (e.key === " " || e.key === "Enter")) return;
      const k = e.key;
      if (k === " " || k === "k" || k === "K") setPlaying(!playing);
      else if (k === "ArrowRight") go(sceneAt(time()) + 1);
      else if (k === "ArrowLeft") go(sceneAt(time()) - 1);
      else if (k === "Home") go(0);
      else if (k === "End") go(count - 1);
      else if ((k === "f" || k === "F") && canFull) toggleFullscreen();
      else if (/^[1-9]$/.test(k) && +k <= count) go(+k - 1);
      else return;
      e.preventDefault();
    });

    // Start all animations from the same point so they stay in step.
    requestAnimationFrame(() => {
      seek(0);
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        playing = false;
        anims().forEach((a) => a.pause());
        go(0);
      } else {
        update(false);
      }
    });
  }

  function initAll() {
    document.querySelectorAll(".opm-overview").forEach(init);
  }

  // navigation.instant swaps pages without a reload; document$ re-runs on each page.
  if (typeof document$ !== "undefined") document$.subscribe(initAll);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initAll);
  else initAll();
})();
