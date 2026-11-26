import marimo

__generated_with = "0.26.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import hashlib
    import json
    import os
    import re
    from pathlib import Path

    import joblib
    import marimo as mo
    import matplotlib
    import numpy as np
    import pandas as pd

    from aisupport_ml.commerce import catalog, routing
    from ml_pipeline import guard, model_experiment

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    return Path, catalog, guard, hashlib, joblib, json, mo, model_experiment, np, os, pd, plt, re, routing


@app.cell
def _(Path, os):
    analysis_dir = Path(__file__).resolve().parent
    private = analysis_dir / ".local"
    split_dir = private / "route-split-v1"
    trained_path = private / "route-model-v1" / "router.joblib"
    catalog_path = private / "softline-catalog-2026-11-25.sqlite"
    evaluation_dir = private / "route-fix-v2"
    mode = os.environ.get("SOFTLINE_EVAL_MODE", "view")
    if mode not in {"view", "diagnose", "freeze", "final"}:
        raise ValueError("SOFTLINE_EVAL_MODE must be view, diagnose, freeze, or final")
    return analysis_dir, catalog_path, evaluation_dir, mode, split_dir, trained_path


@app.cell
def _(catalog, catalog_path, joblib, model_experiment, np, routing, trained_path):
    run_names = ("rules_v1", "words_v1", "catalog_guard_v2")

    def predict_all(features):
        model = joblib.load(trained_path)
        name_index = catalog.SoftlineCatalog(catalog_path)
        texts = features["text"]
        probabilities = model.predict_proba(texts)
        maximum_indices = probabilities.argmax(axis=1)
        words = model.classes_[maximum_indices]
        rules = [model_experiment.rule_route(text) for text in texts]
        hybrid = [
            routing.choose_first_route(text, matches_catalog=name_index.has_title_phrase,
                                      suggested_route=str(suggestion), score=float(score))
            for text, suggestion, score in zip(texts, words, probabilities.max(axis=1), strict=True)
        ]
        return np.column_stack((rules, words, hybrid))

    def aggregate(actual, predicted):
        scores = [
            model_experiment._scores(actual, proposed, name=name, train_count=None, config={})
            for name, proposed in zip(run_names, predicted.T, strict=True)
        ]
        actual = np.asarray(actual)
        return {"n": len(actual), "runs": scores,
                "handoff_false_positives": {name: int(((actual != "handoff") & (guess == "handoff")).sum())
                                            for name, guess in zip(run_names, predicted.T, strict=True)}}

    return aggregate, predict_all, run_names


@app.cell
def _(
    Path, aggregate, analysis_dir, catalog, catalog_path, evaluation_dir, guard, hashlib,
    json, mode, model_experiment, pd, predict_all, re, routing, run_names, split_dir, trained_path,
):
    validation_report = evaluation_dir / "diagnostic.json"
    final_report = evaluation_dir / "final.json"
    lock_path = evaluation_dir / "frozen_comparison.json"
    ledger = analysis_dir / "PIPELINE.md"

    def write_json(path, data):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def fingerprint():
        artifacts = (trained_path, catalog_path, Path(routing.__file__), Path(catalog.__file__),
                     Path(model_experiment.__file__), Path(__file__).resolve())
        files = {}
        for item in artifacts:
            with item.open("rb") as stream:
                files[item.name] = hashlib.file_digest(stream, "sha256").hexdigest()
        state = json.loads((split_dir / ".guard_state.json").read_text(encoding="utf-8"))
        return {"files": files, "frozen_split": state["test_fingerprint"],
                "variants": list(run_names), "primary": "catalog_guard_v2", "metric": "macro_f1_supported"}

    if mode == "diagnose":
        if lock_path.exists():
            raise RuntimeError("Comparison is already frozen")
        evaluation_dir.mkdir(mode=0o700, exist_ok=True)
        archive_val = pd.read_json(split_dir / "validation.jsonl", lines=True)
        actual_val = archive_val.pop("route")
        report = aggregate(actual_val, predict_all(archive_val))
        write_json(validation_report, report)
    elif mode == "freeze":
        if not validation_report.is_file() or lock_path.exists():
            raise RuntimeError("Freeze only once after writing validation diagnostics")
        write_json(lock_path, fingerprint())
        report = json.loads(validation_report.read_text(encoding="utf-8"))
    elif mode == "final":
        if not re.search(r"^- Gate C: approved \d{4}-\d{2}-\d{2}$", ledger.read_text(encoding="utf-8"), re.M):
            raise RuntimeError("User approval is required before opening the held-out set")
        if not lock_path.is_file() or json.loads(lock_path.read_text(encoding="utf-8")) != fingerprint():
            raise RuntimeError("The compared code, model, and catalog must match the frozen plan")
        state = json.loads((split_dir / ".guard_state.json").read_text(encoding="utf-8"))
        if state["test_touches"] != 0 or final_report.exists():
            raise RuntimeError("The held-out set has already been evaluated")
        report = {}

        def heldout_macro_f1(actual, predicted):
            report.update(aggregate(actual, predicted))
            return report["runs"][-1]["macro_f1_supported"]

        held_out = pd.read_json(split_dir / "held_out.jsonl", lines=True)
        guard.final_test(predict_all, held_out, target="route", metric_fn=heldout_macro_f1,
                         state_dir=split_dir, pipeline_md=ledger)
        write_json(final_report, report)
    else:
        previous = final_report if final_report.is_file() else validation_report
        report = json.loads(previous.read_text(encoding="utf-8"))
    return (report,)


@app.cell
def _(analysis_dir, guard, mode, plt, report):
    if mode in {"diagnose", "final"}:
        titles = ("Исходные правила", "Модель по словам", "Каталог и правила")
        steps = [run["correct"] for run in report["runs"]]
        fig, ax = plt.subplots(figsize=(7.8, 3.3), layout="constrained")
        bars = ax.barh(titles, steps, color=("#8293ad", "#4059b3", "#217d75"))
        ax.invert_yaxis()
        ax.set_xlim(0, report["n"] * 1.17)
        ax.bar_label(bars, labels=[f"{value} из {report['n']}" for value in steps], padding=5)
        ax.set_xlabel("Верный маршрут")
        ax.set_title("Разбор исправления на валидации" if mode == "diagnose" else "Однократная отложенная проверка")
        if mode == "diagnose":
            guard.fig(13, "route_fix_validation", fig,
                      "Три варианта сравниваются на знакомой валидации. Она помогает проверять исправления, "
                      "но не измеряет эффект на новых данных.", analysis_dir)
        else:
            guard.fig(14, "route_fix_held_out", fig,
                      "Три заранее зафиксированных варианта проверены на одних отложенных репликах за один прогон. "
                      "На отложенной части нет запросов, где правильно передать менеджеру.", analysis_dir)
    return


@app.cell
def _(mo, pd, report):
    mo.vstack([
        mo.md("# Softline · проверка исправления маршрутов"),
        pd.DataFrame(report["runs"])[["name", "correct", "macro_f1_supported"]],
    ])
    return


if __name__ == "__main__":
    app.run()
