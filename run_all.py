import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def resolve_script(name: str) -> str:
    candidates = [
        BASE_DIR / name,
        SRC_DIR / name,
    ]
    if name.endswith(".py"):
        alt_name = name[:-3] + "_2.py"
        candidates.extend([BASE_DIR / alt_name, SRC_DIR / alt_name])
    elif name.endswith("_2.py"):
        alt_name = name[:-5] + ".py"
        candidates.extend([BASE_DIR / alt_name, SRC_DIR / alt_name])

    for path in candidates:
        if path.exists():
            return str(path)

    return str(SRC_DIR / name)


def run_step(step_name: str, command: list[str]):
    print("\n" + "=" * 70)
    print(f"ШАГ: {step_name}")
    print(f"Команда: {' '.join(command)}")
    print("=" * 70)

    env = os.environ.copy()
    current_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{SRC_DIR}{os.pathsep}{BASE_DIR}{os.pathsep}{current_pp}"

    start_time = time.time()
    result = subprocess.run(command, env=env, cwd=str(BASE_DIR))
    elapsed = time.time() - start_time

    if result.returncode != 0:
        print(f"\n[ОШИБКА] Шаг '{step_name}' завершился с кодом {result.returncode}")
        sys.exit(result.returncode)

    print(f"[УСПЕХ] Шаг завершён за {elapsed:.2f} сек.")


def main():
    py_exec = sys.executable

    print("\n" + "#" * 70)
    print("ПОЛНЫЙ КОНТРОЛЬНЫЙ ПРОГОН ПРОЕКТА ПО ТЕХНИЧЕСКОМУ ЗАДАНИЮ")
    print("#" * 70)

    run_step("1. Модульное и интеграционное тестирование", [
        py_exec, "-m", "pytest", "tests", "-v"
    ])

    absent_target_script = resolve_script("dht_absent_target_experiment.py")
    run_step("2. Эксперимент невырожденности DHT (Раздел 6 ТЗ, 30 поисков)", [
        py_exec, absent_target_script
    ])

    bootstrap_script = resolve_script("run_bootstrap_experiment.py")
    run_step("3. Бенчмарк сходимости Bootstrap (5 серий, N=20)", [
        py_exec, bootstrap_script
    ])

    relay_script = resolve_script("run_relay_experiment.py")
    run_step("4. Бенчмарк выбора ретрансляторов (Random vs Ranked)", [
        py_exec, relay_script
    ])

    underlay_script = resolve_script("run_underlay_experiment.py")
    run_step("5. Эксперимент ограниченного underlay и netem (деградация хопа)", [
        py_exec, underlay_script
    ])

    perf_script = resolve_script("run_performance_experiment.py")
    run_step("6. Комплексный бенчмарк задержек, Goodput, Overhead и Churn (Раздел 15.2 ТЗ)", [
        py_exec, perf_script
    ])

    plot_script = resolve_script("plot_results.py")
    run_step("7. Построение графиков из сырых данных", [
        py_exec, plot_script
    ])

    print("\n" + "#" * 70)
    print("ВСЕ ПРОВЕРКИ И ЭКСПЕРИМЕНТЫ УСПЕШНО ВЫПОЛНЕНЫ!")
    print(f"Все отчёты и графики сохранены в каталоге: {RESULTS_DIR.resolve()}")
    print("  * JSON-отчёты: bootstrap_experiment_results.json, dht_absent_target_strict_results.json,")
    print("                 relay_experiment_results.json, underlay_experiment_report.json,")
    print("                 performance_experiment_results.json, acceptance_report.json")
    print("  * Графики:     convergence_time.png, relay_strategy_latency.png, dht_absent_target_metrics.png")
    print("#" * 70)


if __name__ == "__main__":
    main()