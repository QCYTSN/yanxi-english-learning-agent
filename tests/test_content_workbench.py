from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ielts_coach.content_imports import create_import, process_import
from ielts_coach.content_inventory import build_content_readiness, content_requirements
from ielts_coach.assessment_builder import assemble_assessment_pack, review_assessment_pack
from ielts_coach.init_home import initialise_home
from ielts_coach.question_bank import show_question


def test_content_readiness_reports_explicit_future_gaps(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    report = build_content_readiness(home)
    assert report["modules"]["reading"]["ready_for_varied_practice"] is False
    assert report["modules"]["listening"]["metrics"][0]["key"] == "verified_full_mocks"
    assert report["modules"]["writing"]["metrics"][0]["minimum_gap"] > 0
    assert content_requirements()["note"].startswith("库存数量")


def test_raw_private_pdf_is_staged_without_being_claimed_as_imported(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    job = create_import(
        home,
        title="My owned practice PDF",
        source_type="licensed_private",
        authenticity="official_practice_book",
        rights_status="local_private",
        files=[("Practice Book.pdf", b"%PDF-1.4\nprivate-test", "application/pdf")],
    )
    assert job["status"] == "needs_structuring"
    assert job["files"][0]["file_kind"] == "pdf"
    assert len(job["files"][0]["sha256"]) == 64
    with pytest.raises(ValueError, match="prepared manifest"):
        process_import(home, job["import_id"])


def test_prepared_manifest_package_can_be_validated_and_imported(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    manifest = {
        "corpus_id": "my-private-set",
        "title": "My private structured set",
        "source_type": "licensed_private",
        "authenticity": "practice_only",
        "rights_status": "local_private",
        "permissions": {
            "bundled_with_project": False,
            "redistribution_allowed": False,
            "local_personal_use_only": True,
        },
        "files": [{"kind": "questions", "path": "questions.jsonl"}],
    }
    question = {
        "question_id": "PRIVATE-W-001",
        "module": "writing",
        "task": "task2",
        "question_type": "opinion",
        "minimum_words": 250,
        "content": "Some people prefer to work in small organisations. To what extent do you agree?",
        "source_type": "licensed_private",
        "authenticity": "practice_only",
        "review_status": "reviewed",
        "conformance_status": "verified",
    }
    job = create_import(
        home,
        title="Structured set",
        source_type="licensed_private",
        authenticity="practice_only",
        rights_status="local_private",
        files=[
            ("manifest.yaml", yaml.safe_dump(manifest, sort_keys=False).encode(), "application/yaml"),
            ("questions.jsonl", (json.dumps(question) + "\n").encode(), "application/x-ndjson"),
        ],
    )
    assert job["status"] == "ready_to_import"
    imported = process_import(home, job["import_id"])
    assert imported["status"] == "imported"
    assert imported["summary"]["import_result"]["questions"] == 1
    stored = show_question(home, "PRIVATE-W-001")
    assert stored is not None
    assert stored["source_review_status"] == "reviewed"
    assert stored["review_status"] == "unreviewed"
    assert stored["conformance_status"] == "provisional"


def test_content_upload_rejects_unsafe_file_types(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    with pytest.raises(ValueError, match="Unsupported content file type"):
        create_import(
            home,
            title="Bad upload",
            source_type="personal",
            authenticity="unreviewed",
            rights_status="local_private",
            files=[("run.exe", b"not allowed", "application/octet-stream")],
        )


def test_import_manifest_cannot_override_registered_provenance(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    manifest = {
        "corpus_id": "mismatched-set",
        "title": "Mismatched set",
        "source_type": "personal",
        "authenticity": "self_created",
        "rights_status": "redistributable",
        "permissions": {
            "bundled_with_project": False,
            "redistribution_allowed": True,
            "local_personal_use_only": False,
        },
        "files": [{"kind": "questions", "path": "questions.jsonl"}],
    }
    job = create_import(
        home,
        title="Registered private source",
        source_type="licensed_private",
        authenticity="practice_only",
        rights_status="local_private",
        files=[
            ("manifest.yaml", yaml.safe_dump(manifest, sort_keys=False).encode(), "application/yaml"),
            ("questions.jsonl", b"", "application/x-ndjson"),
        ],
    )
    with pytest.raises(ValueError, match="provenance does not match"):
        process_import(home, job["import_id"])


def test_assessment_pack_builder_derives_structure_and_requires_item_review(tmp_path: Path) -> None:
    home = tmp_path / "home"
    initialise_home(home)
    pack = assemble_assessment_pack(
        home,
        module="writing",
        title="Starter writing pair",
        question_ids=["START-WT1-001", "START-WT2-001"],
    )
    assert pack["practice_mode"] == "full_mock"
    assert {item["task"] for item in pack["structure"]["tasks"]} == {"task1", "task2"}
    assert pack["conformance_status"] == "provisional"
    with pytest.raises(ValueError, match="reviewer and completed checklist"):
        review_assessment_pack(home, pack["pack_id"])

    with pytest.raises(ValueError, match="does not belong"):
        assemble_assessment_pack(
            home,
            module="writing",
            title="Mixed modules",
            question_ids=["START-WT2-001", "START-R-001"],
        )
