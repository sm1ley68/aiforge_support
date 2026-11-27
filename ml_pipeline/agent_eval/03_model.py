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
    modes = ("offline", "live")
    reports = [json.loads((work / f"validation-{mode}.json").read_text()) for mode in modes]
    names = ["Локально", "Haiku + фильтр"]
    figure, axes = plt.subplots(1, 2, figsize=(9, 3.5), layout="constrained")

    axes[0].bar(names, [report["passed_cases"] for report in reports], color=("#377377", "#6b598c"))
    axes[0].set_title("Диалоги без ошибок проверки")
    axes[0].set_ylim(0, max(report["case_count"] for report in reports) + 1)
    for bar, report in zip(axes[0].patches, reports, strict=True):
        axes[0].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                     f"{report['passed_cases']} / {report['case_count']}", ha="center")

    axes[1].bar(names, [report["p95_ms"] / 1000 for report in reports], color=("#377377", "#6b598c"))
    axes[1].set_title("p95 на 14 ходах")
    axes[1].set_ylabel("Секунды")
    if work.joinpath(".save-figures").exists():
        figure.savefig(work / "12_agent_validation.png", dpi=150)
    mo.vstack([figure, mo.md("Одинаковые сценарии сравнивают два режима стенда. Малый набор показывает "
                             "регрессии поведения и задержки отдельных ходов.")])
    return


if __name__ == "__main__":
    app.run()
