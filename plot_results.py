import json
from pathlib import Path
import matplotlib.pyplot as plt

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def plot_bootstrap():
    file_path = RESULTS_DIR / "bootstrap_experiment_results.json"
    if not file_path.exists():
        print(f"[-] {file_path.name} не найден в results/")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    summary_list = data.get("summary", [])
    if not summary_list:
        print("[-] Нет данных в summary bootstrap_experiment_results.json")
        return

    schemes = []
    times = []
    rpcs = []

    for item in summary_list:
        schemes.append(item["scheme"].upper())
        times.append(item["average_convergence_time"])
        rpcs.append(item["average_rpc"])

    fig, ax1 = plt.subplots(figsize=(9, 5))
    color = "tab:blue"
    ax1.set_xlabel("Схема Bootstrap", fontweight="bold")
    ax1.set_ylabel("Время сходимости (с)", color=color, fontweight="bold")
    ax1.bar(schemes, times, color=color, alpha=0.6, width=0.4, label="Время (с)")
    ax1.tick_params(axis="y", labelcolor=color)

    ax2 = ax1.twinx()
    color = "tab:red"
    ax2.set_ylabel("Среднее число RPC", color=color, fontweight="bold")
    ax2.plot(schemes, rpcs, color=color, marker="o", linewidth=2.5, label="RPC")
    ax2.tick_params(axis="y", labelcolor=color)

    node_count = data.get("configuration", {}).get("node_count", 20)
    plt.title(f"Сходимость сети N={node_count} узлов по 4 схемам Bootstrap (ТЗ Разделы 6, 15)")
    fig.tight_layout()
    out_png = RESULTS_DIR / "convergence_time.png"
    plt.savefig(out_png, dpi=200)
    plt.close()
    print(f"[+] График 1 успешно построен: {out_png}")


def plot_relay():
    file_path = RESULTS_DIR / "relay_experiment_results.json"
    if not file_path.exists():
        print(f"[-] {file_path.name} не найден в results/")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rand_lat = data.get("random", {}).get("average_latency", 0.0)
    rank_lat = data.get("ranked", {}).get("average_latency", 0.0)

    plt.figure(figsize=(7, 5))
    bars = plt.bar(
        ["Random (случайный)", "Ranked (по рейтингу)"],
        [rand_lat, rank_lat],
        color=["#e74c3c", "#2ecc71"],
        width=0.45
    )
    plt.ylabel("Средняя сквозная задержка (с)", fontweight="bold")
    plt.title("Сравнение стратегий выбора ретрансляторов (1000 итераций, Раздел 12 ТЗ)")
    plt.grid(axis="y", linestyle="--", alpha=0.6)

    for bar in bars:
        yval = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            yval + 0.01,
            f"{yval:.3f} с",
            ha="center",
            va="bottom",
            fontweight="bold"
        )

    plt.tight_layout()
    out_png = RESULTS_DIR / "relay_strategy_latency.png"
    plt.savefig(out_png, dpi=200)
    plt.close()
    print(f"[+] График 2 успешно построен: {out_png}")


def plot_absent_target():
    file_path = RESULTS_DIR / "dht_absent_target_strict_results.json"
    if not file_path.exists():
        print(f"[-] {file_path.name} не найден в results/")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    summary = data.get("summary", {})
    if not summary:
        print("[-] Нет данных в summary dht_absent_target_strict_results.json")
        return

    schemes = []
    avg_rounds = []
    avg_rpcs = []

    for scheme_name, stats in summary.items():
        schemes.append(scheme_name.upper())
        avg_rounds.append(stats.get("average_rounds", 0.0))
        avg_rpcs.append(stats.get("average_rpc", 0.0))

    fig, ax1 = plt.subplots(figsize=(9, 5))
    x = range(len(schemes))
    width = 0.35

    bars1 = ax1.bar([i - width/2 for i in x], avg_rounds, width=width, label="Среднее число раундов", color="#3498db")
    bars2 = ax1.bar([i + width/2 for i in x], avg_rpcs, width=width, label="Среднее число RPC", color="#9b59b6")

    for bar in bars1:
        yval = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2, yval + 0.1, f"{yval:.1f}", ha="center", va="bottom", fontsize=9)

    for bar in bars2:
        yval = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2, yval + 0.1, f"{yval:.1f}", ha="center", va="bottom", fontsize=9)

    ax1.set_xlabel("Схема Bootstrap", fontweight="bold")
    ax1.set_ylabel("Количество", fontweight="bold")
    ax1.set_title("Поиск отсутствующей цели (30 контрольных поисков, Раздел 6 ТЗ)")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(schemes)
    ax1.legend()
    ax1.grid(axis="y", linestyle="--", alpha=0.6)

    plt.tight_layout()
    out_png = RESULTS_DIR / "dht_absent_target_metrics.png"
    plt.savefig(out_png, dpi=200)
    plt.close()
    print(f"[+] График 3 успешно построен: {out_png}")


if __name__ == "__main__":
    plot_bootstrap()
    plot_relay()
    plot_absent_target()