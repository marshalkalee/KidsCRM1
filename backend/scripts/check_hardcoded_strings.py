#!/usr/bin/env python
"""
Ловит захардкоженные строки интерфейса в шаблонах (ТЗ п. 10.1 — все
строки в файлах локализации, ни одной строки в коде). Не полноценный
HTML+Django-парсер, а практичная эвристика:

- Текст внутри элемента с атрибутом data-i18n — разрешён (это и есть
  фолбэк для JS-подмены, см. static/site/js/i18n.js).
- Текст внутри <script>/<style> — код, не UI-текст, не проверяется.
- {% block title %}...{% endblock %} — тайтл вкладки браузера, не через
  data-i18n (см. ADR/обсуждение в PR) — сознательное исключение, не дырка.
- Всё остальное с "живыми" буквами (не только {{ }}/{% %}/{# #} и пробелы)
  — подозрительная захардкоженная строка.

Запуск: python backend/scripts/check_hardcoded_strings.py
Exit code 1 и список находок, если что-то нашлось — используется в
pre-commit и CI (см. .pre-commit-config.yaml, .github/workflows/ci.yml).
"""

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BACKEND_DIR / "templates"

DJANGO_BLOCK_RE = re.compile(r"\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}", re.DOTALL)
HAS_LETTERS_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ]{2,}")
TITLE_BLOCK_RE = re.compile(
    r"\{%\s*block\s+title\s*%\}.*?\{%\s*endblock(?:\s+title)?\s*%\}", re.DOTALL
)

SKIP_TAGS = {"script", "style"}
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class HardcodedStringChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.findings: list[tuple[int, str]] = []
        self._stack: list[dict] = []

    def _protected(self) -> bool:
        return any(frame["has_i18n"] or frame["skip"] for frame in self._stack)

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            return
        has_i18n = any(name == "data-i18n" for name, _ in attrs)
        self._stack.append({"has_i18n": has_i18n, "skip": tag in SKIP_TAGS})

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if self._protected():
            return
        stripped = DJANGO_BLOCK_RE.sub(" ", data)
        if HAS_LETTERS_RE.search(stripped):
            line = self.getpos()[0]
            snippet = data.strip().replace("\n", " ")[:80]
            self.findings.append((line, snippet))


def check_file(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    text = TITLE_BLOCK_RE.sub(" ", text)
    checker = HardcodedStringChecker()
    checker.feed(text)
    return checker.findings


def main() -> int:
    had_findings = False
    for path in sorted(TEMPLATES_DIR.rglob("*.html")):
        for line, snippet in check_file(path):
            had_findings = True
            rel = path.relative_to(BACKEND_DIR.parent)
            print(f"{rel}:{line}: захардкоженный текст без data-i18n: {snippet!r}")

    if had_findings:
        print(
            "\nНайден текст интерфейса не через data-i18n — добавь атрибут "
            'data-i18n="ключ" на элемент и сам ключ в backend/i18n_src/*.json.'
        )
        return 1

    print("Захардкоженных строк не найдено.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
