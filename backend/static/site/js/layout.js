/*
 * Каркас: burger открывает/закрывает sidebar на мобильном.
 *
 * Специально на чистом JS, без jQuery (как i18n.js) — это базовая
 * навигация, которая должна работать даже до того, как кто-то положит
 * реальные вендорные файлы в static/site/js/vendor/ (см. vendor/README.md).
 * Ставить главную навигацию в зависимость от файла, которого в
 * репозитории физически ещё нет, — не вариант.
 *
 * Хелперы состояний загрузки/пустого/ошибки — на jQuery: их будут звать
 * будущие AJAX-экраны (DataTables и т.п.), у которых jQuery к тому
 * моменту уже точно будет.
 */
(function () {
  "use strict";

  function initBurger() {
    var burger = document.getElementById("kc-burger");
    var sidebar = document.getElementById("kc-sidebar");
    if (!burger || !sidebar) {
      return;
    }

    burger.addEventListener("click", function () {
      sidebar.classList.toggle("kc-sidebar--open");
    });

    var links = sidebar.querySelectorAll(".kc-sidebar__link");
    for (var i = 0; i < links.length; i += 1) {
      links[i].addEventListener("click", function () {
        sidebar.classList.remove("kc-sidebar--open");
      });
    }
  }

  // Скрипт подключён в конце <body> — DOMContentLoaded к этому моменту
  // иногда уже успевает отработать (наблюдалось в headless-браузере при
  // тестировании), и повторно он не сработает. Проверяем readyState, а не
  // слепо вешаемся на событие.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initBurger);
  } else {
    initBurger();
  }
})();

(function ($) {
  "use strict";

  if (typeof $ === "undefined") {
    return;
  }

  window.KidsCRM = window.KidsCRM || {};

  window.KidsCRM.showLoading = function (container) {
    $(container).html(
      '<div class="kc-loading"><span class="kc-spinner"></span><span data-i18n="state.loading">Загрузка...</span></div>'
    );
    window.KidsCRM.applyI18n($(container).get(0));
  };

  window.KidsCRM.showEmpty = function (container, textKey) {
    $(container).html(
      '<div class="kc-empty-state"><span data-i18n="' + textKey + '">Пусто</span></div>'
    );
    window.KidsCRM.applyI18n($(container).get(0));
  };

  window.KidsCRM.showError = function (container, textKey) {
    $(container).html(
      '<div class="kc-error-state"><span data-i18n="' + textKey + '">Ошибка</span></div>'
    );
    window.KidsCRM.applyI18n($(container).get(0));
  };
})(window.jQuery);
