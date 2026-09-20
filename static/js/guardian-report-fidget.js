(function () {
  var overlay = document.getElementById("reportFidget");
  var lineEl = document.getElementById("reportFidgetLine");
  var titleEl = document.getElementById("reportFidgetTitle");
  if (!overlay) {
    return;
  }

  var aiOn = overlay.getAttribute("data-ai") === "1";
  var kinds = {
    report: {
      title: "보고서를 만들고 있어요",
      lines: [
        aiOn ? "AI가 보고서를 조립하고 있어요." : "숫자를 모아 보고서를 조립하고 있어요.",
        "보고서 내용을 읽고 있어요.",
        "CPU와 메모리를 나란히 놓고 보고 있어요.",
        "디스크가 얼마나 남았는지 세고 있어요.",
        "인스턴스가 잘 살아 있는지 확인하고 있어요.",
        "한줄 총평을 고르고 있어요.",
        "숫자만 보고, 없는 얘기는 안 만들려고 해요.",
      ],
    },
    "log-collect": {
      title: "로그를 모으고 있어요",
      lines: [
        "AI가 서버에 들어가고 있어요.",
        "수집중이에요.",
        "로그를 모으고 있어요.",
        "에러 줄을 찾고 있어요.",
        "징후를 정리하고 있어요.",
      ],
    },
    "resource-collect": {
      title: "리소스를 모으고 있어요",
      lines: [
        "AI가 서버에 들어가고 있어요.",
        "수집중이에요.",
        "리소스를 모으고 있어요.",
        "CPU와 메모리를 읽고 있어요.",
        "디스크와 인스턴스를 확인하고 있어요.",
      ],
    },
    "overview": {
      title: "전체를 읽고 있어요",
      lines: [
        aiOn ? "AI가 서버들을 한 이야기로 모으고 있어요." : "서버들을 한 이야기로 모으고 있어요.",
        "로그 징후와 리소스를 나란히 놓고 있어요.",
        "어디를 먼저 볼지 고르고 있어요.",
      ],
    },
    "collect-all": {
      title: "전체를 수집하고 있어요",
      lines: [
        "등록한 서버에서 로그를 읽고 있어요.",
        "리소스와 성능도 같이 모으고 있어요.",
        "징후를 정리하고 있어요.",
      ],
    },
    "report-all": {
      title: "보고서를 만들고 있어요",
      lines: [
        "로그 보고서를 만들고 있어요.",
        "리소스 보고서도 같이 만들고 있어요.",
        "한줄 총평을 고르고 있어요.",
      ],
    },
  };

  var lines = kinds.report.lines;
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

  function startFidget(kind) {
    if (started) {
      return;
    }
    var spec = kinds[kind] || kinds.report;
    lines = spec.lines;
    if (titleEl) {
      titleEl.textContent = spec.title;
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

  document.querySelectorAll("form.js-report-generate, form.js-fidget").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (started) {
        event.preventDefault();
        return;
      }
      startFidget(form.getAttribute("data-fidget") || "report");
    });
  });
})();
