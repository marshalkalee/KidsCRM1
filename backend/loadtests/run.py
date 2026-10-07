"""Один воспроизводимый запуск наполнения, Locust и отчёта TRU-155."""

import argparse
import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402

from loadtests.report import write_report  # noqa: E402


def _cost():
    with connection.cursor() as cursor:
        cursor.execute("SHOW random_page_cost")
        return float(cursor.fetchone()[0])


def _set_cost(value):
    value = float(value)
    if not 0.1 <= value <= 10:
        raise ValueError("random_page_cost вне безопасного диапазона")
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER SYSTEM SET random_page_cost = {value:g}")
        cursor.execute("SELECT pg_reload_conf()")
    connection.close()


@contextlib.contextmanager
def _production_server(args):
    """Run the benchmark against Gunicorn, never Django's development server."""

    if args.host:
        yield args.host
        return

    host = "http://127.0.0.1:8001"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "gunicorn",
            "config.wsgi:application",
            "--bind",
            "0.0.0.0:8001",
            "--workers",
            str(args.workers),
            "--threads",
            "2",
            "--timeout",
            "120",
        ],
        cwd=ROOT,
    )
    try:
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError("Gunicorn завершился до начала нагрузочного теста")
            try:
                with socket.create_connection(("127.0.0.1", 8001), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("Gunicorn не запустился за 12 секунд")
        yield host
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def _locust(prefix, args, host):
    Path(prefix).parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(ROOT / "loadtests" / "locustfile.py"),
        "--headless",
        "--only-summary",
        "--reset-stats",
        "--users",
        str(args.users),
        "--spawn-rate",
        str(args.spawn_rate),
        "--run-time",
        args.duration,
        "--stop-timeout",
        "10",
        "--host",
        host,
        "--csv",
        str(prefix),
        "--html",
        f"{prefix}.html",
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true", help="Пересоздать целевой набор данных")
    parser.add_argument("--organizations", type=int, default=500)
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--spawn-rate", type=float, default=20)
    parser.add_argument("--duration", default="2m")
    parser.add_argument(
        "--host",
        default="",
        help="Внешний host; без параметра runner сам запускает Gunicorn",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--results-dir", default="loadtests/results")
    parser.add_argument("--report", default="/docs/load-testing-results.md")
    parser.add_argument("--compare-random-page-cost", action="store_true")
    args = parser.parse_args()

    if args.seed:
        call_command(
            "seed_analytics",
            reset=True,
            system_organizations=args.organizations,
        )

    results = Path(args.results_dir)
    prefixes = []
    labels = []
    failed_runs = []
    original_cost = _cost()
    try:
        with _production_server(args) as host:
            default_prefix = results / "target_default"
            if _locust(default_prefix, args, host):
                failed_runs.append(str(default_prefix))
            prefixes.append(str(default_prefix))
            labels.append(f"random_page_cost={original_cost:g}")
            if args.compare_random_page_cost and original_cost != 1.1:
                _set_cost(1.1)
                tuned_prefix = results / "target_rpc_1_1"
                if _locust(tuned_prefix, args, host):
                    failed_runs.append(str(tuned_prefix))
                prefixes.append(str(tuned_prefix))
                labels.append("random_page_cost=1.1 (глобально)")
    finally:
        if _cost() != original_cost:
            _set_cost(original_cost)

    path = write_report(
        prefixes,
        args.report,
        users=args.users,
        duration=args.duration,
        labels=labels,
    )
    print(f"Отчёт: {path}")
    if failed_runs:
        raise SystemExit(
            "Locust обнаружил ошибки; отчёт всё равно сохранён. Прогоны: " + ", ".join(failed_runs)
        )


if __name__ == "__main__":
    main()
