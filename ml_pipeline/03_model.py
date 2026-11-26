import marimo

__generated_with = "0.26.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import re
    import tempfile
    from pathlib import Path

    import marimo as mo
    import matplotlib
    import numpy as np
    import pandas as pd

    from ml_pipeline import guard
    from ml_pipeline.model_experiment import run_route_experiment
    from ml_pipeline.prep_data import ROUTES

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    return Path, ROUTES, guard, json, mo, np, os, pd, plt, re, run_route_experiment, tempfile


@app.cell
def _(Path, os):
    analysis_dir = Path(__file__).resolve().parent
    split_dir = analysis_dir / ".local" / "route-split-v1"
    experiment_dir = split_dir.parent / "route-model-v1"
    mode = os.environ.get("SOFTLINE_MODEL_MODE", "view")
    if mode not in {"view", "train", "figures"}:
        raise ValueError("SOFTLINE_MODEL_MODE must be view, train, or figures")
    return analysis_dir, experiment_dir, mode, split_dir


@app.cell
def _(Path, analysis_dir, experiment_dir, json, mode, re, run_route_experiment, split_dir, tempfile):
    if mode == "train":
        ledger = (analysis_dir / "PIPELINE.md").read_text(encoding="utf-8")
        if not re.search(r"^- Gate B: approved \d{4}-\d{2}-\d{2}$", ledger, re.M):
            raise RuntimeError("Approve training before fitting the router")
        if experiment_dir.exists():
            raise FileExistsError(f"{experiment_dir.name} already exists. Use view or figures mode.")
        with tempfile.TemporaryDirectory(prefix="fit-", dir=split_dir.parent) as temporary:
            stage = Path(temporary) / "run"
            stage.mkdir(mode=0o700)
            report = run_route_experiment(split_dir, stage / "router.joblib")
            (stage / "validation_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )
            stage.rename(experiment_dir)
    else:
        report = json.loads((experiment_dir / "validation_report.json").read_text(encoding="utf-8"))
    return (report,)


@app.cell
def _(ROUTES, report):
    labels = dict(zip(ROUTES, ("Товар назван", "Подбор", "Факт о товаре", "Менеджер", "Уточнение"), strict=True))
    runs = {run["name"]: run for run in report["runs"]}
    chosen = runs[report["selected_learned_candidate"]]
    return chosen, labels, runs


@app.cell
def _(analysis_dir, guard, mode, plt, report, runs):
    if mode in {"train", "figures"}:
        def score_bars(names, labels, title, colors):
            figure, axes = plt.subplots(figsize=(7.7, 3.4), layout="constrained")
            scores = [runs[name]["macro_f1_supported"] for name in names]
            bars = axes.barh(labels, scores, color=colors)
            axes.invert_yaxis()
            axes.set_xlim(0, 1.09)
            axes.set_xlabel("Macro-F1 по классам в валидации")
            axes.bar_label(bars, fmt="%.2f", padding=5)
            axes.set_title(title)
            return figure

        figure = score_bars(("majority", "rules", "words"), ("Частый класс", "Простые правила", "TF-IDF по словам"),
                            "Базовые варианты маршрутизации", ("#7383a0", "#217d75", "#4059b3"))
        guard.fig(9, "router_baselines", figure,
                  "Базовые варианты сравниваются на одних и тех же архивных фрагментах. "
                  "Частый класс показывает, сколько даёт прогноз без чтения текста.", analysis_dir)

        figure = score_bars(("words_char_archive", "words_char_C1"), ("Архив", "Архив + синтетика"),
                            "Одинаковая модель · разные обучающие данные", ("#7383a0", "#4059b3"))
        guard.fig(10, "router_training_sources", figure,
                  "Слова и части слов, коэффициент C одинаков. Меняется только источник обучающих данных. "
                  "Варианты сравниваются на одной архивной валидации.", analysis_dir)

        figure, axes = plt.subplots(figsize=(7.1, 3.3), layout="constrained")
        trials = [runs[name] for name in ("words_char_C0.3", "words_char_C1", "words_char_C3")]
        axes.plot([str(run["config"]["C"]) for run in trials], [run["macro_f1_supported"] for run in trials],
                  marker="o", color="#4059b3")
        axes.axhline(runs["words"]["macro_f1_supported"], linestyle="--", color="#217d75", label="Слова, C = 1")
        axes.set_ylim(0, 1)
        axes.set_xlabel("C · меньшее значение сильнее ограничивает модель")
        axes.set_ylabel("Macro-F1")
        axes.set_title(f"Три настройки · {report['validation_n']} валидационных фрагментов")
        axes.legend(loc="lower right")
        guard.fig(11, "router_regularization", figure,
                  "Сравниваются только три значения C. Разница оценок на десяти примерах "
                  "годится для выбора кандидата для следующей проверки.", analysis_dir)
    return


@app.cell
def _(ROUTES, analysis_dir, chosen, guard, labels, mode, np, plt, report, runs):
    if mode in {"train", "figures"}:
        _figure, _axes = plt.subplots(1, 2, figsize=(11.4, 4.5), layout="constrained")
        matrices = (("Базовые правила", runs["rules"]), ("Выбранная обученная модель", chosen))
        largest = max(max(max(row) for row in run["confusion"]) for _, run in matrices)
        for axis, (title, run) in zip(_axes, matrices, strict=True):
            matrix = np.asarray(run["confusion"])
            axis.imshow(matrix, cmap="Blues", vmin=0, vmax=largest)
            for i, j in np.ndindex(matrix.shape):
                axis.text(j, i, str(matrix[i, j]), ha="center", va="center",
                          color="white" if matrix[i, j] > largest / 2 else "#172b4d")
            axis.set_xticks(range(len(ROUTES)), labels.values(), rotation=32, ha="right")
            axis.set_yticks(range(len(ROUTES)), labels.values())
            axis.set_title(f"{title}\nMacro-F1 {run['macro_f1_supported']:.2f}")
            axis.set_xlabel("Прогноз")
            axis.set_ylabel("Разметка")
        guard.fig(12, "router_confusion", _figure,
                  "Строки показывают фактический маршрут, столбцы — выбранный моделью. "
                  "Пустая строка менеджера означает отсутствие реальных примеров для оценки этой ветки.", analysis_dir)

        _figure, _axes = plt.subplots(1, 2, figsize=(10.8, 4.0), layout="constrained")
        palette = dict(zip(ROUTES, ("#4059b3", "#217d75", "#bf7b37", "#9469ad", "#b04866"), strict=True))
        comparison = (("words", "--"), ("selected", "-")) if chosen["name"] != "words" else (("selected", "-"),)
        for name, linestyle in comparison:
            for route, curve in report["curves"][name].items():
                label = labels[route] if name == "selected" else None
                _axes[0].step(curve["recall"], curve["precision"], where="post", color=palette[route],
                              linestyle=linestyle, label=label, alpha=0.9)
                _axes[1].plot(curve["fpr"], curve["tpr"], color=palette[route], linestyle=linestyle, alpha=0.9)
        _axes[0].set(xlabel="Полнота", ylabel="Точность", title="Precision–recall")
        _axes[1].set(xlabel="Доля ложных срабатываний", ylabel="Доля найденных примеров", title="ROC")
        _axes[1].plot((0, 1), (0, 1), color="#98a2b3", linestyle=":")
        _axes[0].legend(loc="lower left")
        _figure.suptitle("Валидация · выбранная модель" if len(comparison) == 1 else
                         "Валидация · выбранный кандидат сплошной, базовый пунктиром")
        guard.fig(12, "router_threshold_diagnostics", _figure,
                  "Кривые показывают поведение оценок классов. Редкие маршруты представлены единичными "
                  "примерами, поэтому из этих кривых нельзя выводить надёжный порог для боевого чата.", analysis_dir)
    return


@app.cell
def _(chosen, mo, pd, report):
    columns = ["name", "train_count", "macro_f1_supported", "correct"]
    mo.vstack([
        mo.md("# Softline · обучение маршрутизатора"),
        mo.md(f"Учебный кандидат **{chosen['name']}**. Сравниваем на {report['validation_n']} архивных репликах."),
        pd.DataFrame(report["runs"])[columns],
        mo.md("Передача менеджеру отсутствует в валидации. Финальный набор в этом ноутбуке не используется."),
    ])
    return


if __name__ == "__main__":
    app.run()
