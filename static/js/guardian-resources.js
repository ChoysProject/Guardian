(function () {
  var modal = document.getElementById("resourceUploadModal");
  var nameEl = document.getElementById("resourceModalServer");
  var bindEl = document.getElementById("resourceBindServer");
  var serverEl = document.getElementById("resourceServer");
  var rows = document.getElementById("resourceModalRows");
  var raw = document.getElementById("resource-groups");
  var viewModal = document.getElementById("snapshotViewModal");
  var viewTitle = document.getElementById("snapshotViewTitle");
  var viewBody = document.getElementById("snapshotViewBody");
  if (!modal || !rows) {
    return;
  }

  var groups = {};
  try {
    groups = JSON.parse((raw && raw.textContent) || "{}") || {};
  } catch (err) {
    groups = {};
  }

  var currentServer = "";
  var EXTRA_SKIP = {
    empty: true,
    cpu_usage: true,
    mem_usage: true,
    disk_usage: true,
    instance_search: true,
    proc_service_alive: true,
    proc_top_cpu: true
  };
  var LABELS = {
    usage_pct: "사용률",
    used_pct: "사용률",
    peak_pct: "최고",
    load1: "Load 1분",
    load5: "Load 5분",
    load15: "Load 15분",
    cores: "코어",
    used_mb: "사용 MB",
    total_mb: "전체 MB",
    swap_used_pct: "스왑",
    free_gb: "여유 GB",
    mount: "마운트",
    name: "이름",
    ok: "상태",
    pid: "PID",
    pids: "PID 수",
    cpu_pct: "CPU",
    mem_pct: "MEM",
    mem_mb: "MEM MB",
    cmd: "명령",
    detail: "상세",
    restarts: "재시작",
    cpu_load: "Load Average",
    cpu_core_count: "코어 개수",
    cpu_steal: "Steal Time",
    cpu_ctxswitch: "Context Switch",
    mem_available: "Available 메모리",
    mem_swap: "Swap 사용량",
    mem_oom: "OOM Killer",
    disk_inode: "inode 사용률",
    disk_iowait: "I/O Wait",
    disk_iops: "디스크 IOPS",
    disk_dir_size: "디렉토리 용량",
    net_traffic: "RX/TX 트래픽",
    net_connections: "연결 상태",
    net_errors: "패킷 오류",
    net_listen_ports: "리스닝 포트",
    proc_top_mem: "메모리 상위 프로세스",
    proc_zombie: "좀비 프로세스",
    proc_fd_usage: "파일 디스크립터",
    os_info: "OS/커널",
    os_uptime: "Uptime",
    os_cloud_meta: "클라우드 인스턴스",
    os_ntp_sync: "시간 동기화",
    sec_failed_login: "로그인 실패",
    sec_crontab_check: "crontab"
  };

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function labelOf(key) {
    return LABELS[key] || key;
  }

  function isBlank(value) {
    if (value == null || value === "") {
      return true;
    }
    if (typeof value === "object" && !Array.isArray(value) && value.status === "unavailable") {
      return true;
    }
    if (Array.isArray(value) && !value.length) {
      return true;
    }
    if (typeof value === "object" && !Array.isArray(value) && !Object.keys(value).length) {
      return true;
    }
    return false;
  }

  function fmtValue(value) {
    if (value === true) {
      return "정상";
    }
    if (value === false) {
      return "중단";
    }
    if (typeof value === "number") {
      return String(value);
    }
    return esc(value);
  }

  function pct(value) {
    return value == null || value === "" ? "-" : esc(value) + "%";
  }

  function findSnapshot(server, date) {
    var snapshots = ((groups[server] || {}).snapshots) || [];
    for (var i = 0; i < snapshots.length; i += 1) {
      if (snapshots[i].date === date) {
        return snapshots[i];
      }
    }
    return null;
  }

  function objectTable(rows) {
    if (!rows.length) {
      return "";
    }
    var keys = [];
    rows.forEach(function (row) {
      Object.keys(row || {}).forEach(function (key) {
        if (keys.indexOf(key) < 0) {
          keys.push(key);
        }
      });
    });
    var head = keys.map(function (key) {
      return "<th>" + esc(labelOf(key)) + "</th>";
    }).join("");
    var body = rows.map(function (row) {
      return "<tr>" + keys.map(function (key) {
        var cell = row[key];
        if (key === "ok") {
          var cls = cell ? "bg-success-soft text-success" : "bg-danger-soft text-danger";
          return '<td><span class="badge ' + cls + '">' + fmtValue(cell) + "</span></td>";
        }
        if (key === "cpu_pct" || key === "mem_pct" || key === "used_pct" || key === "usage_pct") {
          return "<td>" + pct(cell) + "</td>";
        }
        if (cell != null && typeof cell === "object") {
          return "<td>" + renderValue(cell) + "</td>";
        }
        return "<td>" + (isBlank(cell) ? "-" : fmtValue(cell)) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    return '<div class="table-responsive"><table class="table table-sm snap-table mb-0"><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table></div>";
  }

  function pairList(obj) {
    var items = Object.keys(obj || {}).filter(function (key) {
      return !isBlank(obj[key]);
    }).map(function (key) {
      var value = obj[key];
      var shown = typeof value === "object" ? renderValue(value) : fmtValue(value);
      return '<div class="snap-pair"><span class="snap-pair-key">' + esc(labelOf(key)) + '</span><span class="snap-pair-val">' + shown + "</span></div>";
    });
    return items.length ? '<div class="snap-pairs">' + items.join("") + "</div>" : "";
  }

  function renderValue(value) {
    if (isBlank(value)) {
      return '<span class="text-muted">없음</span>';
    }
    if (Array.isArray(value)) {
      if (value.every(function (item) { return item && typeof item === "object" && !Array.isArray(item); })) {
        return objectTable(value);
      }
      return "<ul class=\"mb-0 ps-3\">" + value.map(function (item) {
        return "<li>" + (typeof item === "object" ? renderValue(item) : fmtValue(item)) + "</li>";
      }).join("") + "</ul>";
    }
    if (typeof value === "object") {
      return pairList(value);
    }
    return fmtValue(value);
  }

  function section(title, inner) {
    if (!inner) {
      return "";
    }
    return '<section class="snap-section"><h6>' + esc(title) + "</h6>" + inner + "</section>";
  }

  function kpiCard(label, value, note) {
    return (
      '<div class="snap-kpi">' +
      '<div class="snap-kpi-label">' + esc(label) + "</div>" +
      '<div class="snap-kpi-value">' + value + "</div>" +
      (note ? '<div class="snap-kpi-note">' + note + "</div>" : "") +
      "</div>"
    );
  }

  function renderReport(item) {
    if (!item) {
      return '<div class="text-muted">자료를 찾을 수 없습니다.</div>';
    }
    var cpu = item.cpu || {};
    var mem = item.mem || {};
    var parts = [];
    var kpis = "";
    if (cpu.usage_pct != null || cpu.peak_pct != null || cpu.load1 != null || cpu.cores != null) {
      var cpuNote = [];
      if (cpu.peak_pct != null) {
        cpuNote.push("최고 " + esc(cpu.peak_pct) + "%");
      }
      if (cpu.load1 != null) {
        cpuNote.push("load " + esc(cpu.load1));
      }
      if (cpu.cores != null) {
        cpuNote.push(esc(cpu.cores) + "코어");
      }
      kpis += kpiCard("CPU", cpu.usage_pct != null ? pct(cpu.usage_pct) : "-", cpuNote.join(" · "));
    }
    if (mem.used_pct != null || mem.used_mb != null || mem.swap_used_pct != null) {
      var memNote = [];
      if (mem.used_mb != null) {
        memNote.push(esc(mem.used_mb) + (mem.total_mb != null ? " / " + esc(mem.total_mb) : "") + " MB");
      }
      if (mem.swap_used_pct != null) {
        memNote.push("스왑 " + esc(mem.swap_used_pct) + "%");
      }
      kpis += kpiCard("MEM", mem.used_pct != null ? pct(mem.used_pct) : "-", memNote.join(" · "));
    }
    if ((item.disk || []).length) {
      var hottest = item.disk.slice().sort(function (a, b) {
        return (b.used_pct || 0) - (a.used_pct || 0);
      })[0];
      kpis += kpiCard("Disk", hottest && hottest.used_pct != null ? pct(hottest.used_pct) : "-", hottest ? esc(hottest.mount) : "");
    }
    if (kpis) {
      parts.push('<div class="snap-kpis">' + kpis + "</div>");
    }
    if ((item.disk || []).length) {
      parts.push(section("디스크", objectTable(item.disk)));
    }
    if ((item.instances || []).length) {
      parts.push(section("인스턴스", objectTable(item.instances)));
    }
    if ((item.top || []).length) {
      parts.push(section("CPU 상위 프로세스", objectTable(item.top)));
    }
    if ((cpu.samples || []).length) {
      parts.push(section("시간대별 샘플", objectTable(cpu.samples)));
    }
    var extra = item.extra || {};
    Object.keys(extra).forEach(function (key) {
      if (EXTRA_SKIP[key] || isBlank(extra[key])) {
        return;
      }
      parts.push(section(labelOf(key), renderValue(extra[key])));
    });
    if (!parts.length) {
      return '<div class="text-muted">표시할 수집 항목이 없습니다.</div>';
    }
    return '<div class="snap-report">' + parts.join("") + "</div>";
  }

  function openSnapshot(server, date) {
    var item = findSnapshot(server, date);
    if (viewTitle) {
      viewTitle.textContent = server + " · " + date;
    }
    if (viewBody) {
      viewBody.innerHTML = renderReport(item);
    }
    if (viewModal && window.bootstrap) {
      window.bootstrap.Modal.getOrCreateInstance(viewModal).show();
    }
  }

  function render(server) {
    var snapshots = ((groups[server] || {}).snapshots) || [];
    if (!snapshots.length) {
      rows.innerHTML = '<tr><td colspan="2" class="text-muted">아직 넣은 자료가 없습니다.</td></tr>';
      return;
    }
    rows.innerHTML = snapshots
      .map(function (item) {
        return (
          '<tr class="snapshot-row" data-date="' +
          esc(item.date) +
          '" title="더블클릭하면 수집 내용을 봅니다">' +
          "<td>" +
          esc(item.date) +
          "</td><td class=\"text-end\">" +
          '<form method="post" action="/servers/resources/delete" onsubmit="return confirm(\'이 날짜 자료를 지울까요?\');">' +
          '<input type="hidden" name="server" value="' +
          esc(server) +
          '"><input type="hidden" name="date" value="' +
          esc(item.date) +
          '"><button class="btn btn-sm btn-outline-danger" type="submit">삭제</button></form></td></tr>'
        );
      })
      .join("");
    rows.querySelectorAll(".snapshot-row").forEach(function (row) {
      row.addEventListener("dblclick", function () {
        openSnapshot(server, row.getAttribute("data-date"));
      });
    });
  }

  modal.addEventListener("show.bs.modal", function (event) {
    var trigger = event.relatedTarget;
    var server = (trigger && trigger.getAttribute("data-server-name")) || "";
    currentServer = server;
    if (nameEl) {
      nameEl.textContent = server;
    }
    if (bindEl) {
      bindEl.value = server;
    }
    if (serverEl) {
      serverEl.value = server;
    }
    render(server);
    resetUploadFiles();
  });

  if (viewModal) {
    viewModal.addEventListener("shown.bs.modal", function () {
      document.querySelectorAll(".modal-backdrop").forEach(function (el, index) {
        if (index > 0) {
          el.style.zIndex = "1085";
        }
      });
    });
  }

  var fileInput = document.getElementById("files");
  var fileList = document.getElementById("upload-file-list");
  var uploadForm = fileInput ? fileInput.form : null;
  var picked = [];

  function fileKey(file) {
    return file.name + "\t" + file.size + "\t" + file.lastModified;
  }

  function sortPicked() {
    picked.sort(function (a, b) {
      return a.name.localeCompare(b.name, "ko");
    });
  }

  function renderFiles() {
    if (!fileList) {
      return;
    }
    if (!picked.length) {
      fileList.innerHTML = '<li class="text-muted">고른 파일이 없습니다.</li>';
      return;
    }
    fileList.innerHTML = picked
      .map(function (file, index) {
        return (
          '<li class="upload-file-item">' +
          '<span class="upload-file-name" title="' +
          esc(file.name) +
          '">' +
          esc(file.name) +
          "</span>" +
          '<button type="button" class="upload-file-remove" data-index="' +
          index +
          '" aria-label="빼기">×</button>' +
          "</li>"
        );
      })
      .join("");
    fileList.querySelectorAll(".upload-file-remove").forEach(function (button) {
      button.addEventListener("click", function () {
        var index = parseInt(button.getAttribute("data-index"), 10);
        if (!isNaN(index)) {
          picked.splice(index, 1);
          renderFiles();
        }
      });
    });
  }

  function resetUploadFiles() {
    picked = [];
    if (fileInput) {
      fileInput.value = "";
    }
    renderFiles();
  }

  function applyFilesToInput() {
    if (!fileInput || typeof DataTransfer === "undefined") {
      return picked.length > 0;
    }
    var transfer = new DataTransfer();
    picked.forEach(function (file) {
      transfer.items.add(file);
    });
    fileInput.files = transfer.files;
    return picked.length > 0;
  }

  if (fileInput) {
    fileInput.addEventListener("change", function () {
      var seen = {};
      picked.forEach(function (file) {
        seen[fileKey(file)] = true;
      });
      Array.prototype.forEach.call(fileInput.files || [], function (file) {
        var key = fileKey(file);
        if (!seen[key]) {
          picked.push(file);
          seen[key] = true;
        }
      });
      sortPicked();
      fileInput.value = "";
      renderFiles();
    });
  }

  if (uploadForm) {
    uploadForm.addEventListener("submit", function (event) {
      if (!applyFilesToInput()) {
        event.preventDefault();
        alert("올릴 JSON 파일을 선택하세요.");
      }
    });
  }
})();

(function () {
  var input = document.getElementById("server-search");
  var empty = document.getElementById("server-search-empty");
  if (!input) {
    return;
  }
  var rows = Array.prototype.slice.call(document.querySelectorAll("tr.resource-server-row"));

  function apply() {
    var needle = (input.value || "").trim().toLowerCase();
    var shown = 0;
    rows.forEach(function (row) {
      var hay = (row.getAttribute("data-search") || "").toLowerCase();
      var match = !needle || hay.indexOf(needle) !== -1;
      row.classList.toggle("d-none", !match);
      if (match) {
        shown += 1;
      }
    });
    if (empty) {
      empty.classList.toggle("d-none", shown > 0 || !rows.length);
    }
  }

  input.addEventListener("input", apply);
})();
