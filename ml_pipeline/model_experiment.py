from __future__ import annotations

import hashlib
import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_recall_curve,
    precision_recall_fscore_support,
    roc_curve,
)
from sklearn.pipeline import Pipeline

from ml_pipeline.prep_data import ROUTES, make_text_features, normalize_route_text


_HANDOFF = re.compile(
    r"переключ\w*|соедини\w*|позов\w*|\b(?:менеджер|оператор)\w*\b|"
    r"индивидуальн\w* (?:услови|скидк)|персональн\w* скидк|постоплат\w*"
)
_FIND = re.compile(r"какую лицензи|какая лицензи|какую верси|какой редакц|как (?:докупить|обновить)|как.*продлить")
_NEED = re.compile(r"посовет\w*|подбер\w*|подобрат\w*|ищ[уе]\w*|что (?:купить|выбрать)|какое решение")
_FACT = re.compile(
    r"\b(?:цен\w*|стоимост\w*|наличи\w*)\b|сколько (?:будет )?сто\w*|"
    r"(?:можно|возможно) ли (?:приобрести|купить)|можно (?:приобрести|купить)|есть ли"
)
_GENERIC_FACT_WORDS = set("подскажите пожалуйста скажите сколько какая какой цена стоимость стоит ваша у вас стоит "
                          "можно ли приобрести купить как есть будет это за на он она".split())


def rule_route(message: str) -> str:
    """Small, deliberately fixed rule baseline for the first message."""
    text = normalize_route_text(message)
    if _HANDOFF.search(text):
        return "handoff"
    if _FIND.search(text):
        return "find_named_product"
    if _NEED.search(text):
        return "recommend_by_need"
    if _FACT.search(text):
        # A bare price question needs a referent; numeric quantities don't name a product.
        content_words = set(re.findall(r"[a-zа-я]+", text)) - _GENERIC_FACT_WORDS
        if content_words and not content_words <= {"лицензия", "лицензии", "пользователей", "пользователя", "вот"}:
            return "answer_product_question"
    return "clarify"


def _fit_text(text: pd.Series, routes: pd.Series, *, words_only: bool, c: float) -> Pipeline:
    features = make_text_features()
    if words_only:
        features = dict(features.transformer_list)["words"]
    estimator = Pipeline([
        ("text", features),
        ("router", LogisticRegression(C=c, max_iter=1000)),
    ])
    return estimator.fit(text, routes)


def _scores(actual: pd.Series, predicted, *, name: str, train_count: int | None, config: dict) -> dict:
    precision, recall, f1, support = precision_recall_fscore_support(
        actual, predicted, labels=ROUTES, zero_division=0,
    )
    supported = support > 0
    per_route = {}
    for route, p, r, score, count in zip(ROUTES, precision, recall, f1, support, strict=True):
        per_route[route] = {
            "support": int(count),
            "precision": float(p) if count else None,
            "recall": float(r) if count else None,
            "f1": float(score) if count else None,
        }
    return {
        "name": name,
        "train_count": train_count,
        "config": config,
        "macro_f1_supported": float(np.mean(f1[supported])),
        "correct": int(np.count_nonzero(np.asarray(actual) == predicted)),
        "per_route": per_route,
        "confusion": confusion_matrix(actual, predicted, labels=ROUTES).tolist(),
    }


def _curves(model: Pipeline, text: pd.Series, actual: pd.Series) -> dict:
    probabilities = model.predict_proba(text)
    curves = {}
    for index, route in enumerate(model.classes_):
        given_route = (actual == route).to_numpy()
        if not given_route.any() or given_route.all():
            continue
        scores = probabilities[:, index]
        precision, recall, _ = precision_recall_curve(given_route, scores)
        fpr, tpr, _ = roc_curve(given_route, scores)
        curves[str(route)] = {
            "precision": precision.tolist(), "recall": recall.tolist(),
            "fpr": fpr.tolist(), "tpr": tpr.tolist(),
            "ap": float(average_precision_score(given_route, scores)),
        }
    return curves


def run_route_experiment(split_dir: Path, model_path: Path) -> dict:
    """Read train and validation only. Save the selected, un-deployed candidate."""
    train_path, validation_path = (split_dir / f"{name}.jsonl" for name in ("train", "validation"))
    train = pd.read_json(train_path, lines=True)
    validation = pd.read_json(validation_path, lines=True)
    if not len(train) or not len(validation) or set(train["route"]) != set(ROUTES):
        raise ValueError("Missing training classes or validation records")
    if set(train["group_id"]) & set(validation["group_id"]) or set(validation["origin"]) != {"archive_prefix"}:
        raise ValueError("Expected independent, archive-only validation")
    text_train, routes_train = train["text"], train["route"]
    text_val, routes_val = validation["text"], validation["route"]

    # 09: measure both fit baselines before fitting any other candidate.
    dummy = DummyClassifier(strategy="most_frequent").fit(np.zeros((len(train), 1)), routes_train)
    runs = [_scores(routes_val, dummy.predict(np.zeros((len(validation), 1))), name="majority",
                    train_count=len(train), config={"strategy": "most_frequent"})]
    words = _fit_text(text_train, routes_train, words_only=True, c=1.0)
    runs.append(_scores(routes_val, words.predict(text_val), name="words", train_count=len(train),
                        config={"features": "words", "C": 1.0, "training": "mixed"}))
    runs.append(_scores(routes_val, np.asarray([rule_route(item) for item in text_val]), name="rules",
                        train_count=None, config={"strategy": "fixed_rules_v1"}))

    # 10: compare character features and one matched training-source ablation.
    mixed = _fit_text(text_train, routes_train, words_only=False, c=1.0)
    feature_config = {"features": "words_and_characters", "C": 1.0, "training": "mixed"}
    runs.append(_scores(routes_val, mixed.predict(text_val), name="words_char_C1", train_count=len(train),
                        config=feature_config))
    archive = train.loc[train["origin"] == "archive_prefix"]
    archive_model = _fit_text(archive["text"], archive["route"], words_only=False, c=1.0)
    runs.append(_scores(routes_val, archive_model.predict(text_val), name="words_char_archive",
                        train_count=len(archive), config={**feature_config, "training": "archive_only"}))

    # 11: tune only C on validation; fixed order breaks ties in favour of simpler comparisons.
    learned = {"words": words, "words_char_C1": mixed, "words_char_archive": archive_model}
    for c in (0.3, 3.0):
        name = f"words_char_C{c:g}"
        estimator = _fit_text(text_train, routes_train, words_only=False, c=c)
        runs.append(_scores(routes_val, estimator.predict(text_val), name=name,
                            train_count=len(train), config={**feature_config, "C": c}))
        learned[name] = estimator
    chosen = max((run for run in runs if run["name"] in learned), key=lambda run: run["macro_f1_supported"])
    selected_model = learned[chosen["name"]]

    # 12: retain validation diagnostics and a private experiment checkpoint.
    joblib.dump(selected_model, model_path)
    reloaded = joblib.load(model_path)
    if not np.array_equal(reloaded.predict(text_val), selected_model.predict(text_val)):
        raise RuntimeError("Experiment checkpoint does not reproduce validation predictions")
    return {
        "sklearn_version": sklearn.__version__,
        "sources_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in (train_path, validation_path)},
        "validation_n": len(validation),
        "validation_support": {route: int((routes_val == route).sum()) for route in ROUTES},
        "selection_metric": "macro_f1_supported",
        "selected_learned_candidate": chosen["name"],
        "runs": runs,
        "curves": {name: _curves(model, text_val, routes_val) for name, model in
                   (("words", words), ("selected", selected_model))},
    }
