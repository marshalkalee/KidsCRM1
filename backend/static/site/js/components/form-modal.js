/*
 * Открывает форму создания/редактирования в модалке на полупрозрачном
 * фоне (как в макете Дарьи) вместо перехода на отдельную страницу.
 * Сервер отдаёт ту же форму двумя способами (см. web_views.py,
 * _is_ajax()): обычная навигация — полная страница; запрос с заголовком
 * X-Requested-With — только фрагмент с полями (без <form>/кнопок), его
 * этот модуль вставляет в тело модалки.
 *
 * Использование:
 *   window.KidsCRM.formModal.open({
 *     url: row.edit_url,
 *     title: t("branch_form.title_edit"),
 *   }).then(function (saved) { if (saved) location.reload(); });
 */
(function (window, document) {
  "use strict";

  function serialize(container) {
    var formData = new FormData();
    var fields = container.querySelectorAll("input, select, textarea");
    for (var i = 0; i < fields.length; i += 1) {
      var el = fields[i];
      if (!el.name) {
        continue;
      }
      if (el.type === "checkbox") {
        if (el.checked) {
          formData.append(el.name, el.value || "on");
        }
      } else {
        formData.append(el.name, el.value);
      }
    }
    return formData;
  }

  function submit(url, bodyEl) {
    return fetch(url, {
      method: "POST",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      body: serialize(bodyEl),
    }).then(function (response) {
      var contentType = response.headers.get("content-type") || "";
      if (contentType.indexOf("application/json") !== -1) {
        return true;
      }
      // Сервер вернул фрагмент формы заново — с ошибками валидации и уже
      // введёнными значениями (Django bound form), просто подменяем тело.
      return response.text().then(function (html) {
        bodyEl.innerHTML = html;
        return false;
      });
    });
  }

  /**
   * options: { url, title, saveText, cancelText }
   * Возвращает Promise<boolean> — true, если форма была успешно сохранена.
   */
  function open(options) {
    var t = window.KidsCRM.t;
    return fetch(options.url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (response) {
        return response.text();
      })
      .then(function (html) {
        return window.KidsCRM.modal.open({
          title: options.title,
          bodyHtml: html,
          buttons: [
            { text: options.cancelText || t("branch_form.cancel"), variant: "secondary", value: false },
            {
              text: options.saveText || t("branch_form.save"),
              variant: "primary",
              value: true,
              onClick: function (bodyEl) {
                return submit(options.url, bodyEl);
              },
            },
          ],
        });
      })
      .then(function (saved) {
        return saved === true;
      });
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.formModal = { open: open };
})(window, document);
