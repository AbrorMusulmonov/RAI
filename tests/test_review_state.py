from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.export import __main__ as export_main
from src.review import __main__ as review_main


CATEGORY = "GEN-1"
SOURCE_URL = "https://research-fixture.invalid/discussion"
EXAMPLE_A = "exact original comment text A"
EXAMPLE_B = "exact original comment text B"
FIELDS = [
    "Candidate ID",
    "Example",
    "Context",
    "Source Platform",
    "Source Name",
    "Source URL",
    "Content URL",
    "Source Item ID",
    "Retrieval Tier",
    "Retrieval Signal",
    "Stance Hint",
    "Stance Evidence",
    "Suggested Category",
    "Possible Compound Category",
    "Review Status",
    "Reviewer Notes",
]


def make_row(candidate_id: str, status: str = "PENDING", example: str = EXAMPLE_A, **extra: str) -> dict[str, str]:
    row = {field: "" for field in FIELDS}
    row.update(
        {
            "Candidate ID": candidate_id,
            "Example": example,
            "Context": "Public test comment.",
            "Source Platform": "YouTube",
            "Source Name": "Test Source",
            "Source URL": SOURCE_URL,
            "Source Item ID": f"ITEM-{candidate_id}",
            "Suggested Category": CATEGORY,
            "Review Status": status,
        }
    )
    row.update(extra)
    return row


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def ids_in(path: Path) -> list[str]:
    _, rows = review_main.load_rows(path)
    return [row.get("Candidate ID", "") for row in rows]


def status_in(path: Path, candidate_id: str) -> str | None:
    _, rows = review_main.load_rows(path)
    for row in rows:
        if row.get("Candidate ID") == candidate_id:
            return row.get("Review Status")
    return None


def exportable_ids() -> list[str]:
    registry = json.loads((export_main.PROJECT_ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
    verified_urls = {
        source["url"]
        for source in registry["sources"]
        if export_main.source_is_verified(source)
    }
    raw_by_id, occurrences = export_main.load_evidence()
    return [
        row["Candidate ID"]
        for row in export_main.current_exportable_rows(CATEGORY, verified_urls, raw_by_id, occurrences)
    ]


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(review_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(export_main, "PROJECT_ROOT", tmp_path)
    (tmp_path / "data" / "reviewed").mkdir(parents=True)
    (tmp_path / "data" / "rejected").mkdir(parents=True)
    (tmp_path / "data" / "candidates").mkdir(parents=True)
    (tmp_path / "data" / "raw" / "youtube").mkdir(parents=True)
    write_json(
        tmp_path / "config" / "taxonomy.json",
        {"subcategories": [{"code": CATEGORY, "name": "General misogyny"}]},
    )
    write_json(
        tmp_path / "config" / "sources.json",
        {
            "sources": [
                {
                    "url": SOURCE_URL,
                    "verified": True,
                    "public_access": True,
                    "reachability_verified": True,
                    "identity_verified": True,
                },
            ]
        },
    )
    write_jsonl(
        tmp_path / "data" / "raw" / "youtube" / "GEN-1.jsonl",
        [
            {
                "raw_record_id": "RAW-A",
                "original_text": EXAMPLE_A,
                "example_is_real_world": True,
                "source_verified": True,
            },
            {
                "raw_record_id": "RAW-B",
                "original_text": EXAMPLE_B,
                "example_is_real_world": True,
                "source_verified": True,
            },
        ],
    )
    write_jsonl(
        tmp_path / "data" / "candidates" / "GEN-1.occurrences.jsonl",
        [
            {"candidate_id": "CAND-A", "raw_record_id": "RAW-A"},
            {"candidate_id": "CAND-B", "raw_record_id": "RAW-B"},
        ],
    )
    return tmp_path


def seed_queue(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    review_main.atomic_write(review_main.review_queue_path(CATEGORY), FIELDS, rows)
    return rows


def test_pending_to_accept(project: Path) -> None:
    rows = seed_queue([make_row("CAND-A", "PENDING"), make_row("CAND-B", "PENDING", example=EXAMPLE_B)])
    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "ACCEPT")

    assert status_in(review_main.review_queue_path(CATEGORY), "CAND-A") == "ACCEPT"
    assert status_in(review_main.review_queue_path(CATEGORY), "CAND-B") == "PENDING"
    assert ids_in(review_main.reviewed_path(CATEGORY)) == ["CAND-A"]
    assert status_in(review_main.reviewed_path(CATEGORY), "CAND-A") == "ACCEPT"
    assert "CAND-A" not in ids_in(review_main.rejected_path(CATEGORY))
    assert ids_in(review_main.rejected_path(CATEGORY)) == []
    assert exportable_ids() == ["CAND-A"]


def test_accept_to_reject_removes_stale_reviewed_copy(project: Path) -> None:
    rows = seed_queue([make_row("CAND-A", "PENDING"), make_row("CAND-B", "PENDING", example=EXAMPLE_B)])
    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "ACCEPT")
    review_main.persist_decision(CATEGORY, FIELDS, rows, 1, "ACCEPT")
    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "REJECT")

    assert status_in(review_main.review_queue_path(CATEGORY), "CAND-A") == "REJECT"
    assert status_in(review_main.review_queue_path(CATEGORY), "CAND-B") == "ACCEPT"
    assert "CAND-A" not in ids_in(review_main.reviewed_path(CATEGORY))
    assert ids_in(review_main.reviewed_path(CATEGORY)) == ["CAND-B"]
    assert ids_in(review_main.rejected_path(CATEGORY)) == ["CAND-A"]
    assert status_in(review_main.rejected_path(CATEGORY), "CAND-A") == "REJECT"
    assert exportable_ids() == ["CAND-B"]


def test_reject_to_accept_removes_stale_rejected_copy(project: Path) -> None:
    rows = seed_queue([make_row("CAND-A", "PENDING"), make_row("CAND-B", "REJECT", example=EXAMPLE_B)])
    review_main.persist_decision(CATEGORY, FIELDS, rows, 1, "REJECT")
    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "REJECT")
    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "ACCEPT")

    assert status_in(review_main.review_queue_path(CATEGORY), "CAND-A") == "ACCEPT"
    assert status_in(review_main.review_queue_path(CATEGORY), "CAND-B") == "REJECT"
    assert ids_in(review_main.reviewed_path(CATEGORY)) == ["CAND-A"]
    assert ids_in(review_main.rejected_path(CATEGORY)) == ["CAND-B"]
    assert "CAND-A" not in ids_in(review_main.rejected_path(CATEGORY))
    assert exportable_ids() == ["CAND-A"]


def test_accept_to_unsure_is_not_exported(project: Path) -> None:
    rows = seed_queue([make_row("CAND-A", "PENDING"), make_row("CAND-B", "PENDING", example=EXAMPLE_B)])
    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "ACCEPT")
    review_main.persist_decision(CATEGORY, FIELDS, rows, 1, "ACCEPT")
    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "UNSURE")

    assert status_in(review_main.review_queue_path(CATEGORY), "CAND-A") == "UNSURE"
    assert ids_in(review_main.reviewed_path(CATEGORY)) == ["CAND-A", "CAND-B"]
    assert status_in(review_main.reviewed_path(CATEGORY), "CAND-A") == "UNSURE"
    assert "CAND-A" not in ids_in(review_main.rejected_path(CATEGORY))
    assert exportable_ids() == ["CAND-B"]


def test_accept_to_move_to_other_category_is_not_exported(project: Path) -> None:
    rows = seed_queue([make_row("CAND-A", "PENDING"), make_row("CAND-B", "PENDING", example=EXAMPLE_B)])
    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "ACCEPT")
    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "MOVE_TO_OTHER_CATEGORY")

    assert status_in(review_main.review_queue_path(CATEGORY), "CAND-A") == "MOVE_TO_OTHER_CATEGORY"
    assert ids_in(review_main.reviewed_path(CATEGORY)) == ["CAND-A"]
    assert "CAND-A" not in ids_in(review_main.rejected_path(CATEGORY))
    assert exportable_ids() == []


def test_accept_to_pending_clears_durable_decisions(project: Path) -> None:
    rows = seed_queue([make_row("CAND-A", "PENDING"), make_row("CAND-B", "PENDING", example=EXAMPLE_B)])
    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "ACCEPT")
    review_main.persist_decision(CATEGORY, FIELDS, rows, 1, "REJECT")
    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "PENDING")

    assert status_in(review_main.review_queue_path(CATEGORY), "CAND-A") == "PENDING"
    assert "CAND-A" not in ids_in(review_main.reviewed_path(CATEGORY))
    assert "CAND-A" not in ids_in(review_main.rejected_path(CATEGORY))
    assert ids_in(review_main.rejected_path(CATEGORY)) == ["CAND-B"]
    assert exportable_ids() == []


def test_sync_pending_removes_stale_durable_copies(project: Path) -> None:
    review_main.atomic_write(
        project / "data" / "candidates" / "GEN-1.csv",
        FIELDS,
        [make_row("CAND-A", "PENDING"), make_row("CAND-B", "ACCEPT", example=EXAMPLE_B)],
    )
    review_main.atomic_write(
        review_main.reviewed_path(CATEGORY),
        FIELDS,
        [make_row("CAND-A", "ACCEPT"), make_row("CAND-B", "ACCEPT", example=EXAMPLE_B)],
    )
    review_main.atomic_write(
        review_main.rejected_path(CATEGORY),
        FIELDS,
        [make_row("CAND-A", "REJECT")],
    )

    review_main.sync_candidate_decisions(CATEGORY)

    assert status_in(review_main.review_queue_path(CATEGORY), "CAND-A") is None
    assert "CAND-A" not in ids_in(review_main.reviewed_path(CATEGORY))
    assert "CAND-A" not in ids_in(review_main.rejected_path(CATEGORY))
    assert ids_in(review_main.reviewed_path(CATEGORY)) == ["CAND-B"]
    assert exportable_ids() == ["CAND-B"]


def test_sync_uses_review_queue_when_present(project: Path) -> None:
    seed_queue([make_row("CAND-A", "REJECT"), make_row("CAND-B", "ACCEPT", example=EXAMPLE_B)])
    review_main.atomic_write(
        project / "data" / "candidates" / "GEN-1.csv",
        FIELDS,
        [make_row("CAND-A", "ACCEPT"), make_row("CAND-B", "REJECT", example=EXAMPLE_B)],
    )
    review_main.atomic_write(
        review_main.reviewed_path(CATEGORY),
        FIELDS,
        [make_row("CAND-A", "ACCEPT")],
    )

    review_main.sync_candidate_decisions(CATEGORY)

    assert "CAND-A" not in ids_in(review_main.reviewed_path(CATEGORY))
    assert ids_in(review_main.rejected_path(CATEGORY)) == ["CAND-A"]
    assert ids_in(review_main.reviewed_path(CATEGORY)) == ["CAND-B"]
    assert exportable_ids() == ["CAND-B"]


def test_exporter_ignores_stale_reviewed_accept_when_queue_disagrees(project: Path) -> None:
    seed_queue([make_row("CAND-A", "REJECT")])
    review_main.atomic_write(
        review_main.reviewed_path(CATEGORY),
        FIELDS,
        [make_row("CAND-A", "ACCEPT")],
    )

    assert exportable_ids() == []


def test_exporter_falls_back_to_reviewed_csv_without_queue(project: Path) -> None:
    review_main.atomic_write(
        review_main.reviewed_path(CATEGORY),
        FIELDS,
        [make_row("CAND-A", "ACCEPT"), make_row("CAND-B", "UNSURE", example=EXAMPLE_B)],
    )

    assert not review_main.review_queue_path(CATEGORY).exists()
    assert exportable_ids() == ["CAND-A"]


def test_rejected_then_accepted_regains_original_final_id(project: Path) -> None:
    mapping = {"GEN-1:CAND-A": "GEN1-001"}
    write_json(project / "data" / "reviewed" / "final_ids.json", mapping)
    rows = seed_queue([make_row("CAND-A", "PENDING")])
    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "ACCEPT")
    export_main.main()
    first = json.loads((project / "data" / "reviewed" / "final_ids.json").read_text(encoding="utf-8"))
    assert first["GEN-1:CAND-A"] == "GEN1-001"

    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "REJECT")
    export_main.main()
    after_reject = json.loads((project / "data" / "reviewed" / "final_ids.json").read_text(encoding="utf-8"))
    assert after_reject["GEN-1:CAND-A"] == "GEN1-001"
    assert exportable_ids() == []

    review_main.persist_decision(CATEGORY, FIELDS, rows, 0, "ACCEPT")
    regained = export_main.allocate_id("GEN-1", "CAND-A", dict(after_reject))
    assert regained == "GEN1-001"
    other = export_main.allocate_id("GEN-1", "CAND-B", dict(after_reject))
    assert other != "GEN1-001"


def test_helpers_do_not_rewrite_when_unchanged(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = review_main.reviewed_path(CATEGORY)
    review_main.upsert_by_candidate_id(path, FIELDS, make_row("CAND-A", "ACCEPT"))
    writes: list[Path] = []
    original = review_main.atomic_write

    def tracking_write(target: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
        writes.append(target)
        original(target, fields, rows)

    monkeypatch.setattr(review_main, "atomic_write", tracking_write)
    assert review_main.upsert_by_candidate_id(path, FIELDS, make_row("CAND-A", "ACCEPT")) is False
    assert review_main.remove_by_candidate_id(path, "CAND-MISSING") is False
    assert writes == []


def test_pending_order_supports_priority_and_tier_filters() -> None:
    rows = [
        {"Candidate ID": "A", "Review Status": "PENDING", "Retrieval Tier": "SECONDARY", "Review Priority Score": "70"},
        {"Candidate ID": "B", "Review Status": "REJECT", "Retrieval Tier": "PRIMARY", "Review Priority Score": "100"},
        {"Candidate ID": "C", "Review Status": "PENDING", "Retrieval Tier": "PRIMARY", "Review Priority Score": "90"},
        {"Candidate ID": "D", "Review Status": "PENDING", "Retrieval Tier": "PRIMARY", "Review Priority Score": "80"},
    ]

    assert review_main.pending_order(rows) == [0, 2, 3]
    assert review_main.pending_order(rows, priority=True) == [2, 3, 0]
    assert review_main.pending_order(rows, priority=True, tier="PRIMARY") == [2, 3]
    assert review_main.pending_order(rows, priority=True, tier="SECONDARY") == [0]
