(function () {
  var modal = document.getElementById("resourceUploadModal");
  var nameEl = document.getElementById("resourceModalServer");
  var bindEl = document.getElementById("resourceBindServer");
  var serverEl = document.getElementById("resourceServer");
  var rows = document.getElementById("resourceModalRows");
  var raw = document.getElementById("resource-groups");
  var rawInstances = document.getElementById("resource-instances");
  var instanceEl = document.getElementById("resourceModalInstances");
  if (!modal || !rows) {
    return;
  }

  var groups = {};
  try {
    groups = JSON.parse((raw && raw.textContent) || "{}") || {};
  } catch (err) {
    groups = {};
  }

  var instanceMap = {};
  try {
    instanceMap = JSON.parse((rawInstances && rawInstances.textContent) || "{}") || {};
  } catch (err) {
    instanceMap = {};
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function diskHtml(disks) {
    if (!disks || !disks.length) {
      return "-";
    }
    return disks
      .map(function (disk) {
        var free = disk.free_gb != null ? " <span class=\"text-muted small\">여유 " + esc(disk.free_gb) + "GB</span>" : "";
        return "<span class=\"d-block\"><code>" + esc(disk.mount) + "</code> " + esc(disk.used_pct) + "%" + free + "</span>";
      })
      .join("");
  }

  function instHtml(items) {
    if (!items || !items.length) {
      return "-";
    }
    return items
      .map(function (inst) {
        var cls = inst.ok ? "bg-success-soft text-success" : "bg-danger-soft text-danger";
        var note = [];
        if (inst.cpu_pct != null) {
          note.push("CPU " + esc(inst.cpu_pct) + "%");
        }
        if (inst.mem_mb != null) {
          note.push("MEM " + esc(inst.mem_mb) + "MB");
        }
        if (inst.restarts) {
          note.push("재시작 " + esc(inst.restarts));
        }
        return (
          '<span class="badge ' + cls + '">' + esc(inst.name) + "</span>" +
          (note.length ? ' <span class="text-muted small">' + note.join(", ") + "</span>" : "") +
          "<br>"
        );
      })
      .join("");
  }

  function renderRegistered(server) {
    if (!instanceEl) {
      return;
    }
    var names = instanceMap[server] || [];
    if (!names.length) {
      instanceEl.innerHTML =
        '<span class="text-muted">없음 · 서버 목록의 정보 버튼에서 등록하세요.</span>';
      return;
    }
    var group = groups[server] || {};
    var latest = (group.snapshots || [])[0] || {};
    var reported = {};
    (latest.instances || []).forEach(function (inst) {
      reported[inst.name] = inst.ok;
    });
    instanceEl.innerHTML = names
      .map(function (name) {
        var cls = "bg-light text-muted";
        var note = "";
        if (Object.prototype.hasOwnProperty.call(reported, name)) {
          cls = reported[name] ? "bg-success-soft text-success" : "bg-danger-soft text-danger";
        } else if (latest.date) {
          note = " (최근 자료 없음)";
        }
        return '<span class="badge ' + cls + ' me-1">' + esc(name) + esc(note) + "</span>";
      })
      .join("");
  }

  function render(server) {
    var group = groups[server] || {};
    var snapshots = group.snapshots || [];
    if (!snapshots.length) {
      rows.innerHTML = '<tr><td colspan="6" class="text-muted">아직 넣은 자료가 없습니다.</td></tr>';
      return;
    }
    rows.innerHTML = snapshots
      .map(function (item) {
        var cpu = item.cpu && item.cpu.usage_pct != null ? esc(item.cpu.usage_pct) + "%" : "-";
        if (item.cpu && item.cpu.peak_pct != null) {
          cpu += ' <span class="text-muted small">최고 ' + esc(item.cpu.peak_pct) + "%</span>";
        }
        var mem = item.mem && item.mem.used_pct != null ? esc(item.mem.used_pct) + "%" : "-";
        if (item.mem && item.mem.peak_pct != null) {
          mem += ' <span class="text-muted small">최고 ' + esc(item.mem.peak_pct) + "%</span>";
        }
        return (
          "<tr><td>" +
          esc(item.date) +
          "</td><td>" +
          cpu +
          "</td><td>" +
          mem +
          "</td><td>" +
          diskHtml(item.disk) +
          "</td><td>" +
          instHtml(item.instances) +
          "</td><td>" +
          '<form method="post" action="/servers/resources/delete" onsubmit="return confirm(\'이 날짜 자료를 지울까요?\');">' +
          '<input type="hidden" name="server" value="' +
          esc(server) +
          '"><input type="hidden" name="date" value="' +
          esc(item.date) +
          '"><button class="btn btn-sm btn-outline-danger" type="submit">삭제</button></form></td></tr>'
        );
      })
      .join("");
  }

  modal.addEventListener("show.bs.modal", function (event) {
    var trigger = event.relatedTarget;
    var server = (trigger && trigger.getAttribute("data-server-name")) || "";
    if (nameEl) {
      nameEl.textContent = server;
    }
    if (bindEl) {
      bindEl.value = server;
    }
    if (serverEl) {
      serverEl.value = server;
    }
    var scriptLink = document.getElementById("resourceModalScript");
    if (scriptLink) {
      scriptLink.href = "/servers/resources/sample.sh?server=" + encodeURIComponent(server);
    }
    renderRegistered(server);
    render(server);
  });
})();
