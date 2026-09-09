(function () {
  var modalEl = document.getElementById("resourceReportModal");
  var frame = document.getElementById("resourceReportFrame");
  var title = document.getElementById("resourceReportTitle");
  var listPane = document.getElementById("resourceReportListPane");
  var viewPane = document.getElementById("resourceReportViewPane");
  var listEl = document.getElementById("resourceReportList");
  var backBtn = document.getElementById("resourceReportBack");
  if (!modalEl || !listEl) {
    return;
  }

  var currentServer = "";
  var currentReports = [];

  function showList() {
    title.textContent = currentServer + " 보고서";
    backBtn.classList.add("d-none");
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
    title.textContent = label || "보고서";
    backBtn.classList.remove("d-none");
    listPane.classList.add("d-none");
    viewPane.classList.remove("d-none");
    frame.src = "/reports/" + id + "/embed";
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

  modalEl.addEventListener("hidden.bs.modal", function () {
    if (frame) {
      frame.src = "about:blank";
    }
    currentReports = [];
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
