# Вендорные библиотеки

Кладутся сюда как обычные файлы, без пакетного менеджера — подключаются
`<script>`/`<link>`-тегами напрямую (см. `backend/templates/base.html`).
Ничего не собирается, версии фиксируются именем файла/комментарием в шапке.

Не добавлены в этот коммит — взять из уже существующего продукта
AEM Solutions с тем же стеком (там уже проверенные версии), либо скачать
заново. Нужны как минимум:

| Файл | Библиотека | Версия |
|---|---|---|
| `jquery.min.js` | jQuery | 3.5.1 |
| `bootstrap.bundle.min.js` + `../css/vendor/bootstrap.min.css` | Bootstrap (bundle с Popper) | зафиксировать при добавлении |
| `select2.min.js` + css | Select2 | — |
| `datatables.min.js` + css | DataTables | — |
| `fullcalendar.min.js` + css | FullCalendar | — |
| `chart.min.js` | Chart.js | — |
| `bootstrap-datepicker.min.js` + css | bootstrap-datepicker | — |
| `dropzone.min.js` + css | Dropzone | — |
| `sortable.min.js` | Sortable | — |
| `tagify.min.js` + css | Tagify | — |
| `quill.min.js` + css | Quill | — |

До появления этих файлов страницы рендерятся без вёрстки/интерактивности
плагинов (браузер просто не найдёт `<script src="...">` — 404, страница не
ломается), но не функциональны как задумано.
