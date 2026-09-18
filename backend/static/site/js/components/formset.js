/*
 * Динамическое добавление строк Django-формсета (например, телефонов
 * родителя) без отдельного JS на каждую форму. Разметка:
 *   <div data-formset="phones">
 *     {{ formset.management_form }}
 *     <div data-formset-rows>...существующие формы формсета...</div>
 *     <button type="button" data-formset-add>+ Добавить</button>
 *     <template data-formset-empty>{{ formset.empty_form }}</template>
 *   </div>
 *
 * Слушатель — на document, а не на самой кнопке: form-modal.js вставляет
 * фрагмент формы через innerHTML (без выполнения встроенных <script>), так
 * что обработчик, повешенный внутри фрагмента, не сработал бы — делегирование
 * с document переживает любую динамическую вставку.
 */
(function (window, document) {
  "use strict";

  document.addEventListener("click", function (e) {
    var addBtn = e.target.closest("[data-formset-add]");
    if (!addBtn) {
      return;
    }
    var root = addBtn.closest("[data-formset]");
    if (!root) {
      return;
    }
    var prefix = root.getAttribute("data-formset");
    var totalFormsInput = root.querySelector('input[name="' + prefix + '-TOTAL_FORMS"]');
    var rowsContainer = root.querySelector("[data-formset-rows]");
    var emptyTemplate = root.querySelector("template[data-formset-empty]");
    if (!totalFormsInput || !rowsContainer || !emptyTemplate) {
      return;
    }

    var index = parseInt(totalFormsInput.value, 10);
    var html = emptyTemplate.innerHTML.replace(/__prefix__/g, String(index));
    var wrapper = document.createElement("div");
    wrapper.innerHTML = html;
    while (wrapper.firstChild) {
      rowsContainer.appendChild(wrapper.firstChild);
    }
    totalFormsInput.value = String(index + 1);

    // Новая строка — свежие DOM-узлы (innerHTML их пересобрал с нуля), они
    // не переведены (см. i18n.js) и не знают о Select2/datepicker
    // (form-enhance.js) — то же самое, что и после AJAX-вставки формы в
    // модалку (modal.js), просто другой источник вставки.
    if (window.KidsCRM.applyI18n) {
      window.KidsCRM.applyI18n(rowsContainer);
    }
    if (window.KidsCRM.enhanceForms) {
      window.KidsCRM.enhanceForms(rowsContainer);
    }
  });
})(window, document);
