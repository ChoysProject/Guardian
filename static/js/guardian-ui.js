(function () {
  var toastHost = document.getElementById("guardianToasts");
  var CLIPBOARD =
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16" aria-hidden="true">' +
    '<path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z"/>' +
    '<path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z"/>' +
    "</svg>";

  function fallbackCopy(text) {
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy");
        resolve();
      } catch (err) {
        reject(err);
      }
      area.remove();
    });
  }

  function copyText(text) {
    if (!text) {
      return Promise.reject(new Error("empty"));
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function () {
        return fallbackCopy(text);
      });
    }
    return fallbackCopy(text);
  }

  function markCopied(button) {
    if (!button) {
      return;
    }
    button.classList.add("is-done");
    button.title = "복사됨";
    button.setAttribute("aria-label", "복사됨");
    window.setTimeout(function () {
      button.classList.remove("is-done");
      button.title = "복사";
      button.setAttribute("aria-label", "복사");
    }, 1600);
  }

  function copyButton(text) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "guardian-toast-copy";
    btn.title = "복사";
    btn.setAttribute("aria-label", "복사");
    btn.innerHTML = CLIPBOARD;
    btn.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      copyText(text).then(function () {
        markCopied(btn);
      });
    });
    return btn;
  }

  function toast(message, kind) {
    if (!toastHost || !message) {
      return;
    }
    var text = String(message);
    var tone = kind || "info";
    var copyable = tone === "error" || text.length >= 48;
    var hold = copyable ? 10000 : 3400;
    var el = document.createElement("div");
    el.className = "guardian-toast is-" + tone;
    var body = document.createElement("div");
    body.className = "guardian-toast-body";
    body.textContent = text;
    el.appendChild(body);
    if (copyable) {
      el.appendChild(copyButton(text));
    }
    toastHost.appendChild(el);

    var leaving = false;
    var timer = null;
    function dismiss() {
      if (leaving) {
        return;
      }
      leaving = true;
      el.classList.add("is-out");
      window.setTimeout(function () {
        el.remove();
      }, 280);
    }
    function arm() {
      window.clearTimeout(timer);
      timer = window.setTimeout(dismiss, hold);
    }
    el.addEventListener("mouseenter", function () {
      window.clearTimeout(timer);
    });
    el.addEventListener("mouseleave", arm);
    arm();
  }

  function confirm(options) {
    options = options || {};
    var modalEl = document.getElementById("guardianConfirmModal");
    var titleEl = document.getElementById("guardianConfirmTitle");
    var bodyEl = document.getElementById("guardianConfirmBody");
    var okBtn = document.getElementById("guardianConfirmOk");
    if (!modalEl || !okBtn || !window.bootstrap) {
      return Promise.resolve(window.confirm(options.body || "진행할까요?"));
    }
    return new Promise(function (resolve) {
      var settled = false;
      if (titleEl) {
        titleEl.textContent = options.title || "확인";
      }
      if (bodyEl) {
        bodyEl.textContent = options.body || "진행할까요?";
      }
      okBtn.textContent = options.okLabel || "확인";
      okBtn.className = "btn " + (options.danger === false ? "btn-primary" : "btn-danger");

      function finish(value) {
        if (settled) {
          return;
        }
        settled = true;
        resolve(value);
      }
      function onOk() {
        finish(true);
        window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
      }
      function onHidden() {
        okBtn.removeEventListener("click", onOk);
        modalEl.removeEventListener("hidden.bs.modal", onHidden);
        finish(false);
      }
      okBtn.addEventListener("click", onOk);
      modalEl.addEventListener("hidden.bs.modal", onHidden);
      window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
    });
  }

  document.addEventListener(
    "submit",
    function (event) {
      var form = event.target;
      if (!form || !form.getAttribute) {
        return;
      }
      var message = form.getAttribute("data-confirm");
      if (!message || form.getAttribute("data-confirm-accepted") === "1") {
        return;
      }
      event.preventDefault();
      confirm({
        title: form.getAttribute("data-confirm-title") || "확인",
        body: message,
        okLabel: form.getAttribute("data-confirm-ok") || "삭제",
        danger: form.getAttribute("data-confirm-danger") !== "0",
      }).then(function (ok) {
        if (!ok) {
          return;
        }
        form.setAttribute("data-confirm-accepted", "1");
        form.submit();
      });
    },
    true
  );

  function readFlash() {
    var node = document.getElementById("guardian-flash");
    if (!node || !node.textContent) {
      return {};
    }
    try {
      return JSON.parse(node.textContent);
    } catch (err) {
      return {};
    }
  }

  function showFlashToasts() {
    var flash = readFlash();
    var params = new URLSearchParams(window.location.search);
    var error = flash.error || params.get("error") || "";
    var notice = flash.notice || params.get("notice") || "";
    var tested = flash.tested || params.get("tested") || "";
    var saved = flash.saved || Number(params.get("saved") || 0);
    var kind = params.get("toast");
    var count = params.get("count");
    if (error) {
      toast(error, "error");
    }
    if (notice) {
      toast(notice, "success");
    }
    if (saved) {
      toast(saved + "건을 넣었습니다.", "success");
    }
    if (tested) {
      toast("접속 확인 결과\n" + tested, "success");
    }
    if (kind === "deleted") {
      toast(count && count !== "1" ? "보고서 " + count + "건을 삭제했습니다." : "보고서를 삭제했습니다.", "success");
    } else if (kind === "delete_none") {
      toast("삭제할 보고서를 찾지 못했습니다.", "warning");
    } else if (kind && params.get("toast_text")) {
      toast(params.get("toast_text"), kind === "error" ? "error" : "info");
    }
    ["toast", "count", "toast_text", "error", "notice", "saved", "tested"].forEach(function (key) {
      params.delete(key);
    });
    var next = window.location.pathname;
    var qs = params.toString();
    if (qs) {
      next += "?" + qs;
    }
    next += window.location.hash;
    window.history.replaceState({}, "", next);
  }

  showFlashToasts();

  document.addEventListener(
    "click",
    function (event) {
      var link = event.target.closest("a.js-soon");
      if (link) {
        event.preventDefault();
        event.stopPropagation();
        toast(link.getAttribute("data-toast") || "준비중입니다.", "info");
        return;
      }
      var copyBtn = event.target.closest(".js-copy");
      if (!copyBtn) {
        return;
      }
      event.preventDefault();
      var text = copyBtn.getAttribute("data-copy") || "";
      copyText(text).then(function () {
        markCopied(copyBtn);
      });
    },
    true
  );

  window.GuardianUI = {
    toast: toast,
    confirm: confirm,
    copy: copyText,
  };
})();
