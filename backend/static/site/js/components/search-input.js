/*
 * Поле поиска с задержкой ввода (debounce) — общий хелпер, чтобы каждый
 * список (клиенты, дети, платежи...) не писал свой setTimeout вручную.
 *
 * Использование:
 *   KidsCRM.searchInput.init("#js-client-search", {
 *     onSearch: function (value) { ... },
 *     delay: 350, // мс, по умолчанию 300
 *   });
 */
(function (window, document) {
  "use strict";

  function init(elOrSelector, options) {
    var el =
      typeof elOrSelector === "string" ? document.querySelector(elOrSelector) : elOrSelector;
    if (!el) {
      return null;
    }

    var delay = options.delay || 300;
    var onSearch = options.onSearch || function () {};
    var timer = null;

    function trigger() {
      var value = el.value.trim();
      window.clearTimeout(timer);
      var wrap = el.closest(".kc-search-input");
      if (wrap) {
        wrap.classList.add("kc-search-input--loading");
      }
      timer = window.setTimeout(function () {
        Promise.resolve(onSearch(value)).then(function () {
          if (wrap) {
            wrap.classList.remove("kc-search-input--loading");
          }
        });
      }, delay);
    }

    el.addEventListener("input", trigger);

    // Enter — искать сразу, без ожидания задержки (частый UX-паттерн).
    el.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        window.clearTimeout(timer);
        onSearch(el.value.trim());
      }
    });

    return {
      destroy: function () {
        window.clearTimeout(timer);
        el.removeEventListener("input", trigger);
      },
    };
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.searchInput = { init: init };
})(window, document);
