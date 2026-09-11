/*
 * Своя i18n-система: window.KidsCRM.t(key) + обход DOM по data-i18n.
 * Словарь на текущий язык — window.KidsCRM_I18N[lang], собран
 * backend/scripts/build_i18n_bundle.py в i18n-bundle.js (грузится раньше
 * этого файла в base.html).
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
    var scope = root || document;
    var nodes = scope.querySelectorAll("[data-i18n]");
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      var key = node.getAttribute("data-i18n");
      node.textContent = t(key);
    }
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.t = t;
  window.KidsCRM.applyI18n = applyToDom;

  document.addEventListener("DOMContentLoaded", function () {
    applyToDom(document);
  });
})(window, document);
