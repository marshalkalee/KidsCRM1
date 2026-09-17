/*
 * Своя i18n-система: window.KidsCRM.t(key) + обход DOM по data-i18n.
 * Словарь на текущий язык — window.KidsCRM_I18N[lang], собран
 * backend/scripts/build_i18n_bundle.py в i18n-bundle.js (грузится раньше
 * этого файла в base.html).
 *
 * Для дефолтного языка (ru) источник правды — сам текст в HTML, а не
 * словарь: applyToDom() его не трогает, поэтому правка русского текста —
 * обычные правка+рефреш, без пересборки бандла. Словарь подключается
 * (applyToDom реально подменяет текст) только для не-дефолтных языков —
 * это тот же путь, что понадобится переключателю языка (kk/en), когда он
 * появится: он просто меняет document.documentElement.lang, остальное уже
 * готово. window.KidsCRM.t(key) при этом всегда читает словарь на любом
 * языке — нужен для JS-текста, у которого нет HTML-фолбэка (например,
 * динамические сообщения).
 */
(function (window, document) {
  "use strict";

  var DEFAULT_LANG = "ru";

  function currentLang() {
    return document.documentElement.lang || DEFAULT_LANG;
  }

  function t(key, lang) {
    var dict = (window.KidsCRM_I18N || {})[lang || currentLang()] || {};
    return Object.prototype.hasOwnProperty.call(dict, key) ? dict[key] : key;
  }

  function applyToDom(root) {
    if (currentLang() === DEFAULT_LANG) {
      return;
    }

    var scope = root || document;
    var nodes = scope.querySelectorAll("[data-i18n]");
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      var key = node.getAttribute("data-i18n");
      node.textContent = t(key);
    }

    // <option> — не текстовый узел с data-i18n, а атрибут value/label
    // django-виджета (Select из TextChoices, см. Child.Status и т.п.) —
    // применяем словарь по паре "группа" (data-i18n-choices на <select>) +
    // "значение" (option.value), а не по самому тексту (тот на русском и
    // меняется от локали к локали, а value — стабильный код).
    var selects = scope.querySelectorAll("[data-i18n-choices]");
    for (var s = 0; s < selects.length; s += 1) {
      var select = selects[s];
      var group = select.getAttribute("data-i18n-choices");
      var options = select.querySelectorAll("option");
      for (var o = 0; o < options.length; o += 1) {
        var option = options[o];
        if (!option.value) {
          continue;
        }
        option.textContent = t("choices." + group + "." + option.value);
      }
    }
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.t = t;
  window.KidsCRM.applyI18n = applyToDom;

  // Скрипт подключён в конце <body> — DOMContentLoaded к этому моменту
  // иногда уже успевает отработать (см. layout.js), и повторно он не
  // сработает. Для ru это незаметно (applyToDom — no-op выше), но сломает
  // переключение на kk/en, когда оно появится. Проверяем readyState.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      applyToDom(document);
    });
  } else {
    applyToDom(document);
  }
})(window, document);
