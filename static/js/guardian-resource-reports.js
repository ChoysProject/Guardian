(function () {
  var modalEl = document.getElementById("resourceReportModal");
  var frame = document.getElementById("resourceReportFrame");
  var title = document.getElementById("resourceReportTitle");
  var listPane = document.getElementById("resourceReportListPane");
  var viewPane = document.getElementById("resourceReportViewPane");
  var listEl = document.getElementById("resourceReportList");
  var backBtn = document.getElementById("resourceReportBack");
  var exportEl = document.getElementById("resourceReportExport");
  var imageCopyBtn = document.getElementById("resourceReportImageCopy");
  var imageSaveBtn = document.getElementById("resourceReportImageSave");
  var mdCopyBtn = document.getElementById("resourceReportMdCopy");
  var mdSaveBtn = document.getElementById("resourceReportMdSave");
  if (!modalEl || !listEl) {
    return;
  }

  var currentServer = "";
  var currentReports = [];
  var currentReportId = "";
  var busy = false;

  function toast(message, kind) {
    if (window.GuardianUI) {
      window.GuardianUI.toast(message, kind);
    }
  }

  function fileStem() {
    var raw = String((title && title.textContent) || "report").trim();
    var cleaned = raw.replace(/[\\/:*?"<>|]+/g, "_").replace(/^\.+|\.+$/g, "").trim();
    return cleaned || "report";
  }

  function showExport(on) {
    if (!exportEl) {
      return;
    }
    if (on) {
      exportEl.classList.remove("d-none");
    } else {
      exportEl.classList.add("d-none");
    }
  }

  function showList() {
    currentReportId = "";
    title.textContent = currentServer + " 보고서";
    backBtn.classList.add("d-none");
    showExport(false);
    listPane.classList.remove("d-none");
    viewPane.classList.add("d-none");
    if (frame) {
      frame.src = "about:blank";
    }
    listEl.innerHTML = "";
    if (!currentReports.length) {
      listEl.innerHTML = '<div class="p-4 text-muted">아직 보고서가 없습니다.</div>';
      return;
    }
    currentReports.forEach(function (item) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "list-group-item list-group-item-action";
      btn.setAttribute("data-report-id", String(item.id || ""));
      var heading = document.createElement("div");
      heading.className = "fw-semibold";
      heading.textContent = item.title || "보고서";
      var meta = document.createElement("div");
      meta.className = "small text-muted";
      meta.textContent = [item.period, item.summary].filter(Boolean).join(" · ");
      btn.appendChild(heading);
      btn.appendChild(meta);
      listEl.appendChild(btn);
    });
  }

  function showReport(id, label) {
    if (!id || !frame) {
      return;
    }
    currentReportId = String(id);
    title.textContent = label || "보고서";
    backBtn.classList.remove("d-none");
    showExport(true);
    listPane.classList.add("d-none");
    viewPane.classList.remove("d-none");
    frame.src = "/reports/" + id + "/embed";
  }

  function parseRadius(value, size) {
    var num = parseFloat(value);
    if (!isFinite(num) || num <= 0) {
      return 0;
    }
    if (String(value).indexOf("%") >= 0) {
      return (num / 100) * size;
    }
    return num;
  }

  function waitFrame() {
    return new Promise(function (resolve, reject) {
      var tries = 0;
      function check() {
        var doc = frame && frame.contentDocument;
        if (doc && doc.body && doc.body.innerHTML) {
          resolve();
          return;
        }
        tries += 1;
        if (tries > 40) {
          reject(new Error("timeout"));
          return;
        }
        window.setTimeout(check, 100);
      }
      check();
    });
  }

  function snapshotFrame() {
    return waitFrame().then(function () {
    var doc = frame && frame.contentDocument;
    var win = frame && frame.contentWindow;
    if (!doc || !win || !doc.body) {
      return Promise.reject(new Error("empty"));
    }
    var root = doc.documentElement;
    var body = doc.body;
    var width = Math.ceil(Math.max(root.scrollWidth, body.scrollWidth, 800));
    var height = Math.ceil(Math.max(root.scrollHeight, body.scrollHeight, 400));
    var canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    var ctx = canvas.getContext("2d");
    if (!ctx) {
      return Promise.reject(new Error("canvas"));
    }
    ctx.fillStyle = win.getComputedStyle(body).backgroundColor || "#f5f6f8";
    if (ctx.fillStyle === "rgba(0, 0, 0, 0)" || ctx.fillStyle === "transparent") {
      ctx.fillStyle = "#f5f6f8";
    }
    ctx.fillRect(0, 0, width, height);

    function paintBox(el, style) {
      var rect = el.getBoundingClientRect();
      var x = rect.left + win.scrollX;
      var y = rect.top + win.scrollY;
      var w = rect.width;
      var h = rect.height;
      if (w <= 0 || h <= 0) {
        return;
      }
      var radius = Math.min(parseRadius(style.borderTopLeftRadius, Math.min(w, h)), w / 2, h / 2);
      ctx.beginPath();
      if (ctx.roundRect) {
        ctx.roundRect(x, y, w, h, radius);
      } else {
        ctx.rect(x, y, w, h);
      }
      var bg = style.backgroundColor;
      if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") {
        ctx.fillStyle = bg;
        ctx.fill();
      }
      var bw = parseFloat(style.borderTopWidth) || 0;
      if (bw > 0 && style.borderTopStyle !== "none") {
        ctx.strokeStyle = style.borderTopColor || "#e6e8ee";
        ctx.lineWidth = bw;
        ctx.stroke();
      }
    }

    function paintText(node) {
      var text = node.nodeValue;
      if (!text || !String(text).replace(/\s+/g, "")) {
        return;
      }
      var parent = node.parentElement;
      if (!parent) {
        return;
      }
      var style = win.getComputedStyle(parent);
      ctx.fillStyle = style.color || "#1d2433";
      ctx.font = style.font || "13px sans-serif";
      ctx.textBaseline = "top";
      var range = doc.createRange();
      var lines = [];
      var current = null;
      var i;
      for (i = 0; i < text.length; i += 1) {
        range.setStart(node, i);
        range.setEnd(node, i + 1);
        var box = range.getClientRects()[0];
        if (!box) {
          continue;
        }
        var top = Math.round(box.top);
        if (!current || current.top !== top) {
          current = { top: top, left: box.left, text: text[i] };
          lines.push(current);
        } else {
          current.text += text[i];
        }
      }
      lines.forEach(function (line) {
        ctx.fillText(line.text, line.left + win.scrollX, line.top + win.scrollY);
      });
    }

    function paintNode(node) {
      if (node.nodeType === 3) {
        paintText(node);
        return;
      }
      if (node.nodeType !== 1) {
        return;
      }
      var tag = node.tagName;
      if (tag === "SCRIPT" || tag === "STYLE" || tag === "HEAD" || tag === "META" || tag === "TITLE" || tag === "LINK") {
        return;
      }
      var style = win.getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
        return;
      }
      paintBox(node, style);
      var child = node.firstChild;
      while (child) {
        paintNode(child);
        child = child.nextSibling;
      }
    }

    paintNode(body);
    return new Promise(function (resolve, reject) {
      canvas.toBlob(function (blob) {
        if (!blob) {
          reject(new Error("blob"));
          return;
        }
        resolve(blob);
      }, "image/png");
    });
    });
  }

  function downloadBlob(blob, filename) {
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function copyImage(blob) {
    if (!navigator.clipboard || !window.ClipboardItem) {
      return Promise.reject(new Error("clipboard"));
    }
    var item;
    try {
      item = new ClipboardItem({ "image/png": blob });
    } catch (_err) {
      item = new ClipboardItem({ "image/png": Promise.resolve(blob) });
    }
    return navigator.clipboard.write([item]);
  }

  function loadMarkdown() {
    if (!currentReportId) {
      return Promise.reject(new Error("empty"));
    }
    return fetch("/reports/" + currentReportId + "/markdown", { credentials: "same-origin" }).then(function (res) {
      if (!res.ok) {
        throw new Error("http");
      }
      return res.text();
    });
  }

  function copyText(text) {
    if (window.GuardianUI && window.GuardianUI.copy) {
      return window.GuardianUI.copy(text);
    }
    return navigator.clipboard.writeText(text);
  }

  function run(action) {
    if (busy) {
      return;
    }
    busy = true;
    Promise.resolve()
      .then(action)
      .catch(function () {
        toast("저장에 실패했습니다. 보고서를 연 뒤 다시 시도하세요.", "error");
      })
      .then(function () {
        busy = false;
      });
  }

  function openCard(card) {
    var raw = card.getAttribute("data-reports") || "[]";
    try {
      currentReports = JSON.parse(raw);
    } catch (_err) {
      currentReports = [];
    }
    if (!currentReports.length) {
      return;
    }
    currentServer = card.getAttribute("data-server") || "서버";
    showList();
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }

  document.querySelectorAll(".server-report-card").forEach(function (card) {
    card.addEventListener("click", function (event) {
      if (event.target.closest("button, a, form, select, input")) {
        return;
      }
      openCard(card);
    });
    card.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openCard(card);
      }
    });
  });

  listEl.addEventListener("click", function (event) {
    var item = event.target.closest("[data-report-id]");
    if (!item) {
      return;
    }
    var heading = item.querySelector(".fw-semibold");
    showReport(item.getAttribute("data-report-id"), heading ? heading.textContent : "보고서");
  });

  backBtn.addEventListener("click", function () {
    showList();
  });

  if (imageCopyBtn) {
    imageCopyBtn.addEventListener("click", function () {
      run(function () {
        return snapshotFrame().then(function (blob) {
          return copyImage(blob).then(
            function () {
              toast("이미지가 복사되었습니다.", "success");
            },
            function () {
              toast("이 브라우저는 이미지 복사를 지원하지 않습니다. 이미지 저장을 사용하세요.", "warning");
            }
          );
        });
      });
    });
  }
  if (imageSaveBtn) {
    imageSaveBtn.addEventListener("click", function () {
      run(function () {
        return snapshotFrame().then(function (blob) {
          downloadBlob(blob, fileStem() + ".png");
          toast("이미지가 다운로드 되었습니다.", "success");
        });
      });
    });
  }
  if (mdCopyBtn) {
    mdCopyBtn.addEventListener("click", function () {
      run(function () {
        return loadMarkdown()
          .then(copyText)
          .then(function () {
            toast("MD가 복사되었습니다.", "success");
          });
      });
    });
  }
  if (mdSaveBtn) {
    mdSaveBtn.addEventListener("click", function () {
      run(function () {
        return loadMarkdown().then(function (text) {
          downloadBlob(new Blob([text], { type: "text/markdown;charset=utf-8" }), fileStem() + ".md");
          toast("MD가 다운로드 되었습니다.", "success");
        });
      });
    });
  }

  modalEl.addEventListener("hidden.bs.modal", function () {
    if (frame) {
      frame.src = "about:blank";
    }
    currentReports = [];
    currentReportId = "";
    showList();
  });
})();

(function () {
  var modalEl = document.getElementById("resourceDeleteModal");
  var listEl = document.getElementById("resourceDeleteList");
  var listPane = document.getElementById("resourceDeleteListPane");
  var confirmPane = document.getElementById("resourceDeleteConfirmPane");
  var confirmText = document.getElementById("resourceDeleteConfirmText");
  var confirmItems = document.getElementById("resourceDeleteConfirmItems");
  var titleEl = document.getElementById("resourceDeleteTitle");
  var allBox = document.getElementById("resourceDeleteAll");
  var backBtn = document.getElementById("resourceDeleteBack");
  var submitBtn = document.getElementById("resourceDeleteSubmit");
  var form = document.getElementById("resourceDeleteForm");
  if (!modalEl || !listEl || !submitBtn || !form) {
    return;
  }

  var currentServer = "";
  var currentReports = [];
  var pending = [];
  var confirming = false;

  function parseReports(card) {
    try {
      return JSON.parse(card.getAttribute("data-reports") || "[]");
    } catch (_err) {
      return [];
    }
  }

  function toast(message, kind) {
    if (window.GuardianUI) {
      window.GuardianUI.toast(message, kind);
    }
  }

  function selectedReports() {
    return Array.prototype.map
      .call(listEl.querySelectorAll('input[type="checkbox"]:checked'), function (box) {
        return {
          id: box.value,
          title: box.getAttribute("data-title") || "보고서",
        };
      })
      .filter(function (item) {
        return item.id;
      });
  }

  function syncAllBox() {
    if (!allBox) {
      return;
    }
    var boxes = listEl.querySelectorAll('input[type="checkbox"]');
    var checked = listEl.querySelectorAll('input[type="checkbox"]:checked');
    allBox.checked = boxes.length > 0 && boxes.length === checked.length;
  }

  function showList() {
    confirming = false;
    if (titleEl) {
      titleEl.textContent = currentServer + " 보고서 삭제";
    }
    listPane.classList.remove("d-none");
    confirmPane.classList.add("d-none");
    backBtn.classList.add("d-none");
    submitBtn.textContent = "선택한 보고서 삭제";
    listEl.innerHTML = "";
    if (!currentReports.length) {
      listEl.innerHTML = '<div class="p-4 text-muted">아직 보고서가 없습니다.</div>';
      return;
    }
    currentReports.forEach(function (item) {
      var row = document.createElement("label");
      row.className = "list-group-item resource-delete-item mb-0";
      var box = document.createElement("input");
      box.type = "checkbox";
      box.className = "form-check-input";
      box.value = String(item.id || "");
      box.setAttribute("data-title", item.title || "보고서");
      var body = document.createElement("span");
      var heading = document.createElement("div");
      heading.className = "fw-semibold";
      heading.textContent = item.title || "보고서";
      var meta = document.createElement("div");
      meta.className = "small text-muted";
      meta.textContent = [item.period, item.summary].filter(Boolean).join(" · ");
      body.appendChild(heading);
      body.appendChild(meta);
      row.appendChild(box);
      row.appendChild(body);
      listEl.appendChild(row);
    });
    if (allBox) {
      allBox.checked = false;
    }
  }

  function showConfirm(items) {
    confirming = true;
    pending = items;
    listPane.classList.add("d-none");
    confirmPane.classList.remove("d-none");
    backBtn.classList.remove("d-none");
    submitBtn.textContent = "삭제";
    confirmText.textContent =
      currentServer + " 보고서 " + items.length + "건을 삭제할까요? 이 작업은 되돌릴 수 없습니다.";
    confirmItems.innerHTML = "";
    items.forEach(function (item) {
      var li = document.createElement("li");
      li.textContent = item.title;
      confirmItems.appendChild(li);
    });
  }

  function openDelete(card) {
    currentReports = parseReports(card);
    currentServer = card.getAttribute("data-server") || "서버";
    pending = [];
    if (!currentReports.length) {
      toast("삭제할 보고서가 없습니다.", "warning");
      return;
    }
    showList();
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }

  document.querySelectorAll(".js-report-delete").forEach(function (button) {
    button.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      var card = button.closest(".server-report-card");
      if (card) {
        openDelete(card);
      }
    });
  });

  if (allBox) {
    allBox.addEventListener("change", function () {
      listEl.querySelectorAll('input[type="checkbox"]').forEach(function (box) {
        box.checked = allBox.checked;
      });
    });
  }

  listEl.addEventListener("change", function () {
    syncAllBox();
  });

  backBtn.addEventListener("click", function () {
    showList();
  });

  submitBtn.addEventListener("click", function () {
    if (!confirming) {
      var items = selectedReports();
      if (!items.length) {
        toast("삭제할 보고서를 고르세요.", "warning");
        return;
      }
      showConfirm(items);
      return;
    }
    form.innerHTML = "";
    pending.forEach(function (item) {
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = "report_ids";
      input.value = item.id;
      form.appendChild(input);
    });
    form.submit();
  });

  modalEl.addEventListener("hidden.bs.modal", function () {
    pending = [];
    currentReports = [];
    confirming = false;
  });
})();
