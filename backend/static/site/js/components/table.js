/*
 * Таблица: сортировка, пагинация, фильтры, пустое/загрузка, выбор строк,
 * карточное представление на мобильном (см. .kc-table--cards в
 * components.css — CSS сам превращает строки в карточки, JS только
 * проставляет data-label на каждой ячейке).
 *
 * По умолчанию работает с массивом данных на клиенте — вся сортировка/
 * фильтрация/пагинация режет один уже загруженный JS-массив. Годится для
 * списков, где реально можно отдать всё разом (справочники, филиалы и
 * т.п.), но НЕ годится для списков в тысячи строк (ТЗ п. 10.2 — 5000
 * детей, отклик ≤ 1с): отдавать 5000 строк в одном json_script и держать
 * их в памяти клиента — сам по себе бюджет не даст.
 *
 * options.remote = { url } — включает удалённый режим: страница/сортировка
 * шлются на сервер query-параметрами (page, page_size, sort, dir), сервер
 * отвечает { rows: [...], total: N } уже готовой страницей — компонент не
 * держит весь список в памяти и не сортирует/не режет на страницы сам.
 * Текстовый/произвольный фильтр (setTextFilter/setFilter) в удалённом
 * режиме не поддержан — если понадобится, его нужно будет тоже перенести
 * на сервер (query-параметр), а не резать на клиенте вперемешку с
 * серверной пагинацией (кусок данных на клиенте — не полный набор,
 * фильтровать его нечестно).
 *
 * Использование (клиентский режим — как раньше):
 *   var table = KidsCRM.table.init("#js-clients-table", {
 *     columns: [
 *       { key: "name", label: t("..."), sortable: true },
 *       { key: "phone", label: t("...") },
 *     ],
 *     pageSize: 10,
 *     selectable: true,
 *     rowKey: function (row) { return row.id; },
 *     emptyTextKey: "state.empty",
 *   });
 *   table.setData(rows);
 *   table.setTextFilter("иван", ["name", "phone"]); // поиск по колонкам
 *
 * Использование (удалённый режим):
 *   var table = KidsCRM.table.init("#js-children-table", {
 *     columns: [...],
 *     pageSize: 50,
 *     rowKey: function (row) { return row.id; },
 *     emptyTextKey: "child_list.empty",
 *     remote: { url: "/clients/children/data/" },
 *   });
 *   // Первая страница грузится сама — setData() не нужен и не должен
 *   // вызываться в этом режиме (данные всегда с сервера).
 */
(function (window, document) {
  "use strict";

  function init(elOrSelector, options) {
    var root = typeof elOrSelector === "string" ? document.querySelector(elOrSelector) : elOrSelector;
    if (!root) {
      return null;
    }
    var t = window.KidsCRM.t;

    var columns = options.columns || [];
    var pageSize = options.pageSize || 10;
    var selectable = !!options.selectable;
    var rowKey = options.rowKey || function (row, index) { return index; };
    var emptyTextKey = options.emptyTextKey || "state.empty";
    var remote = options.remote || null;

    var state = {
      data: [],
      total: 0, // только для remote — общее число строк по всем страницам
      loading: false,
      filterFn: null,
      textFilter: null,
      textFilterFields: [],
      sortKey: null,
      sortDir: "none", // none | ascending | descending
      page: 1,
      selected: {},
    };
    var listeners = {};

    root.classList.add("kc-table-wrap");
    // Пагинация — сверху, не снизу: внизу страницы её перекрывает плавающая
    // кнопка создания (.kc-fab, см. branch_list.html/room_list.html), а
    // ссылку/цифру страницы под ней нажать нельзя.
    var footer = document.createElement("div");
    footer.className = "kc-table-footer";
    footer.innerHTML =
      '<span class="kc-table-footer__info"></span><div class="kc-pagination"></div>';
    root.appendChild(footer);
    var table = document.createElement("table");
    table.className = "kc-table kc-table--cards";
    var thead = document.createElement("thead");
    var tbody = document.createElement("tbody");
    table.appendChild(thead);
    table.appendChild(tbody);
    root.appendChild(table);

    function emit(event, payload) {
      (listeners[event] || []).forEach(function (cb) {
        cb(payload);
      });
    }

    function visibleColumns() {
      return selectable
        ? [{ key: "__select", label: "", selectColumn: true }].concat(columns)
        : columns;
    }

    function renderHead() {
      var tr = document.createElement("tr");
      visibleColumns().forEach(function (col) {
        var th = document.createElement("th");
        if (col.selectColumn) {
          th.className = "kc-table__select-cell";
          var selectAll = document.createElement("input");
          selectAll.type = "checkbox";
          selectAll.setAttribute("aria-label", t("table.select_all"));
          selectAll.addEventListener("change", function () {
            getPageRows().forEach(function (row) {
              state.selected[rowKey(row)] = selectAll.checked;
            });
            render();
            emit("selectionchange", getSelected());
          });
          th.appendChild(selectAll);
        } else {
          th.textContent = col.label || col.key;
          if (col.sortable) {
            th.setAttribute("data-sortable", "true");
            th.setAttribute("tabindex", "0");
            th.setAttribute("role", "button");
            th.setAttribute(
              "aria-sort",
              state.sortKey === col.key ? state.sortDir : "none"
            );
            var icon = document.createElement("span");
            icon.className = "kc-table__sort-icon";
            th.appendChild(icon);
            var activate = function () {
              if (state.sortKey !== col.key) {
                state.sortKey = col.key;
                state.sortDir = "ascending";
              } else if (state.sortDir === "ascending") {
                state.sortDir = "descending";
              } else if (state.sortDir === "descending") {
                state.sortKey = null;
                state.sortDir = "none";
              } else {
                state.sortDir = "ascending";
              }
              if (remote) {
                // В клиентском режиме сорт не трогает текущую страницу
                // (так было и раньше) — в удалённом это другая полная
                // выборка на сервере, оставаться на той же странице не
                // имеет смысла.
                state.page = 1;
              }
              refreshData();
            };
            th.addEventListener("click", activate);
            th.addEventListener("keydown", function (event) {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                activate();
              }
            });
          }
        }
        tr.appendChild(th);
      });
      thead.innerHTML = "";
      thead.appendChild(tr);
    }

    function filteredSortedData() {
      var rows = state.data;
      if (state.filterFn) {
        rows = rows.filter(state.filterFn);
      }
      if (state.textFilter) {
        var needle = state.textFilter.toLowerCase();
        var fields = state.textFilterFields.length ? state.textFilterFields : columns.map(function (c) { return c.key; });
        rows = rows.filter(function (row) {
          return fields.some(function (key) {
            var value = row[key];
            return value != null && String(value).toLowerCase().indexOf(needle) !== -1;
          });
        });
      }
      if (state.sortKey && state.sortDir !== "none") {
        var key = state.sortKey;
        var dir = state.sortDir === "ascending" ? 1 : -1;
        rows = rows.slice().sort(function (a, b) {
          var av = a[key];
          var bv = b[key];
          if (av == null && bv == null) return 0;
          if (av == null) return -1 * dir;
          if (bv == null) return 1 * dir;
          if (av < bv) return -1 * dir;
          if (av > bv) return 1 * dir;
          return 0;
        });
      }
      return rows;
    }

    function pageCount() {
      var total = remote ? state.total : filteredSortedData().length;
      return Math.max(1, Math.ceil(total / pageSize));
    }

    function getPageRows() {
      if (remote) {
        // Сервер уже отдал ровно эту страницу, отсортированную по его
        // правилам — резать/сортировать на клиенте нечем и не нужно.
        return state.data;
      }
      var rows = filteredSortedData();
      var start = (state.page - 1) * pageSize;
      return rows.slice(start, start + pageSize);
    }

    function fetchRemotePage() {
      state.loading = true;
      render();
      var params = new URLSearchParams();
      params.set("page", String(state.page));
      params.set("page_size", String(pageSize));
      if (state.sortKey && state.sortDir !== "none") {
        params.set("sort", state.sortKey);
        params.set("dir", state.sortDir === "ascending" ? "asc" : "desc");
      }
      fetch(remote.url + "?" + params.toString(), {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      })
        .then(function (response) {
          return response.json();
        })
        .then(function (data) {
          state.data = data.rows || [];
          state.total = data.total || 0;
          state.loading = false;
          render();
        });
    }

    function refreshData() {
      if (remote) {
        fetchRemotePage();
      } else {
        render();
      }
    }

    function getSelected() {
      return state.data.filter(function (row) {
        return !!state.selected[rowKey(row)];
      });
    }

    function renderBodyMessage(message, className) {
      tbody.innerHTML = "";
      var tr = document.createElement("tr");
      var td = document.createElement("td");
      td.colSpan = visibleColumns().length;
      td.className = className;
      td.textContent = message;
      tr.appendChild(td);
      tbody.appendChild(tr);
    }

    function renderBody() {
      if (state.loading) {
        renderBodyMessage(t("state.loading"), "kc-loading");
        return;
      }
      var pageRows = getPageRows();
      if (pageRows.length === 0) {
        renderBodyMessage(t(emptyTextKey), "kc-empty-state");
        return;
      }
      tbody.innerHTML = "";
      pageRows.forEach(function (row) {
        var tr = document.createElement("tr");
        visibleColumns().forEach(function (col) {
          var td = document.createElement("td");
          if (col.selectColumn) {
            td.className = "kc-table__select-cell";
            var checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.checked = !!state.selected[rowKey(row)];
            checkbox.setAttribute("aria-label", t("table.select_row"));
            checkbox.addEventListener("change", function () {
              state.selected[rowKey(row)] = checkbox.checked;
              emit("selectionchange", getSelected());
            });
            td.appendChild(checkbox);
          } else {
            td.setAttribute("data-label", col.label || col.key);
            if (col.render) {
              var result = col.render(row);
              if (result instanceof window.Node) {
                td.appendChild(result);
              } else {
                td.textContent = result;
              }
            } else {
              td.textContent = row[col.key] == null ? "" : row[col.key];
            }
          }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    }

    function renderFooter() {
      var total = remote ? state.total : filteredSortedData().length;
      var infoEl = footer.querySelector(".kc-table-footer__info");
      infoEl.textContent = t("table.total_rows").replace("{count}", total);

      var pagination = footer.querySelector(".kc-pagination");
      pagination.innerHTML = "";
      var pages = pageCount();
      if (pages <= 1) {
        return;
      }

      function pageButton(label, page, opts) {
        opts = opts || {};
        var btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = label;
        if (opts.active) {
          btn.classList.add("kc-pagination__page--active");
        }
        if (opts.disabled) {
          btn.disabled = true;
        } else {
          btn.addEventListener("click", function () {
            state.page = page;
            refreshData();
          });
        }
        return btn;
      }

      pagination.appendChild(pageButton("‹", state.page - 1, { disabled: state.page <= 1 }));
      for (var i = 1; i <= pages; i += 1) {
        pagination.appendChild(pageButton(String(i), i, { active: i === state.page }));
      }
      pagination.appendChild(pageButton("›", state.page + 1, { disabled: state.page >= pages }));
    }

    function render() {
      if (state.page > pageCount()) {
        state.page = pageCount();
      }
      renderHead();
      renderBody();
      renderFooter();
    }

    if (remote) {
      fetchRemotePage();
    } else {
      render();
    }

    return {
      setData: function (data) {
        if (remote) {
          return; // данные всегда с сервера — внешний setData() тут не к месту
        }
        state.data = data || [];
        state.loading = false;
        state.page = 1;
        render();
      },
      setLoading: function (loading) {
        state.loading = loading;
        render();
      },
      setFilter: function (filterFn) {
        if (remote) {
          return; // не поддержано в удалённом режиме, см. комментарий выше
        }
        state.filterFn = filterFn;
        state.page = 1;
        render();
      },
      setTextFilter: function (text, fields) {
        if (remote) {
          return;
        }
        state.textFilter = text || null;
        state.textFilterFields = fields || [];
        state.page = 1;
        render();
      },
      getSelected: getSelected,
      clearSelection: function () {
        state.selected = {};
        render();
      },
      on: function (event, callback) {
        listeners[event] = listeners[event] || [];
        listeners[event].push(callback);
      },
      refresh: refreshData,
    };
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.table = { init: init };
})(window, document);
