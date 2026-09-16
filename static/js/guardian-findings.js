(function () {
  var root = document.querySelector("[data-findings]");
  if (!root) {
    return;
  }

  var search = document.getElementById("finding-search");
  var serverSel = document.getElementById("finding-server");
  var rows = Array.prototype.slice.call(root.querySelectorAll("[data-finding-row]"));
  var empty = document.getElementById("finding-empty-filter");
  var severity = "all";
  var when = root.getAttribute("data-default-when") || "all";
  var readState = root.getAttribute("data-default-read") || "open";

  function mark(buttons, attr, value) {
    buttons.forEach(function (btn) {
      var on = btn.getAttribute(attr) === value;
      btn.classList.toggle("btn-primary", on);
      btn.classList.toggle("btn-outline-secondary", !on);
    });
  }

  function setCount(key, value) {
    var el = root.querySelector('[data-count="' + key + '"]');
    if (el) {
      el.textContent = String(value);
    }
  }

  function apply() {
    var query = ((search && search.value) || "").trim().toLowerCase();
    var server = (serverSel && serverSel.value) || "";
    var visible = 0;
    var open = 0;
    var read = 0;
    var all = 0;
    var error = 0;
    var warn = 0;
    var today = 0;
    rows.forEach(function (row) {
      var hay = (row.getAttribute("data-search") || "").toLowerCase();
      var sev = row.getAttribute("data-severity") || "";
      var isToday = row.getAttribute("data-today") === "1";
      var srv = row.getAttribute("data-server") || "";
      var isRead = row.getAttribute("data-read") === "1";
      if (isRead) {
        read += 1;
      } else {
        open += 1;
      }
      var inRead = readState === "all" || (readState === "read" && isRead) || (readState === "open" && !isRead);
      if (inRead) {
        all += 1;
        if (sev === "error") {
          error += 1;
        }
        if (sev === "warn") {
          warn += 1;
        }
        if (isToday) {
          today += 1;
        }
      }
      var ok = inRead;
      if (query && hay.indexOf(query) === -1) {
        ok = false;
      }
      if (severity !== "all" && sev !== severity) {
        ok = false;
      }
      if (when === "today" && !isToday) {
        ok = false;
      }
      if (server && srv !== server) {
        ok = false;
      }
      row.classList.toggle("d-none", !ok);
      if (ok) {
        visible += 1;
      }
    });
    setCount("open", open);
    setCount("read", read);
    setCount("all", all);
    setCount("error", error);
    setCount("warn", warn);
    setCount("today", today);
    if (empty) {
      empty.classList.toggle("d-none", visible > 0);
      if (!visible) {
        empty.querySelector("td").textContent =
          readState === "open" && !query && !server && severity === "all" && when !== "today"
            ? "열린 징후가 없습니다. 읽은 것에서 다시 볼 수 있습니다."
            : "조건에 맞는 징후가 없습니다.";
      }
    }
    mark(Array.prototype.slice.call(root.querySelectorAll("[data-finding-severity]")), "data-finding-severity", severity);
    mark(Array.prototype.slice.call(root.querySelectorAll("[data-finding-when]")), "data-finding-when", when);
    mark(Array.prototype.slice.call(root.querySelectorAll("[data-finding-read]")), "data-finding-read", readState);
  }

  root.querySelectorAll("[data-finding-severity]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      severity = btn.getAttribute("data-finding-severity") || "all";
      apply();
    });
  });
  root.querySelectorAll("[data-finding-when]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      when = btn.getAttribute("data-finding-when") || "all";
      apply();
    });
  });
  root.querySelectorAll("[data-finding-read]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      readState = btn.getAttribute("data-finding-read") || "open";
      apply();
    });
  });
  if (search) {
    search.addEventListener("input", apply);
  }
  if (serverSel) {
    serverSel.addEventListener("change", apply);
  }
  apply();
})();
