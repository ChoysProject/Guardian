// 폼을 제출하면 브라우저가 새 페이지를 완전히 새로 불러오면서 스크롤이 맨 위로
// 돌아간다. 같은 화면으로 되돌아오는 액션(수집, 저장, 오류 지우기 등)은 보던
// 위치 그대로 있는 게 자연스러우니, 제출 직전 위치를 남겨 두고 다시 그 화면일
// 때만 복원한다.
(function () {
  var STORAGE_PREFIX = "guardianScrollY:";

  function keyFor(pathname) {
    return STORAGE_PREFIX + pathname;
  }

  document.addEventListener(
    "submit",
    function (event) {
      var form = event.target;
      if (!(form instanceof HTMLFormElement)) {
        return;
      }
      var method = (form.getAttribute("method") || "get").toLowerCase();
      if (method !== "post") {
        return;
      }
      try {
        sessionStorage.setItem(keyFor(window.location.pathname), String(window.scrollY));
      } catch (err) {
        // 저장 공간을 못 쓰는 환경이면 그냥 예전처럼 맨 위에서 시작한다.
      }
    },
    true
  );

  function restore() {
    var key = keyFor(window.location.pathname);
    var saved;
    try {
      saved = sessionStorage.getItem(key);
      if (saved != null) {
        sessionStorage.removeItem(key);
      }
    } catch (err) {
      return;
    }
    if (saved == null) {
      return;
    }
    var y = parseInt(saved, 10);
    if (isNaN(y)) {
      return;
    }
    window.scrollTo(0, y);
    // 이미지·폰트가 늦게 자리 잡으며 레이아웃이 밀리는 경우를 대비해 한 번 더 맞춘다.
    setTimeout(function () {
      window.scrollTo(0, y);
    }, 80);
  }

  if (document.readyState === "complete" || document.readyState === "interactive") {
    restore();
  } else {
    document.addEventListener("DOMContentLoaded", restore);
  }
})();
