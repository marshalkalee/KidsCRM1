/*
 * Таблица: сортировка, пагинация, фильтры, пустое/загрузка, выбор строк,
 * карточное представление на мобильном (см. .kc-table--cards в
 * components.css — CSS сам превращает строки в карточки, JS только
 * проставляет data-label на каждой ячейке).
 *
 * Работает с массивом данных на клиенте (пока нет реальных списков с
 * бэкенда — Child/Parent и т.п. появятся в других тикетах). Загрузка с
 * сервера подключается через setLoading()/setData() снаружи — сам
 * компонент не делает предположений про формат API.
 *
 * Использование:
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

    var state = {
      data: [],
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
    var table = document.createElement("table");
    table.className = "kc-table kc-table--cards";
    var thead = document.createElement("thead");
    var tbody = document.createElement("tbody");
    table.appendChild(thead);
    table.appendChild(tbody);
    root.appendChild(table);
    var footer = document.createElement("div");
    footer.className = "kc-table-footer";
    footer.innerHTML =
      '<span class="kc-table-footer__info"></span><div class="kc-pagination"></div>';
    root.appendChild(footer);

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
              render();
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
      return Math.max(1, Math.ceil(filteredSortedData().length / pageSize));
    }

    function getPageRows() {
      var rows = filteredSortedData();
      var start = (state.page - 1) * pageSize;
      return rows.slice(start, start + pageSize);
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
      var total = filteredSortedData().length;
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
            render();
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

    render();

    return {
      setData: function (data) {
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
        state.filterFn = filterFn;
        state.page = 1;
        render();
      },
      setTextFilter: function (text, fields) {
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
      refresh: render,
    };
  }

  window.KidsCRM = window.KidsCRM || {};
  window.KidsCRM.table = { init: init };
})(window, document);
