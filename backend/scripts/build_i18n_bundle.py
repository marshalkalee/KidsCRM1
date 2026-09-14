#!/usr/bin/env python
"""
Собирает словари i18n_src/<locale>.json в один JS-бандл
static/site/js/i18n-bundle.js, который отдаёт window.KidsCRM_I18N.

Запуск: python backend/scripts/build_i18n_bundle.py
"""

import json
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BACKEND_DIR / "i18n_src"
OUT_FILE = BACKEND_DIR / "static" / "site" / "js" / "i18n-bundle.js"


def build() -> None:
    bundle: dict[str, dict[str, str]] = {}
    for path in sorted(SRC_DIR.glob("*.json")):
        locale = path.stem
        with path.open(encoding="utf-8") as f:
            bundle[locale] = json.load(f)

    if not bundle:
        raise SystemExit(f"Нет словарей в {SRC_DIR}")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "// Автогенерируемый файл — не редактировать руками.\n"
        "// Пересобрать: python backend/scripts/build_i18n_bundle.py\n"
        "// Источник: backend/i18n_src/*.json\n"
    )
    body = "window.KidsCRM_I18N = " + json.dumps(bundle, ensure_ascii=False, indent=2) + ";\n"
    OUT_FILE.write_text(header + body, encoding="utf-8")
    print(f"Собрано {len(bundle)} локал(и) -> {OUT_FILE.relative_to(BACKEND_DIR.parent)}")


if __name__ == "__main__":
    build()
