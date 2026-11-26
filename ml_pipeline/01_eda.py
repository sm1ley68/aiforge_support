import marimo

__generated_with = "0.26.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import re
    from collections import Counter
    from pathlib import Path
    from zipfile import ZipFile

    import marimo as mo
    import matplotlib
    import pandas as pd
    from lxml import etree

    from ml_pipeline import guard

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    return Counter, Path, ZipFile, etree, guard, json, mo, os, pd, plt, re


@app.cell
def _(Path, os):
    analysis_dir = Path(__file__).resolve().parent
    default_dir = Path.home() / "Documents" / "drive-download-20261126T075025Z-1-001"
    source_dir = Path(os.environ.get("SOFTLINE_DATA_DIR", default_dir))
    mode = os.environ.get("SOFTLINE_EDA_MODE", "view")
    if mode not in {"profile", "figures", "view"}:
        raise ValueError("SOFTLINE_EDA_MODE must be profile, figures, or view")
    return analysis_dir, mode, source_dir


@app.cell
def _(Path, ZipFile, pd, re, source_dir):
    record_pattern = re.compile(r"^#(?P<id>\d+)\s*\[(?P<topic>[^\]]+)\]\s*(?P<body>.*)$")
    role_pattern = re.compile(r"(?:клиент|оператор|покупатель|агент|customer|agent)\s*:", re.I)
    chat_rows = []
    normalized_texts = set()
    duplicate_bodies = 0
    expected_txt_files = {f"buy_part_{index}_masked.txt" for index in (1, 2, 3)}
    with ZipFile(source_dir / "чаты поддержки.zip") as archive:
        members = {Path(item.filename).name: item for item in archive.infolist() if not item.is_dir()}
        if set(members) != expected_txt_files:
            raise ValueError("Support archive structure differs from the known three files")
        for filename in sorted(members):
            blob = archive.read(members[filename])
            extracted = source_dir / "чаты поддержки" / filename
            if extracted.is_file() and extracted.read_bytes() != blob:
                raise ValueError(f"Archive and extracted bytes differ in {filename}")
            for line_number, line in enumerate(blob.decode("utf-8-sig").splitlines(), 1):
                if not line.strip():
                    continue
                match = record_pattern.fullmatch(line.strip())
                if match is None:
                    raise ValueError(f"Unrecognized support record at {filename}:{line_number}")
                body = match["body"].strip()
                words = body.split()
                normalized = " ".join(words).casefold()
                duplicate_bodies += normalized in normalized_texts
                normalized_texts.add(normalized)
                chat_rows.append({
                    "record_id": match["id"],
                    "source_file": filename,
                    "archive_topic": match["topic"].strip(),
                    "body_chars": len(body) if body else None,
                    "body_words": len(words) if body else None,
                })
    manifest = pd.DataFrame(chat_rows)
    archive_info = {
        "exact_duplicates": int(manifest.duplicated().sum()),
        "normalized_body_duplicates": duplicate_bodies,
        "duplicate_ids": int(manifest["record_id"].duplicated().sum()),
        "role_marked_rows": sum(bool(role_pattern.search(item)) for item in normalized_texts),
        "by_file": manifest["source_file"].value_counts(sort=False).to_dict(),
        "by_topic": manifest["archive_topic"].value_counts().to_dict(),
    }
    return archive_info, manifest


@app.cell
def _(analysis_dir, archive_info, guard, json, manifest, mode):
    profile_path = analysis_dir / "data_profile.json"
    if mode == "profile":
        profile = guard.profile(manifest, target="archive_topic", state_dir=analysis_dir)
        profile["archive_checks"] = archive_info
        profile["manual_leakage_risks"] = [
            "Raw headers include the archive topic; exclude the entire metadata header from model input.",
            "Record ID and source file are provenance only; keep them out of model features.",
            "The unsegmented record can contain later replies and outcomes; use verified customer prefixes only.",
        ]
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    return (profile,)


@app.cell
def _(Counter, etree, source_dir):
    source_fields = {
        "Лицензия": "Тип лицензии",
        "Срок": "Срок действия",
        "Лимит пользователей": "К-во пользователей до",
        "Версия": "Версия",
        "Архитектура / платформа": "Совместимая архитектура/платформа",
        "Операционная система": "Операционная система",
    }
    unknown = {"", "другое или отсутствует", "не определено"}
    available = Counter()
    field_present = Counter()
    categories = 0
    offer_count = 0
    for _, element in etree.iterparse(
        str(source_dir / "Mindbox.yml.gz.xml"),
        events=("end",),
        tag=("category", "offer"),
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
    ):
        if element.tag == "offer":
            offer_count += 1
            available[element.get("available", "unknown")] += 1
            params = {item.get("name"): (item.text or "").strip().casefold() for item in element.iterchildren("param")}
            for label, attribute in source_fields.items():
                field_present[label] += params.get(attribute, "") not in unknown
        else:
            categories += 1
        element.clear()
        while element.getprevious() is not None:
            del element.getparent()[0]
    feed_info = {
        "offers": offer_count,
        "availability": dict(available),
        "category_nodes": categories,
        "nonmissing_catalog_fields": dict(field_present),
    }
    return (feed_info,)


@app.cell
def _(analysis_dir, archive_info, feed_info, guard, json, manifest, mode, plt):
    if mode == "figures":
        diagnostic = manifest[["archive_topic", "body_chars", "body_words"]].copy()
        short_names = {topic: str(index) for index, topic in enumerate(archive_info["by_topic"], 1)}
        diagnostic["archive_topic"] = diagnostic["archive_topic"].map(short_names)
        guard.eda_figures(diagnostic, target="archive_topic", state_dir=analysis_dir)

        counts = manifest["archive_topic"].value_counts().sort_values()
        fig, ax = plt.subplots(figsize=(9, 4.2), layout="constrained")
        bars = ax.barh(counts.index, counts, color="#4059b3")
        ax.bar_label(bars, padding=4)
        ax.set_xlim(0, counts.max() * 1.14)
        ax.set_title("Темы в архиве Softline · 495 записей")
        ax.set_xlabel("Записи")
        guard.fig(2, "softline_topics", fig,
                  "Распределение девяти архивных тем. Две крупнейшие покрывают около половины записей, "
                  "а у самой редкой три примера. Темы удобны для стратификации ручной разметки, "
                  "но не совпадают с действиями агента.", analysis_dir)

        fields = feed_info["nonmissing_catalog_fields"]
        coverage = [100 * value / feed_info["offers"] for value in fields.values()]
        fig, ax = plt.subplots(figsize=(7, 3.4), layout="constrained")
        bars = ax.barh(list(fields), coverage, color="#217d75")
        ax.invert_yaxis()
        ax.bar_label(bars, labels=[f"{value:.1f}%" for value in coverage], padding=4)
        ax.set_xlim(0, 100)
        ax.set_xlabel("Доля карточек с заполненным полем")
        ax.set_title("Покрытие параметров каталога")
        guard.fig(2, "softline_catalog_coverage", fig,
                  "Версия и платформа указаны гораздо реже, чем тип лицензии. "
                  "Если поле важно для подбора, пустое значение требует документации или уточнения.", analysis_dir)
        (analysis_dir / "catalog_profile.json").write_text(
            json.dumps(feed_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return


@app.cell
def _(archive_info, feed_info, mo, pd, profile):
    mo.vstack([
        mo.md("# Softline · первичная проверка данных"),
        mo.md(f"**{profile['shape']['n_rows']} записей** в архиве и **{feed_info['offers']:,} предложений** в каталоге. "
              "Архивные категории описывают темы, а не решения агента. В этом ноутбуке только агрегаты."),
        pd.DataFrame(archive_info["by_topic"].items(), columns=["Тема архива", "Записей"]),
        pd.DataFrame(feed_info["nonmissing_catalog_fields"].items(), columns=["Поле", "Заполнено"]),
    ])
    return


if __name__ == "__main__":
    app.run()
