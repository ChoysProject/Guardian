(function () {
  var search = document.getElementById("plugin-search");
  var panes = Array.prototype.slice.call(document.querySelectorAll("[data-stage-pane]"));
  var filters = Array.prototype.slice.call(document.querySelectorAll("[data-stage-filter]"));
  var list = document.querySelector("[data-plugin-list]");
  if (!panes.length && list) {
    panes = [list];
  }

  var stage = "1";
  var filterHost = document.querySelector("[data-initial-stage]");
  var params = new URLSearchParams(window.location.search);
  var requested = (params.get("stage") || (filterHost && filterHost.getAttribute("data-initial-stage")) || "1").trim();
  if (requested === "1" || requested === "2" || requested === "3") {
    stage = requested;
  }

  function apply() {
    var query = ((search && search.value) || "").trim().toLowerCase();
    filters.forEach(function (btn) {
      var on = btn.getAttribute("data-stage-filter") === stage;
      btn.classList.toggle("btn-primary", on);
      btn.classList.toggle("btn-outline-secondary", !on);
    });
    panes.forEach(function (pane) {
      var paneStage = pane.getAttribute("data-stage-pane");
      var active = !paneStage || paneStage === stage;
      if (paneStage) {
        pane.classList.toggle("d-none", !active);
      }
      if (!active) {
        return;
      }
      var groups = pane.querySelectorAll("[data-plugin-group]");
      var visible = 0;
      if (!groups.length) {
        pane.querySelectorAll("[data-plugin-card]").forEach(function (card) {
          var hay = (card.getAttribute("data-search") || "").toLowerCase();
          var ok = !query || hay.indexOf(query) !== -1;
          card.classList.toggle("d-none", !ok);
          if (ok) {
            visible += 1;
          }
        });
      } else {
        groups.forEach(function (group) {
          var cards = group.querySelectorAll("[data-plugin-card]");
          var shown = 0;
          cards.forEach(function (card) {
            var hay = (card.getAttribute("data-search") || "").toLowerCase();
            var ok = !query || hay.indexOf(query) !== -1;
            card.classList.toggle("d-none", !ok);
            if (ok) {
              shown += 1;
            }
          });
          group.classList.toggle("d-none", shown === 0);
          visible += shown;
        });
      }
      var empty = pane.querySelector("[data-plugin-empty-search]");
      if (empty) {
        empty.classList.toggle("d-none", !query || visible > 0);
      }
    });
  }

  filters.forEach(function (btn) {
    btn.addEventListener("click", function () {
      stage = btn.getAttribute("data-stage-filter") || "1";
      apply();
    });
  });
  if (search) {
    search.addEventListener("input", apply);
  }
  if (panes.length || search) {
    apply();
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-plugin-more]");
    if (!btn) {
      return;
    }
    ev.preventDefault();
    var box = btn.closest(".plugin-chips");
    if (!box) {
      return;
    }
    var extras = box.querySelectorAll(".is-extra");
    var open = btn.getAttribute("aria-expanded") === "true";
    extras.forEach(function (el) {
      el.classList.toggle("d-none", open);
    });
    btn.setAttribute("aria-expanded", open ? "false" : "true");
    btn.textContent = open ? ("+" + extras.length + "개 더보기") : "접기";
  });
})();
