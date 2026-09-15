(function () {
  if (typeof Chart === "undefined") {
    return;
  }
  Chart.defaults.global.defaultFontFamily = "Metropolis";
  Chart.defaults.global.defaultFontColor = "#69707a";

  var STORAGE_KEY = "guardian.trend.prefs.v2";
  var DEFAULT_PREFS = { error: true, warn: true, info: true, debug: false, granularity: "hour" };
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

  function sumSeries(values) {
    return (values || []).reduce(function (total, item) {
      return total + (Number(item) || 0);
    }, 0);
  }

  function setEmptyHint(data) {
    var empty = document.getElementById("trend-empty");
    if (!empty) {
      return;
    }
    var visible = 0;
    Object.keys(LEVELS).forEach(function (key) {
      if (applied[key]) {
        visible += sumSeries(data.timeline[key]);
      }
    });
    if (visible > 0) {
      empty.classList.add("d-none");
      empty.textContent = "";
      return;
    }
    var info = sumSeries(data.timeline.info);
    var debug = sumSeries(data.timeline.debug);
    var error = sumSeries(data.timeline.error);
    var warn = sumSeries(data.timeline.warn);
    var hour = applied.granularity !== "day";
    if (info && !applied.info) {
      empty.textContent = "이 구간은 INFO 로그입니다. 오른쪽 ⚙에서 INFO를 켜면 추이가 보입니다.";
    } else if (debug && !applied.debug) {
      empty.textContent = "이 구간은 DEBUG 로그입니다. 오른쪽 ⚙에서 DEBUG를 켜면 추이가 보입니다.";
    } else if (hour && error + warn === 0) {
      empty.textContent = "최근 24시간 ERROR·WARN은 없습니다. 일자별로 바꾸면 이전 날짜 징후도 볼 수 있습니다.";
    } else {
      empty.textContent = "이 구간에 표시할 로그가 없습니다. 수집이 로그를 읽고 있는지 확인해 보세요.";
    }
    empty.classList.remove("d-none");
  }

  function render(data) {
    if (!data || !data.timeline) {
      return;
    }
    setEmptyHint(data);
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
