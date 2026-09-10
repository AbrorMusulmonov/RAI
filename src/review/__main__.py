from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import sys

from src.utils.io import PROJECT_ROOT, read_json


ALLOWED = {"PENDING", "ACCEPT", "REJECT", "UNSURE", "MOVE_TO_OTHER_CATEGORY"}
REVIEWED_KEEP_STATUSES = {"ACCEPT", "UNSURE", "MOVE_TO_OTHER_CATEGORY"}
CHOICES = {
    "A": "ACCEPT",
    "R": "REJECT",
    "U": "UNSURE",
    "M": "MOVE_TO_OTHER_CATEGORY",
}


def load_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def atomic_write(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _projected_row(row: dict[str, str], fields: list[str]) -> dict[str, str]:
    return {field: row.get(field, "") for field in fields}


def upsert_by_candidate_id(path: Path, fields: list[str], row: dict[str, str]) -> bool:
    candidate_id = row.get("Candidate ID") or ""
    if not candidate_id:
        raise ValueError("Cannot upsert a row without Candidate ID")
    old_fields, old_rows = load_rows(path)
    effective_fields = old_fields or list(fields)
    incoming = _projected_row(row, effective_fields)
    found = False
    changed = False
    updated: list[dict[str, str]] = []
    for existing in old_rows:
        if existing.get("Candidate ID") == candidate_id:
            found = True
            if _projected_row(existing, effective_fields) != incoming:
                changed = True
            updated.append(incoming)
        else:
            updated.append(existing)
    if not found:
        updated.append(incoming)
        changed = True
    if changed:
        atomic_write(path, effective_fields, updated)
    return changed


def remove_by_candidate_id(path: Path, candidate_id: str) -> bool:
    if not candidate_id or not path.exists():
        return False
    fields, rows = load_rows(path)
    kept = [row for row in rows if row.get("Candidate ID") != candidate_id]
    if len(kept) == len(rows):
        return False
    atomic_write(path, fields, kept)
    return True


def reviewed_path(category: str) -> Path:
    return PROJECT_ROOT / "data" / "reviewed" / f"{category}.csv"


def rejected_path(category: str) -> Path:
    return PROJECT_ROOT / "data" / "rejected" / f"{category}.csv"


def review_queue_path(category: str) -> Path:
    return PROJECT_ROOT / "data" / "reviewed" / f"{category}.review_queue.csv"


def decision_source_path(category: str) -> Path:
    queue_path = review_queue_path(category)
    if queue_path.exists():
        return queue_path
    return PROJECT_ROOT / "data" / "candidates" / f"{category}.csv"


def sync_decision_files(category: str, fields: list[str], row: dict[str, str]) -> None:
    status = (row.get("Review Status") or "").strip()
    if status not in ALLOWED:
        raise ValueError(f"Invalid review status: {status!r}")
    candidate_id = row.get("Candidate ID") or ""
    if not candidate_id:
        raise ValueError("Cannot synchronize a row without Candidate ID")
    if status == "REJECT":
        upsert_by_candidate_id(rejected_path(category), fields, row)
        remove_by_candidate_id(reviewed_path(category), candidate_id)
    elif status in REVIEWED_KEEP_STATUSES:
        upsert_by_candidate_id(reviewed_path(category), fields, row)
        remove_by_candidate_id(rejected_path(category), candidate_id)
    else:
        remove_by_candidate_id(reviewed_path(category), candidate_id)
        remove_by_candidate_id(rejected_path(category), candidate_id)


def sync_candidate_decisions(category: str) -> None:
    """Preserve the original spreadsheet-to-durable-review synchronization mode."""
    source = decision_source_path(category)
    fields, rows = load_rows(source)
    if not rows:
        raise SystemExit(f"No candidate queue found for {category}")
    invalid = sorted({(row.get("Review Status") or "").strip() for row in rows} - ALLOWED)
    if invalid:
        raise SystemExit(f"Invalid review statuses: {invalid}")
    for row in rows:
        sync_decision_files(category, fields, row)
    _, reviewed_rows = load_rows(reviewed_path(category))
    _, rejected_rows = load_rows(rejected_path(category))
    print(f"REVIEWED_STORED\t{len(reviewed_rows)}")
    print(f"REJECTED_STORED\t{len(rejected_rows)}")


def state_path(category: str) -> Path:
    return PROJECT_ROOT / "data" / "reviewed" / f"{category}.review_state.json"


def load_position(category: str, row_count: int) -> int:
    path = state_path(category)
    if not path.exists() or row_count == 0:
        return 0
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return int(state.get("next_index", 0)) % row_count
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0


def save_position(category: str, next_index: int) -> None:
    path = state_path(category)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"next_index": next_index}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def taxonomy_entry(category: str) -> dict[str, object]:
    taxonomy = read_json(PROJECT_ROOT / "config" / "taxonomy.json")
    try:
        return next(item for item in taxonomy["subcategories"] if item["code"] == category)
    except StopIteration as exc:
        raise SystemExit(f"Category {category} is not present in taxonomy.json") from exc


def display_candidate(
    row: dict[str, str], display_number: int, total: int, taxonomy: dict[str, object],
) -> None:
    print("-" * 50)
    print(f"Candidate {display_number} / {total}")
    print("\nTEXT:\n" + (row.get("Example") or ""))
    print("\nCONTEXT:\n" + (row.get("Context") or ""))
    source = f"{row.get('Source Name') or 'Unknown source'} | {row.get('Source URL') or ''}"
    source += f" | Source Item ID: {row.get('Source Item ID') or 'MISSING'}"
    print("\nSOURCE:\n" + source)
    print("\nRETRIEVAL:\n" + (row.get("Retrieval Tier") or ""))
    print((row.get("Retrieval Signal") or ""))
    if row.get("Review Priority Score"):
        print("\nREVIEW PRIORITY:")
        print(f"Score {row.get('Review Priority Score')} | {row.get('Priority Basis') or ''}")
    if row.get("Model Retrieval Relevance"):
        print("\nSEMANTIC RETRIEVAL SUPPORT:")
        print(
            f"Relevance {row.get('Model Retrieval Relevance')} | "
            f"Suggested {row.get('Model Suggested Category') or row.get('Suggested Category') or ''}"
        )
        print("Evidence span: " + (row.get("Model Evidence Span") or ""))
    print("\nSTANCE:\n" + (row.get("Stance Hint") or ""))
    print((row.get("Stance Evidence") or ""))
    compound = row.get("Possible Compound Category") or "None suggested"
    print("\nPOSSIBLE COMPOUND CATEGORY:\n" + compound)
    print(f"\nTAXONOMY:\n{taxonomy['code']} {taxonomy['name']}")
    print(str(taxonomy["full_definition"]))
    print("\nDecision:")
    print("[A] ACCEPT  [R] REJECT  [U] UNSURE  [M] MOVE TO OTHER CATEGORY  [S] SKIP  [Q] QUIT")
    print("-" * 50)


def persist_decision(
    category: str, fields: list[str], rows: list[dict[str, str]], index: int, status: str,
) -> None:
    if status not in ALLOWED:
        raise ValueError(f"Invalid review status: {status!r}")
    queue_path = review_queue_path(category)
    rows[index]["Review Status"] = status
    atomic_write(queue_path, fields, rows)
    sync_decision_files(category, fields, rows[index])


def pending_order(
    rows: list[dict[str, str]], start: int = 0, *, priority: bool = False,
    tier: str | None = None,
) -> list[int]:
    order = list(range(start, len(rows))) + list(range(0, start))
    pending = [
        index for index in order
        if rows[index].get("Review Status") == "PENDING"
        and (tier is None or (rows[index].get("Retrieval Tier") or "").upper() == tier)
    ]
    if priority:
        pending.sort(key=lambda index: (
            -float(rows[index].get("Review Priority Score") or 0),
            rows[index].get("Candidate ID") or "",
        ))
    return pending


def interactive_review(category: str, *, priority: bool = False, tier: str | None = None) -> None:
    queue_path = PROJECT_ROOT / "data" / "reviewed" / f"{category}.review_queue.csv"
    fields, rows = load_rows(queue_path)
    if not queue_path.exists():
        raise SystemExit(
            f"No combined review queue found at {queue_path}. "
            f"Run: python -m src.processing {category}"
        )
    if not rows:
        print(f"No review candidates are currently available in {queue_path}")
        return
    invalid = sorted({(row.get("Review Status") or "").strip() for row in rows} - ALLOWED)
    if invalid:
        raise SystemExit(f"Invalid review statuses: {invalid}")
    taxonomy = taxonomy_entry(category)
    start = load_position(category, len(rows))
    pending = pending_order(rows, start, priority=priority, tier=tier)
    if not pending:
        qualifier = f" {tier}" if tier else ""
        print(f"No{qualifier} PENDING candidates remain in {queue_path}")
        return

    for position, index in enumerate(pending):
        display_candidate(rows[index], index + 1, len(rows), taxonomy)
        while True:
            try:
                choice = input("Choice: ").strip().upper()
            except (EOFError, KeyboardInterrupt):
                print("\nReview stopped; the current position is saved.")
                save_position(category, index)
                return
            if choice in CHOICES or choice in {"S", "Q"}:
                break
            print("Enter A, R, U, M, S, or Q.")
        if choice == "Q":
            save_position(category, index)
            print("Review stopped; the current position is saved.")
            return
        next_index = pending[position + 1] if position + 1 < len(pending) else (index + 1) % len(rows)
        if choice == "S":
            save_position(category, next_index)
            continue
        persist_decision(category, fields, rows, index, CHOICES[choice])
        save_position(category, next_index)
        print(f"Saved {rows[index]['Candidate ID']} as {CHOICES[choice]}.")
    print("Reached the end of the pending review pass. All decisions were saved immediately.")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Review or synchronize human taxonomy decisions.")
    parser.add_argument("category", nargs="?", help="Category to review interactively, for example GEN-1")
    parser.add_argument("--category", dest="legacy_category", help="Legacy candidate-file synchronization mode")
    parser.add_argument("--sync-candidates", action="store_true", help="Synchronize decisions from the primary candidate CSV")
    parser.add_argument("--priority", action="store_true", help="Review highest transparent priority score first")
    tier_group = parser.add_mutually_exclusive_group()
    tier_group.add_argument("--primary-only", action="store_true", help="Review only PENDING PRIMARY candidates")
    tier_group.add_argument("--secondary-only", action="store_true", help="Review only PENDING SECONDARY candidates")
    parser.add_argument(
        "--pending-only", action="store_true",
        help="Explicitly select PENDING rows (the safe interactive default; accepted for scripting clarity)",
    )
    args = parser.parse_args()
    category = (args.category or args.legacy_category or "GEN-1").upper()
    if args.sync_candidates or (args.legacy_category and not args.category):
        sync_candidate_decisions(category)
    else:
        tier = "PRIMARY" if args.primary_only else "SECONDARY" if args.secondary_only else None
        interactive_review(category, priority=args.priority, tier=tier)


if __name__ == "__main__":
    main()
