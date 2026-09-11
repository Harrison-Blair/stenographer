// SPDX-License-Identifier: GPL-3.0-or-later
// Drives the lifecycle pill replica through the daemon's real state order:
// HIDDEN → RECORDING → TRANSCRIBING → DELIVERING → HIDDEN. The first pass
// carries the cold-load ring on RECORDING, because model warmup starts on
// the hotkey press and the loading edge layers over whatever state is showing.
(function () {
  "use strict";

  var stage = document.getElementById("stage");
  var cap = document.getElementById("cap");
  var lbl = document.getElementById("lbl");
  var bars = document.getElementById("bars").children;
  var tiles = document.getElementById("states").children;
  if (!stage || !cap || !lbl || bars.length !== 18) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var script = [
    { s: "hidden", ms: 1400, cap: "idle · nothing on screen" },
    { s: "recording", ms: 3400, cap: "you hold the key · 18 bars follow your voice" },
    { s: "transcribing", ms: 1500, cap: "faster-whisper, on your machine" },
    { s: "delivering", ms: 900, cap: "your clipboard, then Shift+Insert at your cursor" }
  ];
  var labels = { transcribing: "Transcribing", delivering: "Delivering", error: "Error" };
  var index = 0;
  var pass = 0;
  var levels = new Array(18);
  var target = new Array(18);
  var barTimer = null;

  function silence() {
    for (var k = 0; k < 18; k++) { levels[k] = 0; target[k] = 0; }
  }

  function height(level) {
    // _SPECTRUM_MIN_HEIGHT 4 … _SPECTRUM_MAX_HEIGHT 44, level 0–255
    return (4 + 40 * level / 255).toFixed(1) + "px";
  }

  function animateBars() {
    for (var k = 0; k < 18; k++) {
      if (Math.random() < 0.35) target[k] = Math.random() * 255;
      levels[k] += (target[k] - levels[k]) * 0.45;
      bars[k].style.height = height(levels[k]);
    }
  }

  function staticBars() {
    for (var k = 0; k < 18; k++) {
      bars[k].style.height = height(255 * Math.abs(Math.sin(k * 1.7)));
    }
  }

  function step() {
    var cur = script[index];
    var loading = cur.s === "recording" && pass === 0;
    stage.setAttribute("data-state", cur.s);
    stage.setAttribute("data-loading", loading ? "1" : "0");
    cap.textContent = cur.cap + (loading ? " · your model is loading" : "");
    lbl.textContent = labels[cur.s] || "";
    for (var t = 0; t < tiles.length; t++) {
      var tile = tiles[t].getAttribute("data-for");
      tiles[t].classList.toggle("on", tile === cur.s || (tile === "loading" && loading));
    }
    if (barTimer) { clearInterval(barTimer); barTimer = null; }
    if (cur.s === "recording") {
      silence(); // a new recording never inherits the previous utterance's bars
      if (reduced) {
        staticBars();
      } else {
        animateBars();
        barTimer = setInterval(animateBars, 70);
      }
    }
    index = (index + 1) % script.length;
    if (index === 0) pass++;
    setTimeout(step, cur.ms);
  }

  silence();
  step();

  var copy = document.getElementById("copy");
  var command = document.querySelector("#quick-install code");
  if (copy && command) {
    copy.addEventListener("click", function () {
      var text = command.textContent;
      var done = function () { copy.textContent = "Copied"; setTimeout(function () { copy.textContent = "Copy"; }, 1600); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { copy.textContent = "Select and copy"; });
      } else {
        copy.textContent = "Select and copy";
      }
    });
  }
})();
