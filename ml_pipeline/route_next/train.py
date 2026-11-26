from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from aisupport_ml.commerce.catalog import SoftlineCatalog
from aisupport_ml.commerce.routing import choose_first_route
from ml_pipeline.model_experiment import _curves, _scores, rule_route
from ml_pipeline.prep_data import ROUTES, make_text_features
from ml_pipeline.route_next.evidence import RequestEvidence


def fit_router(
    train: pd.DataFrame, *, words_only: bool, balanced: bool, c: float, catalog: Path | None = None,
) -> Pipeline:
    features = make_text_features()
    if words_only:
        features = dict(features.transformer_list)["words"]
    if catalog is not None:
        features = FeatureUnion([("ngrams", features), ("evidence", RequestEvidence(str(catalog.resolve())))],
                                transformer_weights={"evidence": 0.5})
    router = LogisticRegression(C=c, max_iter=1000, class_weight="balanced" if balanced else None)
    return Pipeline([("text", features), ("router", router)]).fit(train["text"], train["route"])


def catalog_v2(texts, old_model, catalog: SoftlineCatalog) -> list[str]:
    probabilities = old_model.predict_proba(texts)
    predictions = old_model.classes_[probabilities.argmax(axis=1)]
    return [
        choose_first_route(text, matches_catalog=catalog.has_title_phrase, suggested_route=prediction, score=float(score))
        for text, prediction, score in zip(texts, predictions, probabilities.max(axis=1), strict=True)
    ]


def run_validation(analysis_dir: Path, *, include_evidence: bool = False) -> dict:
    ledger = (analysis_dir / "route_next" / "PIPELINE.md").read_text(encoding="utf-8")
    if not re.search(r"^- Gate B: approved \d{4}-\d{2}-\d{2}$", ledger, re.M):
        raise RuntimeError("Approve the training plan before fitting the classifiers")

    private = analysis_dir / ".local"
    split = private / "route-split-v2"
    experiment = private / ("route-model-v2-evidence" if include_evidence else "route-model-v2")
    if experiment.exists():
        raise FileExistsError("This experiment already has a validation report")

    train_path = split / "train.jsonl"
    validation_path = split / "validation.jsonl"
    train = pd.read_json(train_path, lines=True)
    validation = pd.read_json(validation_path, lines=True)
    if set(train["route"]) != set(ROUTES) or set(validation["route"]) != set(ROUTES):
        raise ValueError("Training and validation require all route labels")
    if set(validation["origin"]) != {"archive_prefix"} or set(train["group_id"]) & set(validation["group_id"]):
        raise ValueError("Validation must contain independent archive messages only")

    old_path = private / "route-model-v1" / "router.joblib"
    old_model = joblib.load(old_path)
    old_report = json.loads((old_path.parent / "validation_report.json").read_text(encoding="utf-8"))
    old_run = next(run for run in old_report["runs"] if run["name"] == old_report["selected_learned_candidate"])
    catalog_path = private / "softline-catalog-2026-11-25.sqlite"
    texts, actual = validation["text"], validation["route"]
    actual_array = actual.to_numpy()
    runs = []

    def record(name, predictions, *, count=None, config=None):
        predictions = np.asarray(predictions)
        run = _scores(actual, predictions, name=name, train_count=count, config=config or {})
        run["handoff_false_positives"] = int(((actual_array != "handoff") & (predictions == "handoff")).sum())
        runs.append(run)
        return run

    # Score the fixed baselines on the same real validation set before fitting candidates.
    dummy = DummyClassifier(strategy="most_frequent").fit(np.zeros((len(train), 1)), train["route"])
    record("majority", dummy.predict(np.zeros((len(validation), 1))), count=len(train))
    record("rules_v1", texts.map(rule_route))
    record("words_v1", old_model.predict(texts), count=old_run["train_count"])
    record("catalog_guard_v2", catalog_v2(texts, old_model, SoftlineCatalog(catalog_path)))

    settings = (
        ("words_v2", True, False, 1.0),
        ("words_balanced", True, True, 1.0),
        ("words_chars", False, False, 1.0),
        ("words_chars_balanced", False, True, 1.0),
        ("words_chars_balanced_C0.3", False, True, 0.3),
        ("words_chars_balanced_C3", False, True, 3.0),
    )
    fitted = {}
    for name, words_only, balanced, c in settings:
        model = fit_router(train, words_only=words_only, balanced=balanced, c=c)
        fitted[name] = model
        record(name, model.predict(texts), count=len(train), config={
            "features": "words" if words_only else "words_and_characters",
            "class_weight": "balanced" if balanced else None,
            "C": c,
        })

    if include_evidence:
        for name, balanced in (("catalog_evidence", False), ("catalog_evidence_balanced", True)):
            model = fit_router(train, words_only=False, balanced=balanced, c=1.0, catalog=catalog_path)
            fitted[name] = model
            record(name, model.predict(texts), count=len(train), config={
                "features": "words_characters_and_catalog_cues", "evidence_weight": 0.5,
                "class_weight": "balanced" if balanced else None, "C": 1.0,
            })

    best = max((run for run in runs if run["name"] in fitted), key=lambda run: run["macro_f1_supported"])
    selected = fitted[best["name"]]
    report = {
        "validation_n": len(actual),
        "train_n": len(train),
        "sklearn_version": sklearn.__version__,
        "selection_metric": "macro_f1_supported",
        "selected": best["name"],
        "runs": runs,
        "curves": _curves(selected, texts, actual),
    }
    with tempfile.TemporaryDirectory(prefix="route-model-", dir=private) as temporary:
        stage = Path(temporary) / "output"
        stage.mkdir(mode=0o700)
        checkpoint = stage / "router.joblib"
        joblib.dump(selected, checkpoint)
        checkpoint.chmod(0o600)
        if not np.array_equal(joblib.load(checkpoint).predict(texts), selected.predict(texts)):
            raise RuntimeError("Model reload did not reproduce validation predictions")
        fingerprints = (train_path, validation_path, old_path, catalog_path, checkpoint)
        report["sha256"] = {}
        for name, path in zip(("train", "validation", "previous_model", "catalog", "selected_model"), fingerprints, strict=True):
            with path.open("rb") as stream:
                report["sha256"][name] = hashlib.file_digest(stream, "sha256").hexdigest()
        (stage / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stage.rename(experiment)
    return report
