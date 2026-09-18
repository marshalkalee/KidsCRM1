# Вендорные библиотеки

Кладутся сюда как обычные файлы, без пакетного менеджера — подключаются
`<script>`/`<link>`-тегами напрямую (см. `backend/templates/base.html`).
Ничего не собирается, версии фиксируются именем файла/комментарием в шапке.

## Уже есть (скачаны с официальных CDN, версии зафиксированы)

| Файл | Библиотека | Версия | Источник |
|---|---|---|---|
| `jquery.min.js` | jQuery | 3.5.1 | code.jquery.com |
| `bootstrap.bundle.min.js` + `../css/vendor/bootstrap.min.css` | Bootstrap (bundle с Popper) | 5.3.3 | cdnjs.cloudflare.com |
| `select2.min.js` + `../css/vendor/select2.min.css` | Select2 | 4.1.0-rc.0 | cdnjs.cloudflare.com |

Обновлять версию — заменить файл целиком и поправить эту таблицу, не
патчить содержимое вручную.

## Ещё не добавлены — понадобятся в других тикетах

Взять из уже существующего продукта AEM Solutions с тем же стеком (там
уже проверенные версии), либо скачать заново, когда дойдёт до задачи,
которая их требует:

| Файл | Библиотека | Версия |
|---|---|---|
| `datatables.min.js` + css | DataTables | — |
| `fullcalendar.min.js` + css | FullCalendar | — |
| `chart.min.js` | Chart.js | — |
| `bootstrap-datepicker.min.js` + css | bootstrap-datepicker | — |
| `dropzone.min.js` + css | Dropzone | — |
| `sortable.min.js` | Sortable | — |
| `tagify.min.js` + css | Tagify | — |
| `quill.min.js` + css | Quill | — |

До появления этих файлов конкретные страницы, которым они нужны,
рендерятся без вёрстки/интерактивности этих плагинов (браузер просто не
найдёт `<script src="...">` — 404, страница не ломается), но не
функциональны как задумано.
