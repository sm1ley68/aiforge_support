import marimo

app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    from pathlib import Path

    import marimo as mo
    from matplotlib import pyplot as plt

    work = Path(os.environ.get("SOFTLINE_AGENT_EVAL_REPORTS", Path(__file__).with_name("reports")))
    return json, mo, plt, work


@app.cell
def _(json, mo, plt, work):
    archive = json.loads((work / "archive-first-turns.json").read_text())
    named = {
        "find_named_product": "Названный товар",
        "answer_product_question": "Вопрос о товаре",
        "clarify": "Уточнение",
        "recommend_by_need": "Подбор по задаче",
        "handoff": "Передача менеджеру",
    }
    counts = archive["outcomes_by_reference_route"]
    figure, axis = plt.subplots(figsize=(8, 3.7), layout="constrained")
    axis.barh(list(named.values()), [counts[key]["handoff"] for key in named], color="#7e5f60")
    axis.invert_yaxis()
    axis.set(xlabel="Реплики, переданные менеджеру", title="Локальная диагностика 43 архивных реплик")
    if work.joinpath(".save-figures").exists():
        figure.savefig(work / "13_archive_handoffs.png", dpi=150)
    mo.vstack([figure, mo.md("Это бывшая валидация маршрутизатора. Разметка описывает намерение "
                             "клиента, а график показывает результат рабочего агентa без Polza.")])
    return


@app.cell
def _(json, mo, work):
    report = work / "held-out-live.json"
    if report.is_file():
        data = json.loads(report.read_text())
        outcome = mo.md(
            f"**Финальная приёмка**\n\n"
            f"Прошло {data['passed_cases']} из {data['case_count']} сценариев. "
            f"Ходы с расхождениями — {data['failed_turns']} из {data['turn_count']}."
        )
    else:
        outcome = mo.md("Финальный отчёт появится после однократной приёмки.")
    outcome
    return


if __name__ == "__main__":
    app.run()
