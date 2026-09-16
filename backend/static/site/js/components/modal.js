/*
 * Обёртка над Bootstrap Modal + готовое подтверждение опасных действий
 * (удаление и т.п.), чтобы верстать confirm-диалог руками не пришлось на
 * каждой странице отдельно.
 *
 * Использование:
 *   KidsCRM.modal.confirmDanger({
 *     title: "Удалить ребёнка?",
 *     message: "Действие нельзя отменить.",
 *   }).then(function (confirmed) { if (confirmed) { ... } });
 */
(function (window, document, $) {
  "use strict";

  if (typeof $ === "undefined" || typeof window.bootstrap === "undefined") {
    return;
  }

  var MODAL_ID = "kc-shared-modal";

  function getModalEl() {
    var el = document.getElementById(MODAL_ID);
    if (el) {
      return el;
    }
    el = document.createElement("div");
    el.id = MODAL_ID;
    el.className = "modal kc-modal";
    el.tabIndex = -1;
    el.innerHTML =
      '<div class="modal-dialog">' +
      '<div class="modal-content">' +
      '<div class="modal-header">' +
      '<h5 class="modal-title"></h5>' +
      '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
      "</div>" +
      '<div class="modal-body"></div>' +
      '<div class="modal-footer"></div>' +
      "</div></div>";
    document.body.appendChild(el);
    return el;
  }

  /**
   * options: { title, bodyHtml|bodyText, size, buttons: [{ text, variant, value, onClick }] }
   * bodyEl — .modal-body передаётся в onClick(bodyEl), чтобы кнопка могла
   * прочитать/подменить содержимое (AJAX-формы, см. branch_list.html).
   * onClick может вернуть false (или промис, резолвящийся в false) — тогда
   * модалка не закрывается (например, сервер вернул ошибки валидации).
   * Без onClick кнопка ведёт себя как раньше — сразу закрывает модалку.
   * Возвращает Promise, который резолвится значением нажатой кнопки
   * (или undefined, если закрыли крестиком/Esc/фоном).
   */
  function open(options) {
    var el = getModalEl();
    el.querySelector(".modal-title").textContent = options.title || "";
    el.querySelector(".modal-dialog").className =
      "modal-dialog" + (options.size ? " modal-" + options.size : "");

    var body = el.querySelector(".modal-body");
    if (options.bodyHtml) {
      body.innerHTML = options.bodyHtml;
    } else {
      body.textContent = options.bodyText || "";
    }

    var footer = el.querySelector(".modal-footer");
    footer.innerHTML = "";
    var buttons = options.buttons || [];

    return new Promise(function (resolve) {
      var resolved = false;
      var bsModal = window.bootstrap.Modal.getOrCreateInstance(el);

      function finish(value) {
        if (!resolved) {
          resolved = true;
          resolve(value);
        }
        bsModal.hide();
      }

      buttons.forEach(function (btnDef) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "kc-btn " + (btnDef.variant ? "kc-btn--" + btnDef.variant : "kc-btn--secondary");
        btn.textContent = btnDef.text;
        btn.addEventListener("click", function () {
          if (!btnDef.onClick) {
            finish(btnDef.value);
            return;
          }
          var originalText = btn.textContent;
          btn.disabled = true;
          Promise.resolve(btnDef.onClick(body)).then(
            function (shouldClose) {
              btn.disabled = false;
              btn.textContent = originalText;
              if (shouldClose !== false) {
                finish(btnDef.value);
              }
            },
            function () {
              btn.disabled = false;
              btn.textContent = originalText;
            }
          );
        });
        footer.appendChild(btn);
      });

      el.addEventListener(
        "hidden.bs.modal",
        function onHidden() {
          el.removeEventListener("hidden.bs.modal", onHidden);
          if (!resolved) {
            resolved = true;
            resolve(undefined);
          }
        },
        { once: true }
      );

      bsModal.show();
    });
  }

  /**
   * Готовый confirm для опасных действий (удаление, отмена подписки и т.п.)
   * — единообразная разметка/кнопки во всём приложении вместо window.confirm.
   */
  function confirmDanger(options) {
    var t = window.KidsCRM.t;
    return open({
      title: options.title || t("modal.confirm_title"),
      bodyText: options.message || "",
      buttons: [
        { text: options.cancelText || t("modal.cancel"), variant: "secondary", value: false },
        { text: options.confirmText || t("modal.confirm_delete"), variant: "danger", value: true },
      ],
    }).then(function (value) {
      return value === true;
    });
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.modal = {
    open: open,
    confirmDanger: confirmDanger,
  };
})(window, document, window.jQuery);
