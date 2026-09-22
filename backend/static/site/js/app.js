/*
 * Точка входа для мелкой межстраничной инициализации. Код конкретного
 * домена — в static/site/js/domains/<домен>.js, не здесь.
 */
(function ($) {
  "use strict";

  if (typeof $ === "undefined") {
    // jQuery ещё не положен в vendor/ — см. vendor/README.md.
    return;
  }

  $(function () {
    $("#js-ping").on("click", function () {
      window.alert("jQuery работает: " + $.fn.jquery);
    });

    var globalSearchRoot = document.getElementById("kc-global-search");
    if (globalSearchRoot && window.KidsCRM && window.KidsCRM.globalSearch) {
      window.KidsCRM.globalSearch.init(globalSearchRoot, {
        url: globalSearchRoot.getAttribute("data-global-search-url"),
      });
    }
  });
})(window.jQuery);
