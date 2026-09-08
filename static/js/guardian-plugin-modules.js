(function () {
  var preview = document.getElementById("script");
  var checks = Array.prototype.slice.call(document.querySelectorAll(".module-check"));
  var list = document.getElementById("plugin-instance-list");
  var addButton = document.getElementById("plugin-instance-add");
  if (!preview || !checks.length) {
    return;
  }

  var timer = null;

  function selected() {
    return checks.filter(function (box) { return box.checked; }).map(function (box) { return box.value; });
  }

  function instanceNames() {
    return Array.prototype.slice.call(document.querySelectorAll(".plugin-instance-name"))
      .map(function (el) { return (el.value || "").trim(); })
      .filter(Boolean);
  }

  function pluginName() {
    var el = document.getElementById("name") || document.getElementById("plugin-name");
    return el ? (el.value || "").trim() : "";
  }

  function previewParams() {
    var params = new URLSearchParams();
    selected().forEach(function (name) {
      params.append("modules", name);
    });
    instanceNames().forEach(function (name) {
      params.append("instances", name);
    });
    var folder = pluginName();
    if (folder) {
      params.append("name", folder);
    }
    return params;
  }

  function syncDownload() {
    var link = document.getElementById("script-download");
    if (link) {
      link.href = "/plugins/resources/preview.zip?" + previewParams().toString();
    }
  }

  function refresh() {
    var params = previewParams();
    syncDownload();
    fetch("/plugins/resources/preview?" + params.toString())
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data && data.script) {
          preview.value = data.script;
        }
      })
      .catch(function () {});
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(refresh, 180);
  }

  function bindRow(row) {
    var button = row.querySelector(".plugin-instance-remove");
    if (button) {
      button.addEventListener("click", function () {
        var rows = list ? list.querySelectorAll(".plugin-instance-item") : [];
        if (rows.length <= 1) {
          var input = row.querySelector(".plugin-instance-name");
          if (input) {
            input.value = "";
          }
        } else {
          row.remove();
        }
        schedule();
      });
    }
    var input = row.querySelector(".plugin-instance-name");
    if (input) {
      input.addEventListener("input", schedule);
    }
  }

  checks.forEach(function (box) {
    box.addEventListener("change", schedule);
  });
  document.querySelectorAll(".module-help").forEach(function (el) {
    el.addEventListener("click", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
    });
    if (window.bootstrap && bootstrap.Tooltip) {
      bootstrap.Tooltip.getOrCreateInstance(el, { container: "body", placement: "bottom" });
    }
  });
  var nameBox = document.getElementById("name");
  if (nameBox) {
    nameBox.addEventListener("input", schedule);
  }

  if (list) {
    list.querySelectorAll(".plugin-instance-item").forEach(bindRow);
  }
  if (addButton && list) {
    addButton.addEventListener("click", function () {
      var row = document.createElement("div");
      row.className = "col-md-4 mb-2 plugin-instance-item";
      row.innerHTML =
        '<div class="input-group input-group-sm">' +
        '<input class="form-control plugin-instance-name" name="plugin_instances" placeholder="qry-api">' +
        '<button class="btn btn-outline-secondary plugin-instance-remove" type="button" aria-label="빼기">−</button>' +
        "</div>";
      bindRow(row);
      list.appendChild(row);
      var input = row.querySelector(".plugin-instance-name");
      if (input) {
        input.focus();
      }
    });
  }

  syncDownload();
})();
