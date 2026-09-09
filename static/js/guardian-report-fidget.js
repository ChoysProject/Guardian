(function () {
  var overlay = document.getElementById("reportFidget");
  var lineEl = document.getElementById("reportFidgetLine");
  if (!overlay) {
    return;
  }

  var aiOn = overlay.getAttribute("data-ai") === "1";
  var lines = [
    aiOn ? "AI가 보고서를 조립하고 있어요." : "숫자를 모아 보고서를 조립하고 있어요.",
    "보고서 내용을 읽고 있어요.",
    "CPU와 메모리를 나란히 놓고 보고 있어요.",
    "디스크가 얼마나 남았는지 세고 있어요.",
    "인스턴스가 잘 살아 있는지 확인하고 있어요.",
    "한줄 총평을 고르고 있어요.",
    "숫자만 보고, 없는 얘기는 안 만들려고 해요.",
  ];
  var index = 0;
  var timer = null;
  var started = false;

  function setLine(text) {
    if (!lineEl) {
      return;
    }
    lineEl.classList.add("is-out");
    window.setTimeout(function () {
      lineEl.textContent = text;
      lineEl.classList.remove("is-out");
    }, 280);
  }

  function startFidget() {
    if (started) {
      return;
    }
    started = true;
    overlay.classList.add("is-on");
    overlay.setAttribute("aria-busy", "true");
    document.body.style.overflow = "hidden";
    index = 0;
    if (lineEl) {
      lineEl.classList.remove("is-out");
      lineEl.textContent = lines[0];
    }
    window.clearInterval(timer);
    timer = window.setInterval(function () {
      index = (index + 1) % lines.length;
      setLine(lines[index]);
    }, 2400);
  }

  document.querySelectorAll("form.js-report-generate").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (started) {
        event.preventDefault();
        return;
      }
      startFidget();
    });
  });
})();
