from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from src.export import __main__ as export_main
from src.processing import category as category_main
from src.review import __main__ as review_main


CATEGORY = "STA-4"
SOURCE_URL = "https://research-fixture.invalid/discussion"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def generalized_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for module in (category_main, export_main, review_main):
        monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    write_json(
        tmp_path / "config" / "taxonomy.json",
        {
            "subcategories": [
                {
                    "code": "GEN-1",
                    "name": "General misogyny",
                    "full_definition": "Protected category.",
                    "reference_examples": [],
                },
                {
                    "code": CATEGORY,
                    "name": "Age",
                    "full_definition": "Age-based worthlessness or exclusion.",
                    "reference_examples": ["davri o'tgan"],
                },
            ]
        },
    )
    write_json(
        tmp_path / "config" / "search_terms.json",
        {
            "categories": {
                CATEGORY: {
                    "strong_terms": ["davri o'tgan"],
                    "contextual_terms": ["qari qiz"],
                    "discovery_queries": ["qari qiz"],
                    "weak_terms": ["qari"],
                    "spelling_variants": [],
                    "target_terms": ["qari qiz"],
                    "harm_terms": {"exclusion": ["kim uylanadi"]},
                    "standalone_strong_terms": [],
                    "compound_patterns": {"GEN-2": ["qari qiz"]},
                }
            }
        },
    )
    write_json(
        tmp_path / "config" / "sources.json",
        {
            "sources": [
                {
                    "source_id": "fixture-source",
                    "name": "Verified fixture title",
                    "platform": "YouTube",
                    "url": SOURCE_URL,
                    "public_access": True,
                    "reachability_verified": True,
                    "identity_verified": True,
                    "verified_title": "Verified fixture title",
                    "verified_publisher": "Fixture publisher",
                }
            ]
        },
    )
    write_jsonl(
        tmp_path / "data" / "raw" / "youtube" / f"{CATEGORY}.jsonl",
        [
            {
                "raw_record_id": "fixture-source:C-1",
                "original_text": "Qari qiz, davri o'tgan, kim uylanadi unga?",
                "source_platform": "YouTube",
                "source_name": "Verified fixture title",
                "source_url": SOURCE_URL,
                "content_url": None,
                "source_item_id": "C-1",
                "retrieved_at": "2026-01-01T00:00:00+00:00",
                "example_is_real_world": True,
                "source_verified": True,
                "human_readable_provenance": (
                    "Verified fixture title | " + SOURCE_URL + " | Source Item ID: C-1"
                ),
            }
        ],
    )
    return tmp_path


def test_arbitrary_category_queue_and_provenance(generalized_project: Path) -> None:
    metrics = category_main.process_category(CATEGORY, include_cross_category=False)
    queue = csv_rows(generalized_project / "data" / "reviewed" / f"{CATEGORY}.review_queue.csv")

    assert metrics["combined_review_candidates"] == 1
    assert len(queue) == 1
    assert queue[0]["Review Status"] == "PENDING"
    assert queue[0]["Source URL"] == SOURCE_URL
    assert queue[0]["Source Item ID"] == "C-1"
    assert queue[0]["Content URL"] == ""
    assert queue[0]["Possible Compound Category"] == "GEN-2"
    assert queue[0]["Example"] == "Qari qiz, davri o'tgan, kim uylanadi unga?"
    assert queue[0]["Retrieval Tier"] in {"PRIMARY", "SECONDARY"}
    assert queue[0]["Suggested Category"] == CATEGORY
    assert float(queue[0]["Model Retrieval Relevance"]) > 0
    assert queue[0]["Model Evidence Span"].strip("…").strip() in queue[0]["Example"]
    assert queue[0]["Review Status"] != "ACCEPT"
    candidate_rows = csv_rows(generalized_project / "data" / "candidates" / f"{CATEGORY}.csv")
    candidate_rows += csv_rows(
        generalized_project / "data" / "candidates" / f"{CATEGORY}.secondary_review.csv"
    )
    assert "Source Item ID: C-1" in candidate_rows[0]["Provenance"]
    assert queue[0]["Source URL"].startswith("https://research-fixture.invalid/")


def test_category_export_requires_human_accept(generalized_project: Path) -> None:
    category_main.process_category(CATEGORY, include_cross_category=False)
    fields, queue = review_main.load_rows(review_main.review_queue_path(CATEGORY))
    export_main.main()
    assert json.loads((generalized_project / "data" / "reviewed" / "final_ids.json").read_text()) == {}

    review_main.persist_decision(CATEGORY, fields, queue, 0, "ACCEPT")
    export_main.main()
    mapping = json.loads((generalized_project / "data" / "reviewed" / "final_ids.json").read_text())
    assert mapping == {f"{CATEGORY}:{queue[0]['Candidate ID']}": "STA4-001"}

    export_main.main()
    assert json.loads((generalized_project / "data" / "reviewed" / "final_ids.json").read_text()) == mapping


def test_queue_regeneration_preserves_human_decision(generalized_project: Path) -> None:
    category_main.process_category(CATEGORY, include_cross_category=False)
    fields, queue = review_main.load_rows(review_main.review_queue_path(CATEGORY))
    candidate_id = queue[0]["Candidate ID"]
    review_main.persist_decision(CATEGORY, fields, queue, 0, "REJECT")

    category_main.process_category(CATEGORY, include_cross_category=False)
    regenerated = csv_rows(
        generalized_project / "data" / "reviewed" / f"{CATEGORY}.review_queue.csv"
    )
    matching = [row for row in regenerated if row["Candidate ID"] == candidate_id]
    assert len(matching) == 1
    assert matching[0]["Review Status"] == "REJECT"


def test_unverified_source_cannot_enter_queue_or_export(generalized_project: Path) -> None:
    sources = json.loads((generalized_project / "config" / "sources.json").read_text(encoding="utf-8"))
    sources["sources"][0]["identity_verified"] = False
    write_json(generalized_project / "config" / "sources.json", sources)
    metrics = category_main.process_category(CATEGORY, include_cross_category=False)
    assert metrics["combined_review_candidates"] == 0
    assert metrics["provenance_failures"]["SOURCE_UNVERIFIED"] == 1


def test_gen1_processor_guard_preserves_decisions(generalized_project: Path) -> None:
    protected = generalized_project / "data" / "reviewed" / "GEN-1.review_queue.csv"
    protected.parent.mkdir(parents=True, exist_ok=True)
    protected.write_text("Candidate ID,Review Status\nGEN1-C-ABC,ACCEPT\n", encoding="utf-8")
    before = hashlib.sha256(protected.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="GEN-1 is protected"):
        category_main.process_category("GEN-1")
    assert hashlib.sha256(protected.read_bytes()).hexdigest() == before


def test_empty_category_queue_is_a_valid_review_state(
    generalized_project: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    review_main.atomic_write(
        review_main.review_queue_path(CATEGORY), category_main.REVIEW_FIELDS, [],
    )
    review_main.interactive_review(CATEGORY)
    assert "No review candidates are currently available" in capsys.readouterr().out


def test_near_duplicate_collapse_keeps_occurrence_mapping() -> None:
    base = {
        "Candidate ID": "A",
        "Example": "Bu qari odamning davri o'tgan, hech kimga kerak emas.",
        "Review Status": "PENDING",
        "Retrieval Score": 10,
    }
    copy = {
        **base,
        "Candidate ID": "B",
        "Example": "Bu qari odamning davri o'tgan hech kimga kerak emas.",
        "Retrieval Score": 9,
    }
    kept, remap = category_main.near_deduplicate([copy, base])
    assert [row["Candidate ID"] for row in kept] == ["A"]
    assert remap == {"B": "A"}
