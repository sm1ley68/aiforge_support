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
    import pandas as pd

    from ml_pipeline import guard
    from ml_pipeline.prep_data import (
        ROUTES, checked_archive_rows, collect_candidates, make_text_features,
        normalize_route_text, synthetic_train_rows,
    )

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    return (
        Path, ROUTES, checked_archive_rows, collect_candidates, guard, json, make_text_features,
        mo, normalize_route_text, os, pd, plt, re, synthetic_train_rows, tempfile,
    )


@app.cell
def _(Path, os):
    analysis_dir = Path(__file__).resolve().parent
    default_dir = Path.home() / "Documents" / "drive-download-20261126T075025Z-1-001"
    source_dir = Path(os.environ.get("SOFTLINE_DATA_DIR", default_dir))
    split_dir = analysis_dir / ".local" / "route-split-v1"
    mode = os.environ.get("SOFTLINE_PREP_MODE", "view")
    if mode not in {"view", "prepare"}:
        raise ValueError("SOFTLINE_PREP_MODE must be prepare or view")
    return analysis_dir, mode, source_dir, split_dir


@app.cell
def _(
    ROUTES, analysis_dir, checked_archive_rows, collect_candidates, guard, json,
    mode, normalize_route_text, pd, re, source_dir, split_dir, synthetic_train_rows, tempfile,
):
    seed = 26112026
    if mode == "prepare":
        pipeline_text = (analysis_dir / "PIPELINE.md").read_text(encoding="utf-8")
        if not re.search(r"^- Gate A: approved \d{4}-\d{2}-\d{2}$", pipeline_text, re.M):
            raise RuntimeError("Approve the prediction contract before preparing the data")
        if split_dir.exists():
            raise RuntimeError("The split is frozen. Use view mode to read aggregate results.")

        archive_path = source_dir / "чаты поддержки.zip"
        candidates, cleaning = collect_candidates(archive_path)
        real_rows, near_duplicates = checked_archive_rows(
            archive_path, analysis_dir / "reviewed_routes.json", candidates,
        )
        real_frame = pd.DataFrame(real_rows)
        synthetic = pd.DataFrame(synthetic_train_rows(analysis_dir / "synthetic_route_train.json"))
        if not real_frame["group_id"].is_unique or set(real_frame["route"]) != set(ROUTES):
            raise ValueError("Require one reviewed row per source record and all five routes")
        if set(real_frame["text"].map(normalize_route_text)) & set(synthetic["text"].map(normalize_route_text)):
            raise ValueError("A synthetic example duplicates archive text")

        split_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="prepare-", dir=split_dir.parent) as temporary:
            stage = Path(temporary) / "split"
            # One row per source record. Near-duplicates are removed before stratification.
            train_archive, validation, held_out = guard.split(real_frame, target="route", seed=seed, state_dir=stage)
            train = pd.concat([train_archive, synthetic], ignore_index=True)
            guard.check_no_overlap(train, validation, held_out)
            groups = [set(frame["group_id"]) for frame in (train, validation, held_out)]
            if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
                raise ValueError("An example group appears in multiple splits")
            partitions = {"train": train, "validation": validation, "held_out": held_out}
            for name, frame in partitions.items():
                frame.to_json(stage / f"{name}.jsonl", orient="records", lines=True, force_ascii=False)

            train_chars = train["text"].map(normalize_route_text).str.len()
            bins = pd.cut(train_chars, bins=[0, 40, 80, 120, 160, 240, float("inf")],
                          labels=["1–40", "41–80", "81–120", "121–160", "161–240", "241+"])
            report = {
                "seed": seed,
                "cleaning": dict(cleaning),
                "reviewed_before_deduplication": len(real_rows) + near_duplicates,
                "near_duplicates_dropped": near_duplicates,
                "reviewed_by_route": real_frame["route"].value_counts().reindex(ROUTES, fill_value=0).to_dict(),
                "counts": {
                    name: {"n": len(frame),
                           "by_origin": frame["origin"].value_counts().to_dict(),
                           "by_route": frame["route"].value_counts().reindex(ROUTES, fill_value=0).to_dict()}
                    for name, frame in partitions.items()
                },
                "training_length_bins": bins.value_counts(sort=False).to_dict(),
            }
            (stage / "prep_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            stage.rename(split_dir)
    else:
        report = json.loads((split_dir / "prep_report.json").read_text(encoding="utf-8"))
    return (report,)


@app.cell
def _(analysis_dir, guard, mode, plt, report):
    if mode == "prepare":
        counts = report["cleaning"]
        archived = sum(report["reviewed_by_route"].values())
        names = ["Архив", "Кандидаты на первую реплику", "Проверено и размечено"]
        fig, ax = plt.subplots(figsize=(8, 3.2), layout="constrained")
        bars = ax.barh(names, [counts["archive_records"], counts["candidates"], archived], color="#4059b3")
        ax.invert_yaxis()
        ax.bar_label(bars, padding=5)
        ax.set_xlim(0, counts["archive_records"] * 1.14)
        ax.set_title("От архивной записи до размеченной реплики")
        guard.fig(4, "route_filtering", fig,
                  "Фильтр убирает записи с неясным окончанием вопроса и с признаками контактных данных. "
                  "Ручной отбор проверяет смысл первых реплик; остальные записи остаются в архиве.", analysis_dir)

        labels = ["Товар назван", "Подбор по задаче", "Факт о товаре", "Передача", "Уточнение"]
        fig, ax = plt.subplots(figsize=(7.6, 3.6), layout="constrained")
        bars = ax.barh(labels, list(report["reviewed_by_route"].values()), color="#217d75")
        ax.invert_yaxis()
        ax.bar_label(bars, padding=5)
        ax.set_xlim(0, max(report["reviewed_by_route"].values()) * 1.15)
        ax.set_title("Маршруты в проверенных архивных фрагментах")
        guard.fig(5, "reviewed_routes", fig,
                  "На вопрос о товаре примеров больше, чем на подбор и передачу менеджеру. "
                  "Редкие ветки нельзя оценивать по общей точности.", analysis_dir)

        names = ["Обучение", "Валидация", "Финальная проверка"]
        archived_parts = [p["by_origin"].get("archive_prefix", 0) for p in report["counts"].values()]
        synthetic_parts = [p["by_origin"].get("synthetic", 0) for p in report["counts"].values()]
        fig, ax = plt.subplots(figsize=(7.6, 3.5), layout="constrained")
        ax.barh(names, archived_parts, color="#4059b3", label="Фрагменты архива")
        ax.barh(names, synthetic_parts, left=archived_parts, color="#dfa950", label="Синтетика")
        ax.invert_yaxis()
        ax.legend(loc="lower right")
        ax.set_xlabel("Реплики")
        ax.set_title("Синтетика попадает только в обучение")
        guard.fig(6, "split_provenance", fig,
                  "Валидация и финальная проверка состоят только из архивных фрагментов. "
                  "Синтетические примеры используются исключительно для обучения.", analysis_dir)

        lengths = report["training_length_bins"]
        fig, ax = plt.subplots(figsize=(7.3, 3.1), layout="constrained")
        ax.bar(lengths.keys(), lengths.values(), color="#4059b3")
        ax.set_xlabel("Символы после нормализации")
        ax.set_ylabel("Реплики")
        ax.set_title("Длина текста в обучающей части")
        guard.fig(7, "training_message_lengths", fig,
                  "Длины посчитаны только в обучающей части. Используем слова и фрагменты слов, "
                  "чтобы сохранять смысл коротких вопросов, артикулов и опечаток.", analysis_dir)
    return


@app.cell
def _(make_text_features, mo, pd, report):
    preprocessor = make_text_features()
    mo.vstack([
        mo.md("# Softline · подготовка маршрутизатора"),
        pd.DataFrame(report["reviewed_by_route"].items(), columns=["Маршрут", "Архивных фрагментов"]),
        pd.DataFrame({name: part["by_route"] for name, part in report["counts"].items()}),
        mo.md(f"Предобработка: {', '.join(name for name, _ in preprocessor.transformer_list)}. "
              "Словари будут построены только при обучении. На этом шаге модель не обучается."),
    ])
    return


if __name__ == "__main__":
    app.run()
