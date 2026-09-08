(function () {
  var form = document.getElementById("server-add-form");
  var logsBox = document.getElementById("analyze_logs");
  var logRow = document.getElementById("log-path-row");
  if (form && logsBox && logRow) {
    function syncLogRow() {
      logRow.classList.toggle("d-none", !logsBox.checked);
    }
    logsBox.addEventListener("change", syncLogRow);
    syncLogRow();
    form.addEventListener("submit", function (event) {
      var resources = document.getElementById("analyze_resources");
      if (!logsBox.checked && !(resources && resources.checked)) {
        event.preventDefault();
        alert("로그 분석 또는 리소스 분석 중 하나는 선택해야 합니다.");
      }
    });
  }

  function instanceRow(value, wrap) {
    var item = document.createElement("div");
    item.className = wrap
      ? "col-md-4 mb-2 instance-item"
      : "input-group input-group-sm mb-2 instance-item";
    item.innerHTML =
      (wrap ? '<div class="input-group input-group-sm">' : "") +
      '<input class="form-control" name="instances" placeholder="postgres">' +
      '<button class="btn btn-outline-secondary instance-remove" type="button" aria-label="빼기">−</button>' +
      (wrap ? "</div>" : "");
    item.querySelector("input").value = value || "";
    item.querySelector(".instance-remove").addEventListener("click", function () {
      item.remove();
    });
    return item;
  }

  var addList = document.getElementById("instance-list");
  var addButton = document.getElementById("instance-add");
  if (addList && addButton) {
    addList.querySelectorAll(".instance-remove").forEach(function (button) {
      button.addEventListener("click", function () {
        var row = button.closest(".instance-item");
        if (row) {
          row.remove();
        }
      });
    });
    addButton.addEventListener("click", function () {
      addList.appendChild(instanceRow("", false));
    });
  }

  var modalList = document.getElementById("modal-instance-list");
  var modalAdd = document.getElementById("modal-instance-add");
  var instanceForm = document.getElementById("serverInstanceForm");
  if (modalAdd && modalList) {
    modalAdd.addEventListener("click", function () {
      modalList.appendChild(instanceRow("", true));
    });
  }

  function fillInstances(button) {
    if (!modalList || !instanceForm) {
      return;
    }
    instanceForm.action = "/servers/" + (button.getAttribute("data-server-id") || "") + "/instances";
    modalList.innerHTML = "";
    var raw = button.getAttribute("data-server-instances") || "";
    var names = raw
      ? raw.split(",").map(function (item) {
          return item.trim();
        })
      : [];
    names = names.filter(Boolean);
    if (!names.length) {
      names = [""];
    }
    names.forEach(function (name) {
      modalList.appendChild(instanceRow(name, true));
    });
  }

  var panel = document.getElementById("checkpoint-panel");
  var body = document.getElementById("checkpoint-body");
  var loading = document.getElementById("checkpoint-loading");
  var title = document.getElementById("serverInfoTitle");
  var meta = document.getElementById("serverInfoMeta");
  if (!panel || !body) {
    return;
  }

  var PAGE_SIZE = 50;
  var offset = 0;
  var hasMore = true;
  var busy = false;
  var serverId = "";

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function fmtTs(value) {
    if (!value) {
      return "-";
    }
    return String(value).replace("T", " ").slice(0, 19);
  }

  function resetTable() {
    offset = 0;
    hasMore = true;
    busy = false;
    body.innerHTML = '<tr id="checkpoint-empty"><td colspan="4" class="text-muted">아직 수집한 파일이 없습니다.</td></tr>';
  }

  function appendRows(items) {
    var empty = document.getElementById("checkpoint-empty");
    if (empty) {
      empty.remove();
    }
    items.forEach(function (item) {
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td class=\"path\"><code>" +
        esc(item.log_path) +
        "</code></td><td>" +
        esc(item.offset) +
        "</td><td>" +
        esc(item.size) +
        "</td><td>" +
        esc(fmtTs(item.updated_at)) +
        "</td>";
      body.appendChild(tr);
    });
  }

  function loadPage() {
    if (busy || !hasMore || !serverId) {
      return;
    }
    busy = true;
    if (loading) {
      loading.classList.remove("d-none");
    }
    fetch("/api/checkpoints?server_id=" + encodeURIComponent(serverId) + "&offset=" + offset + "&limit=" + PAGE_SIZE)
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        var items = data.items || [];
        hasMore = !!data.has_more;
        offset = (data.offset || offset) + items.length;
        if (items.length) {
          appendRows(items);
        }
      })
      .catch(function () {
        /* 다음 스크롤에서 재시도 */
      })
      .then(function () {
        busy = false;
        if (loading) {
          loading.classList.add("d-none");
        }
      });
  }

  function fillMeta(button) {
    var name = button.getAttribute("data-server-name") || "";
    var kinds = [];
    if (button.getAttribute("data-server-logs") === "1") {
      kinds.push("로그 분석");
    }
    if (button.getAttribute("data-server-resources") === "1") {
      kinds.push("리소스 분석");
    }
    if (title) {
      title.textContent = name || "서버 정보";
    }
    if (meta) {
      var paths = button.getAttribute("data-server-paths") || "[]";
      var err = button.getAttribute("data-server-error") || "";
      meta.innerHTML =
        "<dt class=\"col-sm-3\">수집기</dt><dd class=\"col-sm-9\">" +
        esc(button.getAttribute("data-server-type")) +
        "</dd>" +
        "<dt class=\"col-sm-3\">대상</dt><dd class=\"col-sm-9\">" +
        esc(button.getAttribute("data-server-host")) +
        "</dd>" +
        "<dt class=\"col-sm-3\">분석</dt><dd class=\"col-sm-9\">" +
        esc(kinds.join(" · ") || "-") +
        "</dd>" +
        "<dt class=\"col-sm-3\">로그 경로</dt><dd class=\"col-sm-9\"><code>" +
        esc(paths) +
        "</code></dd>" +
        (err
          ? "<dt class=\"col-sm-3\">오류</dt><dd class=\"col-sm-9 text-danger\">" + esc(err) + "</dd>"
          : "");
    }
  }

  document.querySelectorAll("[data-server-id][data-bs-target='#serverInfoModal']").forEach(function (button) {
    button.addEventListener("click", function () {
      serverId = button.getAttribute("data-server-id") || "";
      fillMeta(button);
      fillInstances(button);
      resetTable();
      loadPage();
    });
  });

  panel.addEventListener("scroll", function () {
    if (!hasMore || busy) {
      return;
    }
    var remain = panel.scrollHeight - panel.scrollTop - panel.clientHeight;
    if (remain < 48) {
      loadPage();
    }
  });
})();
