/*
 * Общий "оживитель" сторонних виджетов внутри формы: Select2 на
 * select[multiple] (направления, филиалы — списки, которые растут, чекбоксы
 * не масштабируются), bootstrap-datepicker на [data-datefield] (даты —
 * везде по сайту, ТЗ п. 10.4 не про это, но UX-договорённость), Dropzone на
 * .dropzone[data-upload-url] (загрузка фото).
 *
 * Один вызов enhance(root) — и для обычной загрузки страницы (DOMContentLoaded,
 * root=document), и после вставки AJAX-фрагмента в модалку (modal.js вызывает
 * его сам на .modal-body) — фрагменты вставляются через innerHTML, встроенный
 * в них <script> не выполнился бы (см. form-modal.js, formset.js — та же
 * причина), поэтому инициализация живёт здесь, а не в самой форме.
 */
(function (window, document, $) {
  "use strict";

  if (window.Dropzone) {
    // Иначе Dropzone сам находит все .dropzone на странице по DOMContentLoaded
    // и инициализирует их без наших опций/колбэков — до того, как мы дойдём
    // сюда со своими handlers (URL загрузки, привязка к скрытому полю).
    window.Dropzone.autoDiscover = false;
  }

  function getCsrfToken() {
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function initSelect2(root) {
    if (!$ || !$.fn || !$.fn.select2) {
      return;
    }
    $(root)
      .find("select[multiple]")
      .each(function () {
        if (this.dataset.select2Inited) {
          return;
        }
        this.dataset.select2Inited = "true";
        $(this).select2({ width: "100%" });
      });
  }

  function initDatepickers(root) {
    if (!$ || !$.fn || !$.fn.datepicker) {
      return;
    }
    // Маркер поля называется data-datefield, а не data-datepicker: если
    // назвать его так же, как ключ, под которым сам jQuery-плагин хранит
    // свой инстанс ($el.data('datepicker')), браузер через dataset
    // заводит data-datepicker="true" в кэш jQuery.data ДО инициализации
    // плагина — плагин видит там уже истинное значение и молча не создаёт
    // календарь (без ошибок, без обработчиков событий).
    $(root)
      .find("[data-datefield]")
      .each(function () {
        if (this.dataset.datefieldInited) {
          return;
        }
        this.dataset.datefieldInited = "true";
        $(this).datepicker({
          format: "dd.mm.yyyy",
          language: "ru",
          autoclose: true,
          todayHighlight: true,
          weekStart: 1,
        });
      });
  }

  function initDropzones(root) {
    if (!window.Dropzone) {
      return;
    }
    var elements = root.querySelectorAll(".dropzone[data-upload-url]");
    elements.forEach(function (el) {
      if (el.dataset.dropzoneInited) {
        return;
      }
      el.dataset.dropzoneInited = "true";

      var targetInput = document.getElementById(el.dataset.target);
      var previewImg = el.dataset.preview ? document.getElementById(el.dataset.preview) : null;
      var t = window.KidsCRM.t;

      var dz = new window.Dropzone(el, {
        url: el.dataset.uploadUrl,
        paramName: "file",
        maxFiles: 1,
        acceptedFiles: "image/*",
        headers: { "X-CSRFToken": getCsrfToken() },
        dictDefaultMessage: t("child_form.photo_dropzone_hint"),
      });

      dz.on("success", function (file, response) {
        if (!response || !response.url) {
          return;
        }
        if (targetInput) {
          targetInput.value = response.url;
        }
        if (previewImg) {
          previewImg.src = response.url;
          previewImg.hidden = false;
        }
      });

      dz.on("maxfilesexceeded", function (file) {
        // Ограничение на одно фото — новое заменяет предыдущее в очереди,
        // а не отклоняется молча.
        dz.removeFile(dz.files[0]);
        dz.addFile(file);
      });

      dz.on("error", function (file, message) {
        window.KidsCRM.toast.error(
          typeof message === "string" ? message : t("child_form.photo_upload_error")
        );
        dz.removeFile(file);
      });
    });
  }

  function enhance(root) {
    root = root || document;
    initSelect2(root);
    initDatepickers(root);
    initDropzones(root);
    initConditionalFields(root);
  }

  /*
   * Общий механизм "показать поле только при таком-то значении другого
   * поля" — например, "Причина ухода" видна только при статусе "Ушёл"
   * (см. ChildForm.status: data-conditional-trigger="child_status" и
   * _child_form_fields.html: data-show-when="child_status=left"). Не
   * специфично для одной формы — тем же способом можно завязать любое
   * поле на любой select в будущем, без нового JS на каждую форму.
   */
  function initConditionalFields(root) {
    var triggers = root.querySelectorAll("[data-conditional-trigger]");
    triggers.forEach(function (trigger) {
      if (trigger.dataset.conditionalInited) {
        return;
      }
      trigger.dataset.conditionalInited = "true";
      var name = trigger.dataset.conditionalTrigger;
      var dependents = root.querySelectorAll('[data-show-when^="' + name + '="]');

      function update() {
        dependents.forEach(function (field) {
          var expected = field.dataset.showWhen.split("=")[1];
          field.hidden = trigger.value !== expected;
        });
      }

      trigger.addEventListener("change", update);
      update();
    });
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.enhanceForms = enhance;

  document.addEventListener("DOMContentLoaded", function () {
    enhance(document);
  });
})(window, document, window.jQuery);
