(function () {
  function flashFromHash() {
    var id = (window.location.hash || "").replace(/^#/, "");
    if (!id) {
      return;
    }
    var el = document.getElementById(id);
    if (!el) {
      return;
    }
    el.classList.remove("is-flash");
    void el.offsetWidth;
    el.classList.add("is-flash");
    window.setTimeout(function () {
      el.classList.remove("is-flash");
    }, 2000);
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeRegExp(text) {
    return String(text).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function markServers() {
    var node = document.getElementById("overviewServerNames");
    if (!node) {
      return;
    }
    var names;
    try {
      names = JSON.parse(node.textContent || "[]");
    } catch (err) {
      return;
    }
    if (!Array.isArray(names) || !names.length) {
      return;
    }
    names = names
      .map(function (item) {
        return String(item || "").trim();
      })
      .filter(Boolean)
      .sort(function (left, right) {
        return right.length - left.length;
      });
    document.querySelectorAll(".js-overview-mark").forEach(function (el) {
      var html = escapeHtml(el.textContent || "");
      names.forEach(function (name) {
        html = html.replace(new RegExp(escapeRegExp(name), "g"), '<span class="overview-server">$&</span>');
      });
      el.innerHTML = html;
    });
  }

  document.querySelectorAll("a.overview-focus, a.overview-stack").forEach(function (link) {
    link.addEventListener("click", function () {
      window.setTimeout(flashFromHash, 40);
    });
  });
  window.addEventListener("hashchange", flashFromHash);
  markServers();
  if (window.location.hash) {
    flashFromHash();
  }

  if (typeof Chart === "undefined") {
    return;
  }
  var canvas = document.getElementById("chartOverviewHealth");
  var node = document.getElementById("overviewChartData");
  if (!canvas || !node) {
    return;
  }
  var payload;
  try {
    payload = JSON.parse(node.textContent || "{}");
  } catch (err) {
    return;
  }
  var health = payload.health || {};
  var raw = [
    { label: "위험", value: health.danger || 0, color: "#e81500" },
    { label: "주의", value: health.warn || 0, color: "#f4a100" },
    { label: "여유", value: health.ok || 0, color: "#00ac69" },
    { label: "대기", value: health.waiting || 0, color: "#d0d5dd" },
  ];
  var slices = raw.filter(function (item) {
    return item.value > 0;
  });
  if (!slices.length) {
    slices = [{ label: "대기", value: 1, color: "#d0d5dd" }];
  }
  new Chart(canvas.getContext("2d"), {
    type: "doughnut",
    data: {
      labels: slices.map(function (item) {
        return item.label;
      }),
      datasets: [
        {
          data: slices.map(function (item) {
            return item.value;
          }),
          backgroundColor: slices.map(function (item) {
            return item.color;
          }),
          borderWidth: 0,
        },
      ],
    },
    options: {
      cutoutPercentage: 76,
      rotation: -0.5 * Math.PI,
      circumference: 2 * Math.PI,
      animation: { duration: 0 },
      responsive: true,
      maintainAspectRatio: false,
      legend: { display: false },
      tooltips: {
        callbacks: {
          label: function (item, data) {
            var label = data.labels[item.index] || "";
            var value = data.datasets[0].data[item.index] || 0;
            return " " + label + " " + value + "대";
          },
        },
      },
    },
  });
})();
