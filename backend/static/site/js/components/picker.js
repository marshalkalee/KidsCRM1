/*
 * Выбор ребёнка/родителя — обёртка над Select2 (поиск по вводу, годится
 * для длинных списков). Модели Child/Parent пока не существуют (появятся
 * в доменном тикете people/clients), поэтому здесь — заглушечные данные и
 * готовый AJAX-режим, который останется просто включить, подставив
 * реальный урл, когда endpoint появится.
 *
 * Использование (пока без бэкенда — статические данные):
 *   KidsCRM.picker.initChildPicker("#js-child-select");
 *
 * Использование (когда появится реальный endpoint):
 *   KidsCRM.picker.initChildPicker("#js-child-select", {
 *     ajaxUrl: "/api/children/search/",
 *   });
 */
(function (window, document, $) {
  "use strict";

  if (typeof $ === "undefined" || typeof $.fn === "undefined" || typeof $.fn.select2 === "undefined") {
    return;
  }

  // Заглушка — убрать, когда появится реальный endpoint поиска детей/родителей.
  var PLACEHOLDER_CHILDREN = [
    { id: "c1", text: "Иванов Алихан, 7 лет" },
    { id: "c2", text: "Смагулова Айым, 9 лет" },
    { id: "c3", text: "Петров Тимур, 5 лет" },
  ];

  var PLACEHOLDER_PARENTS = [
    { id: "p1", text: "Иванова Гульнара (мама)" },
    { id: "p2", text: "Смагулов Ержан (папа)" },
    { id: "p3", text: "Петрова Анна (мама)" },
  ];

  function initPicker(elOrSelector, placeholderData, placeholderTextKey, options) {
    var el = typeof elOrSelector === "string" ? document.querySelector(elOrSelector) : elOrSelector;
    if (!el) {
      return null;
    }
    options = options || {};
    var t = window.KidsCRM.t;

    var config = {
      width: "100%",
      placeholder: t(placeholderTextKey),
      allowClear: true,
      dropdownParent: $(el).closest(".modal").length ? $(el).closest(".modal") : $(document.body),
    };

    if (options.ajaxUrl) {
      config.ajax = {
        url: options.ajaxUrl,
        dataType: "json",
        delay: 300,
        data: function (params) {
          return { q: params.term, page: params.page || 1 };
        },
        processResults: function (data) {
          return { results: data.results, pagination: { more: !!data.has_more } };
        },
      };
      config.minimumInputLength = 1;
    } else {
      config.data = placeholderData;
    }

    $(el).select2(config);

    return {
      destroy: function () {
        $(el).select2("destroy");
      },
      getValue: function () {
        return $(el).val();
      },
    };
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.picker = {
    initChildPicker: function (elOrSelector, options) {
      return initPicker(elOrSelector, PLACEHOLDER_CHILDREN, "picker.select_child", options);
    },
    initParentPicker: function (elOrSelector, options) {
      return initPicker(elOrSelector, PLACEHOLDER_PARENTS, "picker.select_parent", options);
    },
  };
})(window, document, window.jQuery);
