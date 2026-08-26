(function () {
  if (typeof Chart === "undefined") {
    return;
  }
  Chart.defaults.global.defaultFontFamily = "Metropolis";
  Chart.defaults.global.defaultFontColor = "#69707a";

  var STORAGE_KEY = "guardian.trend.prefs";
  var DEFAULT_PREFS = { error: true, warn: true, info: false, debug: false, granularity: "hour" };
  var LEVELS = {
    error: { label: "ERROR", color: "#e81500", fill: "rgba(232, 21, 0, 0.08)" },
    warn: { label: "WARN", color: "#f4a100", fill: "rgba(244, 161, 0, 0.08)" },
    info: { label: "INFO", color: "#00cfd8", fill: "rgba(0, 207, 216, 0.08)" },
    debug: { label: "DEBUG", color: "#69707a", fill: "rgba(105, 112, 122, 0.08)" },
  };

  var area = document.getElementById("chartRealtimeTrend");
  var pie = document.getElementById("chartSeverity");
  var bar = document.getElementById("chartServers");
  if (!area && !pie && !bar) {
    return;
  }

  var trendChart = null;
  var pieChart = null;
  var barChart = null;
  var applied = loadPrefs();

  function loadPrefs() {
    try {
      var saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      if (saved && typeof saved === "object") {
        return Object.assign({}, DEFAULT_PREFS, saved);
      }
    } catch (err) {
      /* ignore */
    }
    return Object.assign({}, DEFAULT_PREFS);
  }

  function savePrefs(prefs) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  }

  function readForm() {
    var prefs = loadPrefs();
    document.querySelectorAll("[data-trend-level]").forEach(function (box) {
      prefs[box.getAttribute("data-trend-level")] = box.checked;
    });
    var range = document.querySelector("input[name='trend-range']:checked");
    prefs.granularity = range && range.value === "day" ? "day" : "hour";
    if (!prefs.error && !prefs.warn && !prefs.info && !prefs.debug) {
      prefs.error = true;
    }
    return prefs;
  }

  function fillForm(prefs) {
    document.querySelectorAll("[data-trend-level]").forEach(function (box) {
      box.checked = !!prefs[box.getAttribute("data-trend-level")];
    });
    var hour = document.getElementById("trend-hour");
    var day = document.getElementById("trend-day");
    if (hour && day) {
      hour.checked = prefs.granularity !== "day";
      day.checked = prefs.granularity === "day";
    }
  }

  function bindSettings() {
    fillForm(applied);
    var apply = document.getElementById("trend-apply");
    if (apply) {
      apply.addEventListener("click", function () {
        applied = readForm();
        savePrefs(applied);
        fillForm(applied);
        refresh();
      });
    }
  }

  function sameList(a, b) {
    if (!a || !b || a.length !== b.length) {
      return false;
    }
    for (var i = 0; i < a.length; i++) {
      if (a[i] !== b[i]) {
        return false;
      }
    }
    return true;
  }

  function datasetsFrom(data) {
    return Object.keys(LEVELS)
      .filter(function (key) {
        return applied[key];
      })
      .map(function (key) {
        var meta = LEVELS[key];
        return {
          label: meta.label,
          lineTension: 0.3,
          backgroundColor: meta.fill,
          borderColor: meta.color,
          pointRadius: 3,
          pointBackgroundColor: meta.color,
          pointBorderColor: meta.color,
          borderWidth: 2,
          data: data.timeline[key] || [],
        };
      });
  }

  function patchLine(chart, labels, datasets) {
    var structureChanged =
      chart.data.datasets.length !== datasets.length ||
      !sameList(
        chart.data.datasets.map(function (item) {
          return item.label;
        }),
        datasets.map(function (item) {
          return item.label;
        })
      );
    if (structureChanged) {
      chart.data.labels = labels;
      chart.data.datasets = datasets;
      chart.update();
      return;
    }
    var changed = !sameList(chart.data.labels, labels);
    chart.data.labels = labels;
    datasets.forEach(function (ds, i) {
      if (!sameList(chart.data.datasets[i].data, ds.data)) {
        changed = true;
        chart.data.datasets[i].data = ds.data;
      }
    });
    if (changed) {
      chart.update();
    }
  }

  function patchPie(chart, labels, values) {
    if (!sameList(chart.data.labels, labels)) {
      chart.data.labels = labels;
    }
    if (!chart.data.datasets[0]) {
      return;
    }
    if (sameList(chart.data.datasets[0].data, values)) {
      return;
    }
    chart.data.datasets[0].data = values;
    chart.update();
  }

  function patchBar(chart, labels, values) {
    if (!chart.data.datasets[0]) {
      return;
    }
    if (sameList(chart.data.labels, labels) && sameList(chart.data.datasets[0].data, values)) {
      return;
    }
    chart.data.labels = labels;
    chart.data.datasets[0].data = values;
    chart.update();
  }

  function render(data) {
    if (area) {
      var tickLimit = applied.granularity === "day" ? 7 : 8;
      var datasets = datasetsFrom(data);
      if (trendChart) {
        trendChart.options.scales.xAxes[0].ticks.maxTicksLimit = tickLimit;
        patchLine(trendChart, data.timeline.labels, datasets);
      } else {
        trendChart = new Chart(area, {
          type: "line",
          data: { labels: data.timeline.labels, datasets: datasets },
          options: {
            maintainAspectRatio: false,
            animation: { duration: 400 },
            legend: { display: true },
            scales: {
              xAxes: [{ gridLines: { display: false }, ticks: { maxTicksLimit: tickLimit } }],
              yAxes: [{ ticks: { beginAtZero: true, precision: 0 }, gridLines: { color: "rgba(0, 0, 0, 0.05)" } }],
            },
          },
        });
      }
    }
    if (pie) {
      var pieLabels = data.severity.labels;
      var pieValues = data.severity.values;
      if (pieChart) {
        patchPie(pieChart, pieLabels, pieValues);
      } else {
        pieChart = new Chart(pie, {
          type: "doughnut",
          data: {
            labels: pieLabels,
            datasets: [
              {
                data: pieValues,
                backgroundColor: ["#e81500", "#f4a100", "#00cfd8", "#69707a"],
                hoverBackgroundColor: ["#c50d00", "#d58d00", "#00b6be", "#4d5560"],
              },
            ],
          },
          options: {
            maintainAspectRatio: false,
            animation: { duration: 400 },
            cutoutPercentage: 70,
            legend: { display: true, position: "bottom" },
          },
        });
      }
    }
    if (bar) {
      if (barChart) {
        patchBar(barChart, data.servers.labels, data.servers.values);
      } else {
        barChart = new Chart(bar, {
          type: "bar",
          data: {
            labels: data.servers.labels,
            datasets: [
              {
                label: "징후 건수",
                backgroundColor: "#0061f2",
                hoverBackgroundColor: "#0052cc",
                data: data.servers.values,
              },
            ],
          },
          options: {
            maintainAspectRatio: false,
            animation: { duration: 400 },
            legend: { display: false },
            scales: {
              xAxes: [{ gridLines: { display: false } }],
              yAxes: [{ ticks: { beginAtZero: true, precision: 0 }, gridLines: { color: "rgba(0, 0, 0, 0.05)" } }],
            },
          },
        });
      }
    }
  }

  function refresh() {
    fetch("/api/charts/summary?granularity=" + encodeURIComponent(applied.granularity || "hour"))
      .then(function (res) {
        return res.json();
      })
      .then(render)
      .catch(function () {
        /* 다음 주기에 재시도 */
      });
  }

  bindSettings();
  refresh();
  setInterval(refresh, 15000);
})();
