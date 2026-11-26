import marimo

app = marimo.App(width="medium")


@app.cell
def _():
    import os
    from pathlib import Path

    import marimo as mo
    import matplotlib
    import pandas as pd

    from ml_pipeline import guard
    from ml_pipeline.route_next.evaluate import FinalComparison, read_json

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    return FinalComparison, Path, guard, mo, os, pd, plt, read_json


@app.cell
def _(FinalComparison, Path, os, read_json):
    report_dir = Path(__file__).resolve().parent
    comparison = FinalComparison(report_dir.parent)
    mode = os.getenv("SOFTLINE_ROUTE_NEXT_MODE", "view")
    if mode == "diagnose":
        diagnostics = comparison.diagnose_validation()
    else:
        diagnostics_path = comparison.diagnostic_path
        if mode in {"view", "figures"} and not diagnostics_path.is_file():
            diagnostics_path = report_dir / "reports" / diagnostics_path.name
        diagnostics = read_json(diagnostics_path)
    if mode == "freeze":
        comparison.freeze()
    if mode == "final":
        report = comparison.final()
    elif mode in {"diagnose", "freeze", "figures", "view"}:
        final_path = comparison.final_path
        if mode in {"view", "figures"} and not final_path.is_file():
            final_path = report_dir / "reports" / final_path.name
        report = read_json(final_path) if final_path.is_file() else None
    else:
        raise ValueError("SOFTLINE_ROUTE_NEXT_MODE must be diagnose, freeze, final, figures, or view")
    return diagnostics, mode, report, report_dir


@app.cell
def _(diagnostics, guard, mode, plt, report, report_dir):
    route_names = ["Выбор товара", "Подбор по задаче", "Факт о товаре", "Передача", "Уточнение"]
    if mode in {"diagnose", "figures"}:
        matrix = diagnostics["validation"]["runs"][-1]["confusion"]
        errors = sorted(((count, f"{route_names[actual]} → {route_names[predicted]}")
                         for actual, row in enumerate(matrix) for predicted, count in enumerate(row)
                         if actual != predicted and count), reverse=True)
        fig, ax = plt.subplots(figsize=(8.5, 4), layout="constrained")
        bars = ax.barh([label for _, label in errors], [count for count, _ in errors], color="#4059b3")
        ax.bar_label(bars, padding=4)
        ax.invert_yaxis()
        ax.set_xlim(0, max(count for count, _ in errors) + 1)
        ax.set_xlabel("Ошибочные маршруты")
        guard.fig(13, "validation_errors", fig, "Чаще всего модель выбирала уточнение вместо вопроса о товаре. "
                  "График показывает пары ожидаемого и выбранного маршрута на валидации.", report_dir)

    if report is not None and mode in {"final", "figures"}:
        labels = ["Частый класс", "Прежние правила", "Прежний TF-IDF", "Прежняя проверка каталога", "Выбранная модель"]
        scores = [run["macro_f1_supported"] for run in report["runs"]]
        fig, ax = plt.subplots(figsize=(8.5, 3.8), layout="constrained")
        bars = ax.barh(labels, scores, color=["#4059b3"] * 4 + ["#217d75"])
        ax.bar_label(bars, fmt="%.3f", padding=4)
        ax.invert_yaxis()
        ax.set_xlim(0, 1)
        ax.set_xlabel(f"Macro-F1 · {report['n']} отложенных обращений")
        guard.fig(14, "held_out_comparison", fig, "Варианты оценены на одном замороженном архивном наборе. "
                  "Подбор по задаче и передача представлены одним обращением каждый.", report_dir)
    return


@app.cell
def _(diagnostics, mo, pd, report, report_dir):
    current = report if report is not None else diagnostics["validation"]
    summary = pd.DataFrame(current["runs"])[["name", "correct", "macro_f1_supported", "handoff_false_positives"]]
    title = "Итоговая проверка" if report is not None else "Диагностика валидации"
    chart = "14_held_out_comparison.png" if report is not None else "13_validation_errors.png"
    mo.vstack([mo.md(f"# Softline · {title}\n\nПроверено {current['n']} обращений."), summary,
               mo.image(src=report_dir / "figures" / chart)])
    return


if __name__ == "__main__":
    app.run()
