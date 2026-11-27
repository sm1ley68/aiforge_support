import marimo

__generated_with = "0.26.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    from pathlib import Path

    import marimo as mo
    from matplotlib import pyplot as plt

    work = Path(os.environ.get("SOFTLINE_AGENT_EVAL_REPORTS", Path(__file__).with_name("reports")))
    profile_report = Path(os.environ.get(
        "SOFTLINE_PROFILE_REPORT",
        Path(__file__).resolve().parents[1] / ".local/profile-comparison/closed-v1-report.json",
    ))
    return json, mo, plt, profile_report, work


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


@app.cell
def _(json, mo, profile_report):
    if not profile_report.is_file():
        comparison = mo.md("Сравнение моделей доступно в отчёте проекта.")
    else:
        profiles = json.loads(profile_report.read_text())["profiles"]
        comparison = mo.ui.table([
            {"Профиль": name, "Диалоги": f"{profile['passed_cases']}/{profile['case_count']}",
             "p95 хода, с": profile["p95_ms"] / 1000,
             "Успешные вызовы": f"{profile['extraction']['succeeded']}/{profile['extraction']['calls']}",
             "p95 вызова, с": profile["extraction"]["p95_ms"] / 1000 if profile["extraction"]["p95_ms"] else None}
            for name, profile in profiles.items()
        ])
    comparison
    return


if __name__ == "__main__":
    app.run()
