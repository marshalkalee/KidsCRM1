/*
 * Лента коммуникаций (вкладка ребёнка + сводная на карточке родителя) —
 * общая логика схлопывания и фильтра по датам, чтобы не держать её
 * дважды в двух шаблонах:
 *   - по умолчанию видны только последние N записей (данные уже
 *     отсортированы новыми вперёд, см. CommunicationLog.Meta.ordering);
 *     остальные — по кнопке "Показать старые записи". Это ПОРЯДКОВОЕ
 *     схлопывание (после N-й записи), не по времени/дате;
 *   - фильтр по датам — отдельная, независимая функция: находит записи в
 *     диапазоне и на время фильтра показывает вообще все совпадения
 *     (переопределяет схлопывание, а не комбинируется с ним — если ищут
 *     конкретное, схлопывание только мешало бы).
 *
 * Разметка — templates/includes/communications_feed.html, вставляется в
 * контейнер с data-comm-root (сам контейнер передаётся сюда явно, а не
 * ищется по фиксированному id — на одной странице разметка используется
 * только один раз, но id должен оставаться уникальным для каждого места
 * использования).
 *
 * Использование:
 *   KidsCRM.communicationsFeed.init(document.getElementById("..."), rows, {
 *     showChildName: true,       // строка meta: автор · дата · ребёнок
 *     showContactName: true,     // строка meta: автор · дата · контакт
 *     emptyTextKey: "communications.empty",
 *   });
 */
(function (window, document) {
  "use strict";

  var RECENT_COUNT = 5;

  function isoDateFromPicker(value) {
    // datepicker пишет "dd.mm.yyyy" (form-enhance.js), row.date у нас
    // "yyyy-mm-dd" (см. web_views.py) — сравнивать нужно в одном формате.
    var parts = (value || "").split(".");
    return parts.length === 3 ? parts[2] + "-" + parts[1] + "-" + parts[0] : null;
  }

  function renderItem(row, options, t) {
    var item = document.createElement("div");
    item.className = "kc-timeline__item";

    var badge = document.createElement("span");
    badge.className = "kc-badge kc-badge--blue";
    badge.textContent = t("choices.communication_channel." + row.channel_code);
    item.appendChild(badge);

    var note = document.createElement("p");
    note.className = "kc-timeline__note";
    note.textContent = row.note;
    item.appendChild(note);

    var metaParts = [row.author, row.date_display];
    if (options.showChildName && row.child_name) {
      metaParts.push(row.child_name);
    }
    if (options.showContactName && row.contact_name) {
      metaParts.push(row.contact_name);
    }
    var meta = document.createElement("div");
    meta.className = "kc-timeline__meta";
    meta.textContent = metaParts.join(" · ");
    item.appendChild(meta);

    return item;
  }

  function init(root, rows, options) {
    if (!root) {
      return null;
    }
    options = options || {};
    var t = window.KidsCRM.t;
    var feedEl = root.querySelector("[data-comm-feed]");
    var toggleBtn = root.querySelector("[data-comm-toggle]");
    var fromInput = root.querySelector("[data-comm-date-from]");
    var toInput = root.querySelector("[data-comm-date-to]");
    var resetBtn = root.querySelector("[data-comm-reset]");
    var showingAll = false;

    function render() {
      var from = isoDateFromPicker(fromInput.value);
      var to = isoDateFromPicker(toInput.value);
      var filtering = !!(from || to);

      var filtered = rows.filter(function (row) {
        if (from && row.date < from) {
          return false;
        }
        if (to && row.date > to) {
          return false;
        }
        return true;
      });

      var visible = filtering || showingAll ? filtered : filtered.slice(0, RECENT_COUNT);

      feedEl.innerHTML = "";
      if (visible.length === 0) {
        var empty = document.createElement("p");
        empty.className = "kc-empty-state";
        empty.textContent = t(options.emptyTextKey || "state.empty");
        feedEl.appendChild(empty);
      } else {
        visible.forEach(function (row) {
          feedEl.appendChild(renderItem(row, options, t));
        });
      }

      if (filtering || filtered.length <= RECENT_COUNT) {
        toggleBtn.hidden = true;
      } else {
        toggleBtn.hidden = false;
        toggleBtn.textContent = showingAll
          ? t("communications_feed.show_recent")
          : t("communications_feed.show_older");
      }
    }

    toggleBtn.addEventListener("click", function () {
      showingAll = !showingAll;
      render();
    });

    resetBtn.addEventListener("click", function () {
      fromInput.value = "";
      toInput.value = "";
      showingAll = false;
      render();
    });

    if (window.jQuery) {
      // changeDate — событие bootstrap-datepicker (jQuery, не нативное DOM
      // "change"), см. form-enhance.js; "change" — на случай ручного
      // ввода/очистки поля мимо календаря.
      window.jQuery([fromInput, toInput]).on("changeDate change", render);
    }

    render();
    return { refresh: render };
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.communicationsFeed = { init: init };
})(window, document);
