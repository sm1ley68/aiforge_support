import marimo

app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    from pathlib import Path

    import marimo as mo
    import matplotlib
    import pandas as pd

    from ml_pipeline import guard
    from ml_pipeline.prep_data import make_text_features
    from ml_pipeline.route_next.prepare import prepare_next_split

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    return Path, guard, json, make_text_features, mo, os, pd, plt, prepare_next_split


@app.cell
def _(Path, json, os, prepare_next_split):
    report_dir = Path(__file__).resolve().parent
    default_source = Path.home() / "Documents" / "drive-download-20261126T075025Z-1-001"
    source = Path(os.getenv("SOFTLINE_DATA_DIR", default_source)) / "чаты поддержки.zip"
    mode = os.getenv("SOFTLINE_ROUTE_NEXT_MODE", "view")
    if mode not in {"prepare", "figures", "view"}:
        raise ValueError("SOFTLINE_ROUTE_NEXT_MODE must be prepare, figures, or view")
    if mode == "prepare":
        report = prepare_next_split(source, report_dir.parent)
    else:
        saved = report_dir.parent / ".local" / "route-split-v2" / "prep_report.json"
        if not saved.is_file():
            saved = report_dir / "reports" / saved.name
        report = json.loads(saved.read_text(encoding="utf-8"))
    return mode, report, report_dir


@app.cell
def _(guard, mode, pd, plt, report, report_dir):
    routes = ["Товар назван", "Подбор по задаче", "Вопрос о товаре", "Передача", "Уточнение"]
    parts = ["Обучение", "Валидация", "Финальная проверка"]
    counts = pd.DataFrame({label: list(part["by_route"].values())
                           for label, part in zip(parts, report["counts"].values(), strict=True)}, index=routes)
    if mode in {"prepare", "figures"}:
        totals = [report["reviewed_initial"], sum(report["excluded_initial"].values()),
                  report["reviewed_supplemental_accepted"], sum(report["duplicates_by_route"].values()),
                  sum(report["new_by_route"].values())]
        labels = ["Проверено в исходном отборе", "Исключено вручную", "Восстановлено из архива",
                  "Удалено дублей", "Пригодных новых реплик"]
        fig, ax = plt.subplots(figsize=(9, 3.8), layout="constrained")
        bars = ax.barh(labels, totals, color="#4059b3")
        ax.invert_yaxis()
        ax.bar_label(bars, padding=4)
        ax.set_xlim(0, max(totals) * 1.15)
        guard.fig(4, "manual_review", fig, "Ручная проверка оставила пригодные клиентские реплики. "
                  "Дополнительные реплики восстановлены из архива и все тексты проверены на близкие дубли.", report_dir)

        fig, ax = plt.subplots(figsize=(9, 4.5), layout="constrained")
        counts.plot.barh(ax=ax, color=["#4059b3", "#dfa950", "#217d75"])
        ax.invert_yaxis()
        ax.set_xlabel("Реплики")
        ax.legend(loc="lower right")
        guard.fig(6, "split_by_route", fig, "Обе контрольные части состоят из новых реальных реплик. "
                  "Классы представлены неравномерно, поэтому итог нужно дополнять числами по каждому маршруту.", report_dir)

        fig, ax = plt.subplots(figsize=(8, 3.2), layout="constrained")
        lengths = report["training_length_bins"]
        ax.bar(lengths.keys(), lengths.values(), color="#217d75")
        ax.set_xlabel("Символов в первой реплике")
        ax.set_ylabel("Реплики обучения")
        guard.fig(7, "training_lengths", fig, "Длины подсчитаны только для будущего обучения. "
                  "Признаки используют слова и их части; словарь будет строиться только на обучающей выборке.", report_dir)
        plt.close("all")
    return (counts,)


@app.cell
def _(counts, make_text_features, mo):
    transformer = make_text_features()
    names = ", ".join(name for name, _ in transformer.transformer_list)
    mo.vstack([
        mo.md("# Softline · подготовка нового сравнения"),
        counts,
        mo.md(f"Подготовленные признаки — {names}. На этом этапе модель не обучалась."),
    ])
    return


if __name__ == "__main__":
    app.run()
