/*
 * Глобальный поиск в шапке (ТЗ п. 4.1) — по имени ребёнка, имени
 * родителя и телефону одним полем, доступен с любого экрана (base.html),
 * не только со списка детей.
 *
 * Задержка ввода — через существующий searchInput (debounce). Отмена
 * устаревших запросов — свой AbortController: без него быстрый повторный
 * ввод может отрисовать результат уже неактуального запроса, если он
 * ответит позже более нового (обычная гонка сетевых ответов при вводе).
 *
 * Разметка — templates/includes/header_search.html.
 *
 * Использование:
 *   KidsCRM.globalSearch.init(document.getElementById("kc-global-search"), {
 *     url: "/clients/search/",
 *   });
 */
(function (window, document) {
  "use strict";

  var MIN_LENGTH = 3;

  function matchedLine(item, t) {
    if (item.matched_on === "parent_name" && item.matched_detail) {
      return t("global_search.matched_parent_name") + ": " + item.matched_detail;
    }
    if (item.matched_on === "phone") {
      return item.matched_detail
        ? t("global_search.matched_phone") + ": " + item.matched_detail
        : t("global_search.matched_phone");
    }
    return null;
  }

  function renderResults(resultsEl, items, t) {
    resultsEl.innerHTML = "";

    if (items.length === 0) {
      var empty = document.createElement("p");
      empty.className = "kc-empty-state";
      empty.textContent = t("global_search.no_results");
      resultsEl.appendChild(empty);
      resultsEl.hidden = false;
      return;
    }

    items.forEach(function (item) {
      var link = document.createElement("a");
      link.className = "kc-global-search__item";
      link.href = item.url;

      var badge = document.createElement("span");
      badge.className =
        "kc-badge " + (item.type === "parent" ? "kc-badge--purple" : "kc-badge--blue");
      badge.textContent = t("global_search.type_" + item.type);
      link.appendChild(badge);

      var text = document.createElement("span");
      text.className = "kc-global-search__item-text";

      var title = document.createElement("span");
      title.className = "kc-global-search__item-title";
      title.textContent = item.title;
      text.appendChild(title);

      var detail = matchedLine(item, t);
      if (detail) {
        var sub = document.createElement("span");
        sub.className = "kc-global-search__item-sub";
        sub.textContent = detail;
        text.appendChild(sub);
      }

      link.appendChild(text);
      resultsEl.appendChild(link);
    });
    resultsEl.hidden = false;
  }

  function init(root, options) {
    if (!root) {
      return null;
    }
    options = options || {};
    var url = options.url;
    var t = window.KidsCRM.t;
    var input = root.querySelector("input");
    var resultsEl = root.querySelector("[data-global-search-results]");
    var toggleBtn = root.querySelector("[data-global-search-toggle]");
    var closeBtn = root.querySelector("[data-global-search-close]");
    var controller = null;

    function hideResults() {
      resultsEl.hidden = true;
    }

    // Открыть/закрыть — только мобильный вид (иконка вместо постоянного
    // поля, см. components.css); на десктопе кнопок нет (display: none),
    // эти функции просто никогда не вызываются оттуда.
    function openOverlay() {
      root.classList.add("kc-global-search--open");
      input.focus();
    }

    function closeOverlay() {
      root.classList.remove("kc-global-search--open");
      hideResults();
      input.value = "";
    }

    function search(value) {
      if (controller) {
        controller.abort();
      }
      if (!value || value.length < MIN_LENGTH) {
        hideResults();
        return Promise.resolve();
      }
      controller = new AbortController();
      return fetch(url + "?q=" + encodeURIComponent(value), { signal: controller.signal })
        .then(function (response) {
          return response.json();
        })
        .then(function (data) {
          renderResults(resultsEl, data.results || [], t);
        })
        .catch(function (error) {
          // AbortError — обычный результат отмены устаревшего запроса, не
          // ошибка для пользователя; молча ничего не меняем.
          if (error.name !== "AbortError") {
            hideResults();
          }
        });
    }

    window.KidsCRM.searchInput.init(input, { onSearch: search, delay: 300 });

    if (toggleBtn) {
      toggleBtn.addEventListener("click", openOverlay);
    }
    if (closeBtn) {
      closeBtn.addEventListener("click", closeOverlay);
    }

    document.addEventListener("click", function (event) {
      if (!root.contains(event.target)) {
        hideResults();
      }
    });

    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        if (root.classList.contains("kc-global-search--open")) {
          closeOverlay();
        } else {
          hideResults();
          input.blur();
        }
      }
    });

    input.addEventListener("focus", function () {
      if (input.value.trim().length >= MIN_LENGTH && resultsEl.children.length > 0) {
        resultsEl.hidden = false;
      }
    });

    return { search: search };
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.globalSearch = { init: init };
})(window, document);
