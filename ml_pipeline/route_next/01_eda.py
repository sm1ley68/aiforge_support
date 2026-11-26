import marimo

app = marimo.App(width="medium")


@app.cell
def _():
    import hashlib
    import json
    import os
    from pathlib import Path

    import marimo as mo
    import matplotlib
    import pandas as pd

    from ml_pipeline import guard
    from ml_pipeline.prep_data import collect_candidates

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    return Path, collect_candidates, guard, hashlib, json, mo, os, pd, plt


@app.cell
def _(Path, collect_candidates, guard, hashlib, json, os, pd):
    report_dir = Path(__file__).resolve().parent
    build = os.environ.get("SOFTLINE_ROUTE_NEXT_MODE") == "report"
    funnel = manifest = pool = reviewed = None
    if build:
        default_data = Path.home() / "Documents" / "drive-download-20261126T075025Z-1-001"
        source_dir = Path(os.environ.get("SOFTLINE_DATA_DIR", default_data))
        archive = source_dir / "чаты поддержки.zip"
        review = json.loads((report_dir.parent / "reviewed_routes.json").read_text(encoding="utf-8"))
        if hashlib.sha256(archive.read_bytes()).hexdigest() != review["archive_sha256"]:
            raise ValueError("The archive differs from the snapshot used by the previous experiment")

        candidates, funnel = collect_candidates(archive)
        reviewed = {position for positions in review["routes"].values() for position in positions}
        if not reviewed.issubset({item.archive_position for item in candidates}):
            raise ValueError("Previously reviewed positions are absent from the candidate pool")

        # Expose only topic, review status, and length. Archive topics are not route labels.
        manifest = pd.DataFrame({
            "archive_topic": [item.topic for item in candidates],
            "review_status": ["Проверено ранее" if item.archive_position in reviewed else "Новые кандидаты"
                              for item in candidates],
            "prefix_chars": [len(item.text) for item in candidates],
        })
        pool = manifest.loc[manifest["review_status"] == "Новые кандидаты"]
        guard.profile(pool, target="archive_topic", state_dir=report_dir)
    return build, funnel, manifest, pool, report_dir, reviewed


@app.cell
def _(build, funnel, guard, manifest, plt, pool, report_dir, reviewed):
    if build:
        totals = [funnel["archive_records"], len(manifest), len(pool)]
        fig, ax = plt.subplots(figsize=(9, 3.2), layout="constrained")
        bars = ax.barh(["Записи в архиве", "Кандидаты с коротким вопросом", "Ещё не размечены"],
                       totals, color=["#4059b3", "#4059b3", "#217d75"])
        ax.invert_yaxis()
        ax.bar_label(bars, padding=5)
        ax.set_xlim(0, max(totals) * 1.1)
        ax.set_xlabel("Обращения")
        guard.fig(1, "candidate_pool", fig,
                  f"Из {totals[0]} записей {totals[1]} прошли исходный фильтр. После исключения "
                  f"{len(reviewed)} ранее размеченных позиций осталось {totals[2]} кандидата для проверки.",
                  state_dir=report_dir)

        topics = (manifest.groupby(["archive_topic", "review_status"]).size().unstack(fill_value=0)
                  .reindex(columns=["Проверено ранее", "Новые кандидаты"]).sort_values("Новые кандидаты"))
        fig, ax = plt.subplots(figsize=(11, 5), layout="constrained")
        topics.plot.barh(stacked=True, color=["#4059b3", "#217d75"], ax=ax)
        ax.set_xlabel("Обращения")
        ax.set_ylabel("")
        ax.legend(loc="lower right")
        guard.fig(2, "topics_left_to_review", fig,
                  "Кандидаты распределены по архивным темам. Разметку подбора и передачи менеджеру "
                  "стоит начать со спецификаций и особых условий, затем проверить по тексту сообщения.",
                  state_dir=report_dir)

        fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
        ax.hist(pool["prefix_chars"], bins=14, color="#217d75")
        ax.set_xlabel("Символов в отобранном вопросе")
        ax.set_ylabel("Кандидаты")
        guard.fig(2, "candidate_lengths", fig,
                  "Длины относятся к префиксам, прошедшим старый фильтр. Нужна ручная проверка границ "
                  "реплик, особенно когда вопрос зависит от предыдущего хода.", state_dir=report_dir)
        plt.close("all")
    return


@app.cell
def _(mo, report_dir):
    mo.vstack([
        mo.md("## Softline · резерв для новой оценки маршрутизации"),
        mo.image(src=report_dir / "figures" / "01_candidate_pool.png"),
        mo.image(src=report_dir / "figures" / "02_topics_left_to_review.png"),
        mo.image(src=report_dir / "figures" / "02_candidate_lengths.png"),
    ])
    return


if __name__ == "__main__":
    app.run()
