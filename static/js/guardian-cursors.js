(function () {
  var panel = document.getElementById("checkpoint-panel");
  var body = document.getElementById("checkpoint-body");
  var empty = document.getElementById("checkpoint-empty");
  var loading = document.getElementById("checkpoint-loading");
  var count = document.getElementById("checkpoint-count");
  if (!panel || !body) {
    return;
  }

  var PAGE_SIZE = 50;
  var offset = 0;
  var total = 0;
  var hasMore = true;
  var busy = false;

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

  function appendRows(items) {
    if (empty) {
      empty.remove();
      empty = null;
    }
    items.forEach(function (item) {
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" +
        esc(item.server_name) +
        "</td><td class=\"path\"><code>" +
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
    if (busy || !hasMore) {
      return;
    }
    busy = true;
    if (loading) {
      loading.classList.remove("d-none");
    }
    fetch("/api/checkpoints?offset=" + offset + "&limit=" + PAGE_SIZE)
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        var items = data.items || [];
        total = data.total || 0;
        hasMore = !!data.has_more;
        offset = (data.offset || offset) + items.length;
        if (count) {
          count.textContent = total ? offset + " / " + total : "";
        }
        if (items.length) {
          appendRows(items);
        } else if (offset === 0 && empty) {
          empty.classList.remove("d-none");
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

  panel.addEventListener("scroll", function () {
    if (!hasMore || busy) {
      return;
    }
    var remain = panel.scrollHeight - panel.scrollTop - panel.clientHeight;
    if (remain < 48) {
      loadPage();
    }
  });

  loadPage();
})();
