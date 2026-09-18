/*
 * Формы: клиентская валидация, показ ошибок сервера, состояние отправки
 * (спиннер на кнопке), защита от повторной отправки, предупреждение о
 * несохранённых изменениях. Работает с обычной Django-разметкой — поле
 * должно быть обёрнуто в .kc-field с дочерним .kc-field__error (см.
 * пример на dev/components.html).
 *
 * Использование:
 *   var form = KidsCRM.form.init("#js-demo-form", {
 *     onSubmit: function (data, helpers) {
 *       // AJAX-запрос; при ошибках сервера — helpers.showServerErrors({...})
 *       // при успехе — helpers.markClean()
 *       helpers.done();
 *     },
 *   });
 */
(function (window, document, $) {
  "use strict";

  function fieldWrap(input) {
    return input.closest(".kc-field") || input.parentElement;
  }

  function setFieldError(input, message) {
    var wrap = fieldWrap(input);
    wrap.classList.add("kc-field--invalid");
    var errorEl = wrap.querySelector(".kc-field__error");
    if (errorEl) {
      errorEl.textContent = message || "";
    }
  }

  function clearFieldError(input) {
    var wrap = fieldWrap(input);
    wrap.classList.remove("kc-field--invalid");
    var errorEl = wrap.querySelector(".kc-field__error");
    if (errorEl) {
      errorEl.textContent = "";
    }
  }

  function getFields(form) {
    return Array.prototype.slice.call(form.querySelectorAll("input, select, textarea"));
  }

  function validateField(input) {
    if (input.validity.valid) {
      clearFieldError(input);
      return true;
    }
    var t = window.KidsCRM.t;
    var message = input.validationMessage;
    if (input.validity.valueMissing) {
      message = input.getAttribute("data-error-required") || t("form.error_required");
    } else if (input.validity.typeMismatch || input.validity.patternMismatch) {
      message = input.getAttribute("data-error-invalid") || t("form.error_invalid");
    }
    setFieldError(input, message);
    return false;
  }

  function setBusy(form, busy) {
    var submitBtn = form.querySelector('[type="submit"]');
    if (!submitBtn) {
      return;
    }
    if (busy) {
      submitBtn.disabled = true;
      if (!submitBtn.hasAttribute("data-original-html")) {
        submitBtn.setAttribute("data-original-html", submitBtn.innerHTML);
      }
      submitBtn.innerHTML = '<span class="kc-spinner"></span>' + submitBtn.getAttribute("data-original-html");
    } else {
      submitBtn.disabled = false;
      if (submitBtn.hasAttribute("data-original-html")) {
        submitBtn.innerHTML = submitBtn.getAttribute("data-original-html");
      }
    }
  }

  /**
   * errors: { field_name: "текст" | ["текст", ...], __all__: "текст" | [...] }
   * Ключи — по атрибуту name поля (как в DRF/Django form.errors).
   */
  function showServerErrors(form, errors) {
    errors = errors || {};
    Object.keys(errors).forEach(function (name) {
      var messages = errors[name];
      var message = Array.isArray(messages) ? messages[0] : messages;
      if (name === "__all__" || name === "non_field_errors") {
        window.KidsCRM.toast.error(message);
        return;
      }
      var input = form.querySelector('[name="' + name + '"]');
      if (input) {
        setFieldError(input, message);
      } else {
        window.KidsCRM.toast.error(message);
      }
    });
  }

  function init(formOrSelector, options) {
    var form =
      typeof formOrSelector === "string" ? document.querySelector(formOrSelector) : formOrSelector;
    if (!form) {
      return null;
    }
    options = options || {};

    var isDirty = false;
    var isSubmitting = false;
    var suppressUnsavedWarning = false;

    function onFieldChange() {
      isDirty = true;
    }
    getFields(form).forEach(function (input) {
      input.addEventListener("input", onFieldChange);
      input.addEventListener("change", onFieldChange);
      input.addEventListener("blur", function () {
        if (input.value !== "" || input.required) {
          validateField(input);
        }
      });
    });

    function onBeforeUnload(event) {
      if (isDirty && !suppressUnsavedWarning) {
        event.preventDefault();
        event.returnValue = "";
        return "";
      }
    }
    window.addEventListener("beforeunload", onBeforeUnload);

    function markClean() {
      isDirty = false;
    }

    function done() {
      isSubmitting = false;
      setBusy(form, false);
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();

      // Защита от повторной отправки — второй клик/Enter во время
      // "висящего" запроса игнорируется, а не шлёт дубликат.
      if (isSubmitting) {
        return;
      }

      var fields = getFields(form);
      var allValid = fields.reduce(function (ok, input) {
        return validateField(input) && ok;
      }, true);
      if (!allValid) {
        return;
      }

      isSubmitting = true;
      setBusy(form, true);

      var data = new window.FormData(form);
      if (options.onSubmit) {
        options.onSubmit(data, {
          form: form,
          done: done,
          markClean: markClean,
          showServerErrors: function (errors) {
            showServerErrors(form, errors);
          },
        });
      } else {
        done();
      }
    });

    return {
      form: form,
      markClean: markClean,
      showServerErrors: function (errors) {
        showServerErrors(form, errors);
      },
      destroy: function () {
        window.removeEventListener("beforeunload", onBeforeUnload);
      },
      // Для программной навигации сразу после успешного сохранения —
      // чтобы диалог "несохранённые изменения" не всплывал зря.
      navigateAway: function (url) {
        suppressUnsavedWarning = true;
        window.location.href = url;
      },
    };
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.form = { init: init, showServerErrors: showServerErrors };
})(window, document, window.jQuery);
