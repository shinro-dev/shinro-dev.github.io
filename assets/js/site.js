/* Shinro site — small progressive enhancements. No trackers, no deps. */
(function () {
  "use strict";

  /* Copy helpers: clipboard API when available, execCommand fallback. */
  function copyText(text, button) {
    var done = function () {
      var old = button.textContent;
      button.textContent = "Copied";
      window.setTimeout(function () {
        button.textContent = old;
      }, 1600);
    };

    var fallback = function () {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.top = "-1000px";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        if (document.execCommand("copy")) done();
      } catch (err) {
        /* no-op */
      }
      document.body.removeChild(area);
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, fallback);
    } else {
      fallback();
    }
  }

  /* Copy buttons on code blocks */
  document.querySelectorAll(".pre-head").forEach(function (head) {
    var button = head.querySelector(".copy");
    var block = head.parentElement;
    if (!button || !block) return;

    button.addEventListener("click", function () {
      var code = block.querySelector("code");
      if (!code) return;
      copyText(code.textContent.replace(/\u00a0/g, " "), button);
    });
  });

  /* Copy the quickstart commands from the homepage terminal */
  document.querySelectorAll("[data-copy-term]").forEach(function (button) {
    var term = button.closest(".term");
    if (!term) return;
    button.addEventListener("click", function () {
      var commands = Array.prototype.map
        .call(term.querySelectorAll(".line"), function (line) {
          return line.textContent
            .replace(/^\s*\$\s*/, "")
            .replace(/\s+#.*$/, "")
            .trim();
        })
        .filter(Boolean)
        .join("\n");
      copyText(commands, button);
    });
  });

  /* Play/pause control for the inline demo video */
  document.querySelectorAll("[data-video-toggle]").forEach(function (button) {
    var frame = button.closest(".fig-media");
    var video = frame && frame.querySelector("video");
    if (!video) return;

    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reduce.matches) {
      video.pause();
    } else {
      var started = video.play();
      if (started && typeof started.catch === "function") started.catch(function () {});
    }

    function label() {
      var paused = video.paused;
      button.textContent = paused ? "Play" : "Pause";
      button.setAttribute(
        "aria-label",
        paused ? "Play the demo video" : "Pause the demo video"
      );
    }

    button.addEventListener("click", function () {
      if (video.paused) {
        video.play();
      } else {
        video.pause();
      }
    });

    video.addEventListener("play", label);
    video.addEventListener("pause", label);
    label();
  });

  /* Highlight the current section in the table of contents */
  var links = Array.prototype.slice.call(
    document.querySelectorAll('.toc a[href^="#"]')
  );
  if (!links.length) return;

  var entries = links
    .map(function (link) {
      var section = document.getElementById(link.getAttribute("href").slice(1));
      return section ? { link: link, section: section } : null;
    })
    .filter(Boolean);
  if (!entries.length) return;

  var ticking = false;

  function update() {
    ticking = false;
    var offset = 150;
    var current = entries[0];

    entries.forEach(function (entry) {
      if (entry.section.getBoundingClientRect().top <= offset) current = entry;
    });

    // At the very bottom of the page, highlight the last entry.
    if (
      window.innerHeight + window.scrollY >=
      document.documentElement.scrollHeight - 40
    ) {
      current = entries[entries.length - 1];
    }

    entries.forEach(function (entry) {
      entry.link.classList.toggle("active", entry === current);
    });
  }

  function onScroll() {
    if (!ticking) {
      ticking = true;
      window.requestAnimationFrame(update);
    }
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);
  update();
})();
