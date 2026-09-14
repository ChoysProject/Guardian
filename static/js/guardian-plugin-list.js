(function () {
  var search = document.getElementById("plugin-search");
  var panes = document.querySelectorAll("[data-stage-pane]");
  var filters = document.querySelectorAll("[data-stage-filter]");
  if (!panes.length || !filters.length) {
    return;
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
      var active = pane.getAttribute("data-stage-pane") === stage;
      pane.classList.toggle("d-none", !active);
      if (!active) {
        return;
      }
      var groups = pane.querySelectorAll("[data-plugin-group]");
      var visible = 0;
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
  apply();
})();
