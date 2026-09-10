/* Minimal slideshow for the docs landing page (no Bootstrap).
 *
 * Markup: .slideshow > .slideshow__track > .slideshow__slide, plus optional
 * .slideshow__prev / .slideshow__next buttons and a .slideshow__dots container.
 * Autoplays every data-interval ms (default 5000); pauses on hover/focus and
 * when the user prefers reduced motion.
 */
(function () {
  function init(root) {
    if (root.dataset.ready) return;
    root.dataset.ready = "1";

    const track = root.querySelector(".slideshow__track");
    const slides = Array.from(track.children);
    const dots = root.querySelector(".slideshow__dots");
    const interval = parseInt(root.dataset.interval || "5000", 10);
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let index = 0;
    let timer = null;

    const dotButtons = slides.map((slide, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("aria-label", slide.dataset.label || `Slide ${i + 1}`);
      b.addEventListener("click", () => { show(i); restart(); });
      dots && dots.appendChild(b);
      return b;
    });

    function show(i) {
      index = (i + slides.length) % slides.length;
      track.style.transform = `translateX(-${index * 100}%)`;
      slides.forEach((s, j) => {
        s.setAttribute("aria-hidden", j === index ? "false" : "true");
        s.inert = j !== index;
      });
      dotButtons.forEach((b, j) => {
        b.classList.toggle("active", j === index);
        if (j === index) b.setAttribute("aria-current", "true");
        else b.removeAttribute("aria-current");
      });
    }

    function stop() { clearInterval(timer); timer = null; }
    function start() {
      if (reduceMotion || interval <= 0 || timer) return;
      timer = setInterval(() => show(index + 1), interval);
    }
    function restart() { stop(); start(); }

    root.querySelector(".slideshow__prev")?.addEventListener("click", () => { show(index - 1); restart(); });
    root.querySelector(".slideshow__next")?.addEventListener("click", () => { show(index + 1); restart(); });
    root.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { show(index - 1); restart(); }
      else if (e.key === "ArrowRight") { show(index + 1); restart(); }
    });
    root.addEventListener("mouseenter", stop);
    root.addEventListener("mouseleave", start);
    root.addEventListener("focusin", stop);
    root.addEventListener("focusout", start);

    // swipe support
    let x0 = null;
    track.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; }, { passive: true });
    track.addEventListener("touchend", (e) => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0;
      if (Math.abs(dx) > 40) { show(index + (dx < 0 ? 1 : -1)); restart(); }
      x0 = null;
    });

    show(0);
    start();
  }

  function initAll() {
    document.querySelectorAll(".slideshow").forEach(init);
  }

  // With navigation.instant, pages are swapped without a reload; the theme
  // exposes document$ to re-run scripts on each page change.
  if (typeof document$ !== "undefined") document$.subscribe(initAll);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initAll);
  else initAll();
})();
