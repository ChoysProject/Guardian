(function () {
  // data-picker 가 붙은 select 는 보기 좋은 목록으로 바꿔 단다.
  // 값은 원래 select 가 그대로 들고 있어서 폼 전송은 달라지지 않는다.
  document.querySelectorAll("select[data-picker]").forEach(function (select) {
    var wrap = document.createElement("div");
    wrap.className = "dropdown guardian-picker";
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    select.classList.add("d-none");

    var button = document.createElement("button");
    button.type = "button";
    button.className = "form-select text-start guardian-picker-toggle";
    button.setAttribute("data-bs-toggle", "dropdown");
    button.setAttribute("aria-expanded", "false");
    wrap.appendChild(button);

    var menu = document.createElement("div");
    menu.className = "dropdown-menu shadow guardian-picker-menu";
    wrap.appendChild(menu);

    var empty = select.getAttribute("data-picker-empty") || "고르세요";

    function paint() {
      var current = select.value;
      var picked = select.options[select.selectedIndex];
      button.textContent = picked ? picked.text.trim() : empty;
      menu.querySelectorAll(".dropdown-item").forEach(function (item) {
        item.classList.toggle("active", item.getAttribute("data-value") === current);
      });
    }

    Array.prototype.forEach.call(select.options, function (option) {
      var item = document.createElement("button");
      item.type = "button";
      item.className = "dropdown-item";
      item.setAttribute("data-value", option.value);
      var label = document.createElement("span");
      label.className = "guardian-picker-name";
      label.textContent = option.text.trim();
      item.appendChild(label);
      var desc = (option.getAttribute("data-desc") || "").trim();
      if (desc) {
        var hint = document.createElement("span");
        hint.className = "guardian-picker-desc";
        hint.textContent = desc;
        item.appendChild(hint);
      }
      item.addEventListener("click", function () {
        select.value = option.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        paint();
      });
      menu.appendChild(item);
    });

    select.addEventListener("change", paint);
    paint();
  });

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
