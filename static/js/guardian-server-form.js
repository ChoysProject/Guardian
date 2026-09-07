(function () {
  // 인증 방식에 따라 비밀번호 칸과 키 칸을 번갈아 보여 준다.
  var selector = document.querySelector(".auth-type");
  if (selector) {
    var sync = function () {
      var mode = selector.value;
      document.querySelectorAll(".auth-password").forEach(function (el) {
        el.classList.toggle("d-none", mode !== "password");
      });
      document.querySelectorAll(".auth-key").forEach(function (el) {
        el.classList.toggle("d-none", mode !== "key");
      });
    };
    selector.addEventListener("change", sync);
    sync();
  }

  // 인스턴스 칸 늘리고 줄이기
  var list = document.getElementById("instance-list");
  var addButton = document.getElementById("instance-add");
  if (!list || !addButton) {
    return;
  }

  function bindRemove(row) {
    var button = row.querySelector(".instance-remove");
    if (button) {
      button.addEventListener("click", function () {
        row.remove();
      });
    }
  }

  list.querySelectorAll(".instance-item").forEach(bindRemove);

  addButton.addEventListener("click", function () {
    var row = document.createElement("div");
    row.className = "col-md-4 mb-2 instance-item";
    row.innerHTML =
      '<div class="input-group input-group-sm">' +
      '<input class="form-control" name="instances" placeholder="was">' +
      '<button class="btn btn-outline-secondary instance-remove" type="button" aria-label="빼기">−</button>' +
      "</div>";
    bindRemove(row);
    list.appendChild(row);
  });
})();
