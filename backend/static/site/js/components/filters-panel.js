/*
 * Панель фильтров списка (ТЗ п. 4.1: филиал/направление/группа/статус/
 * долг/абонемент) — комбинируются между собой, состояние живёт в URL
 * (ссылку с фильтрами можно переслать коллеге — открывается в том же
 * виде), последний набор — в localStorage, восстанавливается только
 * когда в URL фильтров нет вообще. Если хотя бы один фильтр есть в URL,
 * он важнее localStorage — иначе открытая по ссылке коллеги страница
 * подмешивала бы твои собственные старые фильтры вместо присланных.
 *
 * На мобильном панель — не всегда видимая боковая колонка, а отдельный
 * полноэкранный слой, открывается кнопкой вне root (см. .kc-filters-panel
 * в components.css и [data-filters-toggle] ниже).
 *
 * Разметка:
 *   - внутри root: элементы [data-filter="<key>"] (select или checkbox),
 *     необязательная [data-filters-reset], необязательная [data-filters-close]
 *   - вне root: необязательная [data-filters-toggle] (кнопка "Фильтры" —
 *     открывает root на мобильном), необязательная [data-filters-count]
 *     (текст счётчика — обновляется через panel.setCount())
 *
 * Использование:
 *   var panel = KidsCRM.filtersPanel.init(document.getElementById("..."), {
 *     storageKey: "child_list_filters",
 *     onChange: function (values) { table.setRemoteParams(values); },
 *   });
 *   table.on("load", function (data) { panel.setCount(data.total); });
 */
(function (window, document) {
  "use strict";

  function filterKeys(root) {
    return Array.prototype.map.call(root.querySelectorAll("[data-filter]"), function (el) {
      return el.getAttribute("data-filter");
    });
  }

  function readValues(root) {
    var values = {};
    root.querySelectorAll("[data-filter]").forEach(function (el) {
      var key = el.getAttribute("data-filter");
      values[key] = el.type === "checkbox" ? (el.checked ? el.value || "1" : "") : el.value || "";
    });
    return values;
  }

  function applyValues(root, values) {
    root.querySelectorAll("[data-filter]").forEach(function (el) {
      var key = el.getAttribute("data-filter");
      var value = (values && values[key]) || "";
      if (el.type === "checkbox") {
        el.checked = !!value;
      } else {
        el.value = value;
      }
    });
  }

  function readFromUrl(root) {
    var params = new URLSearchParams(window.location.search);
    var keys = filterKeys(root);
    if (!keys.some(function (key) { return params.has(key); })) {
      return null;
    }
    var values = {};
    keys.forEach(function (key) {
      values[key] = params.get(key) || "";
    });
    return values;
  }

  function writeToUrl(values) {
    var url = new URL(window.location.href);
    Object.keys(values).forEach(function (key) {
      if (values[key]) {
        url.searchParams.set(key, values[key]);
      } else {
        url.searchParams.delete(key);
      }
    });
    window.history.replaceState(null, "", url.toString());
  }

  function init(root, options) {
    if (!root) {
      return null;
    }
    options = options || {};
    var t = window.KidsCRM.t;
    var storageKey = "kc.filters." + (options.storageKey || "list");
    var onChange = options.onChange || function () {};
    // Счётчик может стоять и рядом с мобильной кнопкой-переключателем, и в
    // самой панели (десктоп) — оба варианта одновременно в разметке
    // (просто скрыты друг от друга через CSS), поэтому обновляем все.
    var countEls = document.querySelectorAll("[data-filters-count]");
    var toggleBtn = document.querySelector("[data-filters-toggle]");
    var closeBtn = root.querySelector("[data-filters-close]");
    var resetBtn = root.querySelector("[data-filters-reset]");

    function loadStored() {
      try {
        var raw = window.localStorage.getItem(storageKey);
        return raw ? JSON.parse(raw) : null;
      } catch (e) {
        return null;
      }
    }

    function saveStored(values) {
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(values));
      } catch (e) {
        // приватный режим/квота — не критично, просто не переживёт визит
      }
    }

    function commit(values) {
      writeToUrl(values);
      saveStored(values);
      onChange(values);
    }

    root.querySelectorAll("[data-filter]").forEach(function (el) {
      el.addEventListener("change", function () {
        commit(readValues(root));
      });
    });

    if (resetBtn) {
      resetBtn.addEventListener("click", function () {
        applyValues(root, {});
        // Не commit({}) — writeToUrl только проходит по ключам ПЕРЕДАННОГО
        // объекта, пустой объект не знает, какие параметры удалять из уже
        // открытого URL. readValues(root) после applyValues() отдаёт полный
        // набор ключей с пустыми значениями — тогда writeToUrl реально
        // подчистит все фильтры.
        commit(readValues(root));
      });
    }

    function close() {
      root.classList.remove("kc-filters-panel--open");
    }

    if (toggleBtn) {
      toggleBtn.addEventListener("click", function () {
        root.classList.add("kc-filters-panel--open");
      });
    }
    if (closeBtn) {
      closeBtn.addEventListener("click", close);
    }

    var initial = readFromUrl(root) || loadStored() || {};
    applyValues(root, initial);
    commit(initial);

    return {
      setCount: function (count) {
        var text = t("filters_panel.found_count").replace("{count}", count);
        countEls.forEach(function (el) {
          el.textContent = text;
        });
      },
      getValues: function () {
        return readValues(root);
      },
      close: close,
    };
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.filtersPanel = { init: init };
})(window, document);
