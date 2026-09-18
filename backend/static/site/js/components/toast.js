/*
 * Тосты/уведомления — единообразно во всех местах, где раньше был бы
 * alert() или молчаливая ошибка. Своя реализация (не Bootstrap Toast):
 * нужен один общий контейнер и очередь, а не разметка тоста на каждой
 * странице вручную.
 *
 * Использование:
 *   KidsCRM.toast.success("Сохранено");
 *   KidsCRM.toast.error("Не удалось сохранить");
 *   KidsCRM.toast.show({ type: "warning", text: "...", timeout: 8000 });
 */
(function (window, document) {
  "use strict";

  var CONTAINER_ID = "kc-toast-container";
  var DEFAULT_TIMEOUT = 5000;

  function getContainer() {
    var el = document.getElementById(CONTAINER_ID);
    if (!el) {
      el = document.createElement("div");
      el.id = CONTAINER_ID;
      el.className = "kc-toast-container";
      el.setAttribute("role", "status");
      el.setAttribute("aria-live", "polite");
      document.body.appendChild(el);
    }
    return el;
  }

  function dismiss(node) {
    if (node.parentNode) {
      node.parentNode.removeChild(node);
    }
  }

  function show(options) {
    if (typeof options === "string") {
      options = { text: options };
    }
    var type = options.type || "info";
    var timeout = options.timeout === 0 ? 0 : options.timeout || DEFAULT_TIMEOUT;

    var node = document.createElement("div");
    node.className = "kc-toast kc-toast--" + type;
    node.setAttribute("role", "alert");

    var body = document.createElement("div");
    body.className = "kc-toast__body";
    body.textContent = options.text || "";
    node.appendChild(body);

    var closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "kc-toast__close";
    closeBtn.setAttribute("aria-label", window.KidsCRM.t("common.close"));
    closeBtn.textContent = "×";
    closeBtn.addEventListener("click", function () {
      dismiss(node);
    });
    node.appendChild(closeBtn);

    getContainer().appendChild(node);

    if (timeout > 0) {
      window.setTimeout(function () {
        dismiss(node);
      }, timeout);
    }

    return node;
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.toast = {
    show: show,
    success: function (text, options) {
      return show(Object.assign({}, options, { type: "success", text: text }));
    },
    error: function (text, options) {
      return show(Object.assign({}, options, { type: "danger", text: text }));
    },
    warning: function (text, options) {
      return show(Object.assign({}, options, { type: "warning", text: text }));
    },
    info: function (text, options) {
      return show(Object.assign({}, options, { type: "info", text: text }));
    },
  };
})(window, document);
