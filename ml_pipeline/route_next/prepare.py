from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

from ml_pipeline import guard
from ml_pipeline.prep_data import (
    ROUTES, _CONTACT, _FORBIDDEN_PRIVATE_TOKEN, _GREETING, _LATER_GREETING,
    _OPERATOR_MARKER, _PAGE, _PRIVATE_CONTEXT, _RECORD, _comparison_text,
    collect_candidates,
)

EXCLUDED = {"exclude:workflow_only", "exclude:uncertain_boundary", "exclude:private_context"}
SEED = 26112027


def supplemental_prefixes(archive: Path, positions: set[int]) -> dict[int, str]:
    """Recover manually verified first messages rejected by the short-question filter."""
    prefixes = {}
    position = 0
    with ZipFile(archive) as source:
        for name in sorted(name for name in source.namelist() if name.endswith(".txt")):
            for line in source.read(name).decode("utf-8-sig").splitlines():
                if not line.strip():
                    continue
                position += 1
                if position not in positions:
                    continue
                record = _RECORD.fullmatch(line.strip())
                if record is None:
                    raise ValueError(f"Unexpected record at position {position}")
                body, page_header = _PAGE.subn("", record.group(3))
                prefix, question_mark, _ = body.partition("?")
                text = _GREETING.sub("", " ".join(prefix.split())).strip() + question_mark
                private_or_mixed = any(pattern.search(text) for pattern in (
                    _CONTACT, _PRIVATE_CONTEXT, _FORBIDDEN_PRIVATE_TOKEN, _OPERATOR_MARKER, _LATER_GREETING,
                ))
                if not page_header or not 10 <= len(text) <= 361 or private_or_mixed:
                    raise ValueError(f"Unusable reviewed message at position {position}")
                prefixes[position] = text
    if prefixes.keys() != positions:
        raise ValueError("Some additional review positions are absent")
    return prefixes


def prepare_next_split(archive: Path, analysis_dir: Path) -> dict:
    ledger = (analysis_dir / "route_next" / "PIPELINE.md").read_text(encoding="utf-8")
    if not re.search(r"^- Gate A: approved \d{4}-\d{2}-\d{2}$", ledger, re.M):
        raise RuntimeError("Approve the next evaluation contract before preparing the data")
    private = analysis_dir / ".local"
    split_dir = private / "route-split-v2"
    if split_dir.exists():
        raise FileExistsError("The second split is frozen. Use view mode to read aggregate results.")

    review = json.loads((private / "route-review-v2" / "decisions.json").read_text(encoding="utf-8"))
    prior = json.loads((analysis_dir / "reviewed_routes.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != review["archive_sha256"] or digest != prior["archive_sha256"]:
        raise ValueError("Review decisions belong to a different archive snapshot")

    candidates, _ = collect_candidates(archive)
    candidate_text = {candidate.archive_position: candidate.text for candidate in candidates}
    prior_positions = {position for group in prior["routes"].values() for position in group}
    decisions = {int(position): label for position, label in review["decisions"].items()}
    if decisions.keys() != candidate_text.keys() - prior_positions or set(decisions.values()) - set(ROUTES) - EXCLUDED:
        raise ValueError("Expected one known review decision per previously unreviewed candidate")

    supplemental = {position: route for route, positions in review["supplemental"].items() for position in positions}
    if supplemental.keys() & candidate_text.keys() or set(supplemental.values()) - set(ROUTES):
        raise ValueError("Invalid additional review positions or labels")
    candidate_text.update(supplemental_prefixes(archive, set(supplemental)))

    # Old training data is the only previous split read. The previous review manifest
    # identifies duplicate candidates to exclude without reading the old held-out file.
    prior_train = pd.read_json(private / "route-split-v1" / "train.jsonl", lines=True)
    comparisons = [_comparison_text(candidate_text[position]) for position in prior_positions]
    comparisons.extend(_comparison_text(text) for text in prior_train.loc[prior_train["origin"] == "synthetic", "text"])
    seen = list(comparisons)
    near_duplicates: Counter = Counter()
    included = []
    for position, route in sorted((decisions | supplemental).items()):
        if route in EXCLUDED:
            continue
        text = candidate_text[position]
        normalized = _comparison_text(text)
        if any(SequenceMatcher(a=other, b=normalized, autojunk=False).ratio() >= 0.92 for other in seen):
            near_duplicates[route] += 1
            continue
        seen.append(normalized)
        included.append({"group_id": f"archive-{position:03}", "origin": "archive_prefix", "text": text, "route": route})
    fresh = pd.DataFrame(included)
    if not fresh["group_id"].is_unique or set(fresh["route"]) != set(ROUTES):
        raise ValueError("Expected unique reviewed messages covering all five routes")

    with tempfile.TemporaryDirectory(prefix="route-prep-", dir=private) as temporary:
        stage = Path(temporary) / "partition"
        # There is one first message per record. Near duplicates were removed before stratification.
        new_train, validation, held_out = guard.split(
            fresh, target="route", seed=SEED, test_size=0.30, val_size=0.26, state_dir=stage,
        )
        train = pd.concat([prior_train, new_train], ignore_index=True)
        guard.check_no_overlap(train, validation, held_out)
        all_group_ids = pd.concat([part["group_id"] for part in (train, validation, held_out)], ignore_index=True)
        if not all_group_ids.is_unique:
            raise ValueError("An archive or training group appears in more than one split")
        partitions = {"train": train, "validation": validation, "held_out": held_out}
        for name, frame in partitions.items():
            path = stage / f"{name}.jsonl"
            frame.to_json(path, orient="records", lines=True, force_ascii=False)
            path.chmod(0o600)

        report = {
            "seed": SEED,
            "reviewed_initial": len(decisions),
            "excluded_initial": dict(Counter(route for route in decisions.values() if route in EXCLUDED)),
            "reviewed_supplemental_accepted": len(supplemental),
            "duplicates_by_route": dict(near_duplicates),
            "new_by_route": fresh["route"].value_counts().reindex(ROUTES, fill_value=0).to_dict(),
            "new_train": len(new_train),
            "counts": {name: {"n": len(frame), "by_origin": frame["origin"].value_counts().to_dict(),
                              "by_route": frame["route"].value_counts().reindex(ROUTES, fill_value=0).to_dict()}
                       for name, frame in partitions.items()},
            "training_length_bins": pd.cut(
                train["text"].str.len(), bins=[0, 40, 80, 120, 160, 240, float("inf")],
                labels=["1–40", "41–80", "81–120", "121–160", "161–240", "241+"],
            ).value_counts(sort=False).to_dict(),
        }
        (stage / "prep_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stage.rename(split_dir)
    return report
