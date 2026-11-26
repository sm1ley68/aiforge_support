from __future__ import annotations

import fcntl
import hashlib
import json
import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from aisupport_ml.commerce import catalog, routing
from ml_pipeline import guard, model_experiment, prep_data
from ml_pipeline.route_next import evidence, train


BASELINES = ("majority", "rules_v1", "words_v1", "catalog_guard_v2")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_once(path: Path, value: dict) -> None:
    data = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(data)


class FinalComparison:
    def __init__(self, analysis_dir: Path):
        private = analysis_dir / ".local"
        self.ledger = analysis_dir / "route_next" / "PIPELINE.md"
        self.split = private / "route-split-v2"
        self.experiment = private / "route-model-v2-evidence"
        self.selected_path = self.experiment / "router.joblib"
        self.prior_path = private / "route-model-v1" / "router.joblib"
        self.catalog_path = private / "softline-catalog-2026-11-25.sqlite"
        self.validation_path = self.experiment / "validation_report.json"
        self.plan_path = self.experiment / "frozen_comparison.json"
        self.final_path = self.experiment / "final_report.json"
        self.diagnostic_path = self.experiment / "validation_diagnostics.json"

    def plan(self) -> dict:
        report = read_json(self.validation_path)
        files = {"train": self.split / "train.jsonl", "validation": self.split / "validation.jsonl",
                 "previous_model": self.prior_path, "catalog": self.catalog_path, "selected_model": self.selected_path}
        fingerprints = {name: digest(path) for name, path in files.items()}
        if report["sha256"] != fingerprints or report["sklearn_version"] != sklearn.__version__:
            raise ValueError("Model, inputs or scikit-learn version changed after validation")
        majority = pd.read_json(files["train"], lines=True)["route"].mode().iat[0]
        state = read_json(self.split / ".guard_state.json")
        sources = (model_experiment, prep_data, train, evidence, catalog, routing, guard)
        return {"model": report["selected"], "variants": [*BASELINES, report["selected"]],
                "metric": report["selection_metric"], "majority_route": majority,
                "data_and_models_sha256": fingerprints, "validation_report_sha256": digest(self.validation_path),
                "code_sha256": {**{module.__name__: digest(Path(module.__file__)) for module in sources},
                                __name__: digest(Path(__file__))},
                "frozen_test_fingerprint": state["test_fingerprint"], "test_size": state["n_test"]}

    def freeze(self) -> None:
        if not self.diagnostic_path.is_file() or read_json(self.split / ".guard_state.json")["test_touches"]:
            raise RuntimeError("Complete validation diagnostics before freezing an unused test set")
        write_once(self.plan_path, self.plan())

    def predict(self, texts, *, plan, previous, selected) -> np.ndarray:
        return np.column_stack((
            np.repeat(plan["majority_route"], len(texts)),
            texts.map(model_experiment.rule_route),
            previous.predict(texts),
            train.catalog_v2(texts, previous, catalog.SoftlineCatalog(self.catalog_path)),
            selected.predict(texts),
        ))

    @staticmethod
    def summarize(actual, predictions, plan) -> dict:
        runs = []
        for label, guess in zip(plan["variants"], predictions.T, strict=True):
            scores = model_experiment._scores(actual, guess, name=label, train_count=None, config={})
            scores["handoff_false_positives"] = int(((actual != "handoff") & (guess == "handoff")).sum())
            runs.append(scores)
        return {"n": len(actual), "selected": plan["model"], "runs": runs}

    def diagnose_validation(self) -> dict:
        plan = self.plan()
        validation = pd.read_json(self.split / "validation.jsonl", lines=True)
        actual = validation["route"].to_numpy()
        previous = joblib.load(self.prior_path)
        selected = joblib.load(self.selected_path)
        predictions = self.predict(validation["text"], plan=plan, previous=previous, selected=selected)
        recomputed = self.summarize(actual, predictions, plan)
        report = read_json(self.validation_path)
        expected = {run["name"]: run["confusion"] for run in report["runs"]}
        if any(run["confusion"] != expected[run["name"]] for run in recomputed["runs"]):
            raise RuntimeError("Final evaluator did not reproduce validation confusion matrices")

        confidence = selected.predict_proba(validation["text"]).max(axis=1)
        correct = predictions[:, -1] == actual
        lengths = validation["text"].str.len().to_numpy()
        report = {"n": len(actual), "selected": plan["model"], "validation": recomputed,
                  "length_slices": {name: {"n": int(mask.sum()), "correct": int((correct & mask).sum())}
                                    for name, mask in (("up_to_80", lengths <= 80), ("over_80", lengths > 80))},
                  "mean_confidence_correct": float(confidence[correct].mean()),
                  "mean_confidence_wrong": float(confidence[~correct].mean())}
        write_once(self.diagnostic_path, report)
        return report

    def final(self) -> dict:
        if not re.search(r"^- Gate C: approved \d{4}-\d{2}-\d{2}$", self.ledger.read_text(encoding="utf-8"), re.M):
            raise RuntimeError("Approve the final comparison before opening the held-out data")
        with (self.experiment / ".final.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.final_path.exists() or read_json(self.split / ".guard_state.json")["test_touches"]:
                raise RuntimeError("The final comparison has already been run")
            plan = read_json(self.plan_path)
            if plan != self.plan():
                raise RuntimeError("The comparison has changed since it was frozen")
            previous = joblib.load(self.prior_path)
            selected = joblib.load(self.selected_path)
            result = {}

            def predict_frozen(features):
                return self.predict(features["text"], plan=plan, previous=previous, selected=selected)

            def heldout_macro_f1(actual, predictions):
                result.update(self.summarize(actual, predictions, plan))
                result["frozen_comparison_sha256"] = digest(self.plan_path)
                write_once(self.final_path, result)
                return result["runs"][-1]["macro_f1_supported"]

            held_out = pd.read_json(self.split / "held_out.jsonl", lines=True)
            guard.final_test(predict_frozen, held_out, target="route", metric_fn=heldout_macro_f1,
                             state_dir=self.split, pipeline_md=self.ledger)
        return result
