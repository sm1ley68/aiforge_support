import marimo

app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    from pathlib import Path

    import marimo as mo
    import matplotlib
    import numpy as np
    import pandas as pd

    from ml_pipeline import guard
    from ml_pipeline.prep_data import ROUTES
    from ml_pipeline.route_next.train import run_validation

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    return Path, ROUTES, guard, json, mo, np, os, pd, plt, run_validation


@app.cell
def _(Path, json, os, run_validation):
    report_dir = Path(__file__).resolve().parent
    mode = os.getenv("SOFTLINE_ROUTE_NEXT_MODE", "view")
    if mode not in {"train", "figures", "view"}:
        raise ValueError("SOFTLINE_ROUTE_NEXT_MODE must be train, figures, or view")
    if mode == "train":
        report = run_validation(report_dir.parent, include_evidence=True)
    else:
        saved = report_dir.parent / ".local" / "route-model-v2-evidence" / "validation_report.json"
        if not saved.is_file():
            saved = report_dir / "reports" / saved.name
        report = json.loads(saved.read_text(encoding="utf-8"))
    best = next(run for run in report["runs"] if run["name"] == report["selected"])
    return best, mode, report, report_dir


@app.cell
def _(ROUTES, best, guard, mode, np, plt, report, report_dir):
    if mode in {"train", "figures"}:
        names = [run["name"] for run in report["runs"]]
        values = [run["macro_f1_supported"] for run in report["runs"]]
        colors = ["#217d75" if name == best["name"] else "#4059b3" for name in names]
        fig, ax = plt.subplots(figsize=(9, 5.3), layout="constrained")
        bars = ax.barh(names, values, color=colors)
        ax.bar_label(bars, fmt="%.3f", padding=4)
        ax.invert_yaxis()
        ax.set_xlim(0, 1)
        ax.set_xlabel("Macro-F1 · 43 валидационные реплики")
        guard.fig(12, "router_comparison", fig, "Все варианты проверены на одной валидации. "
                  "Macro-F1 учитывает каждый маршрут отдельно, даже если его примеров мало.", report_dir)

        route_labels = ["Товар назван", "Подбор по задаче", "Вопрос о товаре", "Менеджер", "Уточнение"]
        matrix = np.asarray(best["confusion"])
        fig, ax = plt.subplots(figsize=(7, 5.5), layout="constrained")
        heatmap = ax.imshow(matrix, cmap="Blues")
        ax.set_xticks(range(len(route_labels)), route_labels, rotation=30, ha="right")
        ax.set_yticks(range(len(route_labels)), route_labels)
        ax.set_xlabel("Маршрут модели")
        ax.set_ylabel("Ожидаемый маршрут")
        for row, col in np.ndindex(matrix.shape):
            ax.text(col, row, matrix[row, col], ha="center", va="center",
                    color="white" if matrix[row, col] > matrix.max() / 2 else "#1f2937")
        fig.colorbar(heatmap, ax=ax, shrink=0.72)
        guard.fig(12, "router_confusion", fig, "Диагональ показывает верные ответы лучшего обученного варианта. "
                  "У подбора и передачи менеджеру всего по одной реплике, поэтому их строки диагностические.", report_dir)

        fig, (pr, roc) = plt.subplots(1, 2, figsize=(10, 4.2), layout="constrained")
        for route, label in zip(ROUTES, route_labels, strict=True):
            curve = report["curves"][route]
            pr.plot(curve["recall"], curve["precision"], label=label)
            roc.plot(curve["fpr"], curve["tpr"], label=label)
        pr.set(xlabel="Полнота", ylabel="Точность", title="Precision–Recall")
        roc.set(xlabel="Доля ложных срабатываний", ylabel="Полнота", title="ROC")
        roc.legend(loc="lower right", fontsize="small")
        guard.fig(12, "router_threshold_curves", fig, "Кривые показывают оценки по каждому маршруту. "
                  "По редким классам нельзя надёжно выбрать рабочий порог из этой валидации.", report_dir)
    return


@app.cell
def _(mo, pd, report, report_dir):
    summary = pd.DataFrame.from_records(report["runs"])[["name", "train_count", "correct", "macro_f1_supported",
                                                        "handoff_false_positives"]]
    mo.vstack([
        mo.md("# Softline · сравнение на валидации"),
        mo.md(f"**{report['validation_n']}** реальных реплик. Лучший обученный вариант — `{report['selected']}`."),
        summary,
        mo.image(src=report_dir / "figures" / "12_router_confusion.png"),
    ])
    return


if __name__ == "__main__":
    app.run()
