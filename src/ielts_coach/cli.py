from __future__ import annotations

import json
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Optional

import typer

from .allocation import recommend_allocation
from . import __version__
from .backups import create_backup, list_backups, restore_backup, verify_backup
from .calibration import (
    calibration_report,
    import_calibration_case,
    import_calibration_run,
    list_calibration_cases,
    prepare_calibration_run,
    record_calibration,
)
from .capability_evaluation import (
    list_capability_evaluations,
    provider_reliability_report,
    run_contract_evaluation,
)
from .config import load_profile
from .conformance import assess_pack, assess_question, standard_profile
from .content_imports import imports as list_content_imports, process_import
from .content_inventory import build_content_readiness, content_requirements
from .corpus import corpus_stats, import_manifest, reindex_corpus
from .diagnostics import (
    attach_diagnostic_session,
    cancel_diagnostic,
    complete_diagnostic,
    diagnostic_status,
    start_diagnostic,
)
from .health import audit_data_home
from .init_home import initialise_home
from .onboarding import complete_onboarding, onboarding_status
from .paths import find_project_root, resolve_home
from .profiles import build_learning_profile
from .question_bank import draw_question, search_questions, show_question, show_reading_set
from .reports import build_summary, build_trend_report, build_weekly_report
from .scale_benchmark import run_temporary_scale_benchmark
from .session_io import load_data_file, load_session_file
from .session_manager import finish_session, show_session, start_session, transition_session
from .study_runtime import (
    apply_reading_review,
    apply_writing_review,
    reconcile_session,
    record_reading_hint,
    resume_session,
    submit_reading_answers,
    submit_writing_version,
)
from .speaking_io import import_speaking_report
from .storage import (
    SCHEMA_VERSION, connect, db_path, list_corpora, list_error_profile, list_sessions,
    record_runtime_telemetry, record_session, telemetry_summary, update_error_status,
)
from .story_bank import add_story, list_stories, show_story
from .study_context import build_study_context
from .sync import SKILLS, TARGETS, skills_are_synced, sync_skills
from .rubrics import list_rubrics, register_rubric
from .privacy import check_processing_permission
from .validation import validate_data

app = typer.Typer(no_args_is_help=True, help="Local CLI for IELTS AI Coach")
question_app = typer.Typer(no_args_is_help=True, help="Search and draw indexed IELTS questions")
session_app = typer.Typer(no_args_is_help=True, help="Create and complete structured practice sessions")
corpus_app = typer.Typer(no_args_is_help=True, help="Register and index user-owned corpora")
speaking_app = typer.Typer(no_args_is_help=True, help="Import structured speaking reports")
calibration_app = typer.Typer(no_args_is_help=True, help="Track model score calibration against authorised references")
error_app = typer.Typer(no_args_is_help=True, help="Inspect and update recurring error status")
story_app = typer.Typer(no_args_is_help=True, help="Manage reusable personal Speaking stories")
onboarding_app = typer.Typer(no_args_is_help=True, help="Inspect and complete first-use setup")
diagnostic_app = typer.Typer(no_args_is_help=True, help="Run a standardised Academic baseline diagnostic")
teaching_app = typer.Typer(no_args_is_help=True, help="Validate structured teaching feedback contracts")
rubric_app = typer.Typer(no_args_is_help=True, help="Manage official scoring rubric references")
privacy_app = typer.Typer(no_args_is_help=True, help="Check whether material may be sent for remote processing")
telemetry_app = typer.Typer(no_args_is_help=True, help="Record metadata-only cost and latency observations")
ui_app = typer.Typer(no_args_is_help=True, help="Run the optional local browser study desk")
conformance_app = typer.Typer(no_args_is_help=True, help="Inspect IELTS content contracts and eligibility")
content_app = typer.Typer(no_args_is_help=True, help="Inspect content readiness and staged local imports")
backup_app = typer.Typer(no_args_is_help=True, help="Create, verify and restore local IELTS_HOME backups")
benchmark_app = typer.Typer(no_args_is_help=True, help="Run isolated local performance benchmarks")
evaluation_app = typer.Typer(no_args_is_help=True, help="Evaluate Agent contracts and provider reliability")
app.add_typer(question_app, name="question")
app.add_typer(session_app, name="session")
app.add_typer(corpus_app, name="corpus")
app.add_typer(speaking_app, name="speaking")
app.add_typer(calibration_app, name="calibration")
app.add_typer(error_app, name="error")
app.add_typer(story_app, name="story")
app.add_typer(onboarding_app, name="onboarding")
app.add_typer(diagnostic_app, name="diagnostic")
app.add_typer(teaching_app, name="teaching")
app.add_typer(rubric_app, name="rubric")
app.add_typer(privacy_app, name="privacy")
app.add_typer(telemetry_app, name="telemetry")
app.add_typer(ui_app, name="ui")
app.add_typer(conformance_app, name="conformance")
app.add_typer(content_app, name="content")
app.add_typer(backup_app, name="backup")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(evaluation_app, name="evaluation")


@evaluation_app.command("contracts")
def evaluation_contracts_command(
    cases: Path = typer.Option(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Directory containing <contract>.valid.json and .invalid.json pairs",
    ),
    suite: str = typer.Option("agent-contract-regression"),
    home: Optional[Path] = typer.Option(None),
) -> None:
    """Run content-free contract regression cases and retain only hashes/outcomes."""
    result = run_contract_evaluation(
        resolve_home(home),
        cases,
        suite_name=suite,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "passed":
        raise typer.Exit(code=1)


@evaluation_app.command("reliability")
def evaluation_reliability_command(
    days: int = typer.Option(30, min=1, max=365),
    home: Optional[Path] = typer.Option(None),
) -> None:
    """Report metadata-only runtime reliability and release-gate status."""
    typer.echo(
        json.dumps(
            provider_reliability_report(resolve_home(home), days=days),
            ensure_ascii=False,
            indent=2,
        )
    )


@evaluation_app.command("history")
def evaluation_history_command(
    limit: int = typer.Option(20, min=1, max=100),
    home: Optional[Path] = typer.Option(None),
) -> None:
    """List recent local capability evaluation results."""
    typer.echo(
        json.dumps(
            list_capability_evaluations(resolve_home(home), limit=limit),
            ensure_ascii=False,
            indent=2,
        )
    )


@evaluation_app.command("release")
def evaluation_release_command(
    cases: Path = typer.Option(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Directory containing contract positive/negative cases",
    ),
    sessions: int = typer.Option(10_000, min=1, max=100_000),
    questions: int = typer.Option(100_000, min=1, max=1_000_000),
    repeats: int = typer.Option(5, min=1, max=20),
    home: Optional[Path] = typer.Option(None),
) -> None:
    """Run the deterministic contract and scale gates used before a release."""
    contract_report = run_contract_evaluation(
        resolve_home(home),
        cases,
        suite_name="release-contract-regression",
    )
    scale_report = run_temporary_scale_benchmark(
        session_count=sessions,
        question_count=questions,
        repeats=repeats,
    )
    result = {
        "status": (
            "passed"
            if contract_report["status"] == "passed" and scale_report["passed"]
            else "failed"
        ),
        "contract_gate": contract_report,
        "scale_gate": scale_report,
        "visual_review": "separate_human_decision_required",
    }
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "passed":
        raise typer.Exit(code=1)


@benchmark_app.command("scale")
def benchmark_scale_command(
    sessions: int = typer.Option(10_000, min=1, max=100_000),
    questions: int = typer.Option(100_000, min=1, max=1_000_000),
    repeats: int = typer.Option(5, min=1, max=20),
) -> None:
    """Benchmark synthetic sessions/questions in a temporary, disposable data home."""
    report = run_temporary_scale_benchmark(
        session_count=sessions,
        question_count=questions,
        repeats=repeats,
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise typer.Exit(code=1)


@backup_app.command("create")
def backup_create_command(
    home: Optional[Path] = typer.Option(None),
    kind: str = typer.Option("manual", help="Short reason recorded in the backup manifest"),
) -> None:
    """Create a verified local snapshot without including prior backups or runtime files."""
    result = create_backup(resolve_home(home), kind=kind)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@backup_app.command("list")
def backup_list_command(home: Optional[Path] = typer.Option(None)) -> None:
    """List backups stored under the current IELTS_HOME."""
    typer.echo(json.dumps(list_backups(resolve_home(home)), ensure_ascii=False, indent=2))


@backup_app.command("verify")
def backup_verify_command(
    backup: str = typer.Argument(..., help="Backup ID or absolute .zip path"),
    home: Optional[Path] = typer.Option(None),
) -> None:
    """Verify manifest hashes and SQLite integrity without restoring data."""
    typer.echo(json.dumps(verify_backup(resolve_home(home), backup), ensure_ascii=False, indent=2))


@backup_app.command("restore")
def backup_restore_command(
    backup: str = typer.Argument(..., help="Backup ID or absolute .zip path"),
    confirm: bool = typer.Option(False, "--confirm", help="Required destructive-action confirmation"),
    home: Optional[Path] = typer.Option(None),
) -> None:
    """Restore managed local data after validation and a pre-restore safety backup."""
    if not confirm:
        typer.echo("Restore was not started. Re-run with --confirm after stopping the Study Desk.", err=True)
        raise typer.Exit(code=2)
    result = restore_backup(resolve_home(home), backup, confirmed=True)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@content_app.command("requirements")
def content_requirements_command() -> None:
    """Print the adjustable high-quality content inventory targets."""
    typer.echo(json.dumps(content_requirements(), ensure_ascii=False, indent=2))


@content_app.command("readiness")
def content_readiness_command(home: Optional[Path] = typer.Option(None)) -> None:
    """Compare the local corpus with the inventory targets."""
    typer.echo(json.dumps(build_content_readiness(resolve_home(home)), ensure_ascii=False, indent=2))


@content_app.command("imports")
def content_imports_command(home: Optional[Path] = typer.Option(None)) -> None:
    """List files staged through the local content workbench."""
    typer.echo(json.dumps(list_content_imports(resolve_home(home)), ensure_ascii=False, indent=2))


@content_app.command("process")
def content_process_command(
    import_id: str,
    home: Optional[Path] = typer.Option(None),
) -> None:
    """Validate and import a staged manifest/JSONL package."""
    typer.echo(json.dumps(process_import(resolve_home(home), import_id), ensure_ascii=False, indent=2))


@conformance_app.command("standard")
def conformance_standard() -> None:
    """Print the pinned IELTS Academic standard profile used by this build."""
    typer.echo(json.dumps(standard_profile(), ensure_ascii=False, indent=2))


@conformance_app.command("question")
def conformance_question(
    question_id: str,
    home: Optional[Path] = typer.Option(None),
) -> None:
    """Re-assess an indexed question without changing it."""
    question = show_question(resolve_home(home), question_id, include_answer=True)
    typer.echo(json.dumps(assess_question(question), ensure_ascii=False, indent=2))


@conformance_app.command("pack")
def conformance_pack(path: Path) -> None:
    """Validate an assessment-pack JSON or YAML file before import."""
    payload = load_data_file(path)
    validate_data(payload, "assessment-pack")
    report = assess_pack(payload)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == "rejected":
        raise typer.Exit(code=2)


@ui_app.command("start")
def ui_start(
    home: Optional[Path] = typer.Option(None),
    port: int = typer.Option(0, min=0, max=65535),
    no_open: bool = typer.Option(False, help="Print the URL without opening a browser"),
) -> None:
    """Start the token-protected local Study Desk on 127.0.0.1."""
    try:
        from .web.server import serve_ui
    except ImportError as exc:
        typer.echo('UI dependencies are missing. Install with: pip install -e ".[ui]"', err=True)
        raise typer.Exit(code=1) from exc
    try:
        serve_ui(resolve_home(home), port=port, open_browser=not no_open)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@ui_app.command("open")
def ui_open(
    home: Optional[Path] = typer.Option(None),
    port: int = typer.Option(0, min=0, max=65535),
    no_open: bool = typer.Option(False, help="Start or reuse the service without opening a browser"),
) -> None:
    """Start or reuse the background Study Desk and open a fresh authenticated tab."""
    try:
        from .web.server import open_ui

        url = open_ui(resolve_home(home), port=port, open_browser=not no_open)
        typer.echo(f"IELTS Study Desk ready: {url}")
    except (ImportError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@ui_app.command("stop")
def ui_stop(home: Optional[Path] = typer.Option(None)) -> None:
    """Stop the background Study Desk for this IELTS_HOME."""
    from .web.server import stop_ui

    typer.echo("Stopping IELTS Study Desk." if stop_ui(resolve_home(home)) else "IELTS Study Desk is not running.")


@ui_app.command("status")
def ui_status_command(home: Optional[Path] = typer.Option(None)) -> None:
    """Show whether the background Study Desk is running."""
    from .web.server import ui_status

    typer.echo(json.dumps(ui_status(resolve_home(home)), ensure_ascii=False, indent=2))


@ui_app.command("shortcut-install")
def ui_shortcut_install(home: Optional[Path] = typer.Option(None)) -> None:
    """Install a Windows desktop shortcut that starts or reopens the Study Desk."""
    try:
        from .web.shortcut import install_desktop_shortcut

        path = install_desktop_shortcut(resolve_home(home))
        typer.echo(f"Desktop shortcut installed: {path}")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@ui_app.command("shortcut-remove")
def ui_shortcut_remove() -> None:
    """Remove the Windows desktop Study Desk shortcut."""
    try:
        from .web.shortcut import remove_desktop_shortcut

        path = remove_desktop_shortcut()
        typer.echo(f"Desktop shortcut removed: {path}" if path else "Desktop shortcut was not installed.")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def init(home: Optional[Path] = typer.Option(None), force: bool = typer.Option(False)) -> None:
    target = resolve_home(home)
    initialise_home(target, force=force)
    typer.echo(f"Initialised IELTS_HOME: {target}")


@app.command("sync-skills")
def sync_skills_command(project_root: Optional[Path] = typer.Option(None)) -> None:
    root = project_root.resolve() if project_root else find_project_root()
    for path in sync_skills(root):
        typer.echo(f"Synced: {path}")


@app.command()
def doctor(home: Optional[Path] = typer.Option(None), project_root: Optional[Path] = typer.Option(None)) -> None:
    target = resolve_home(home)
    root = project_root.resolve() if project_root else find_project_root()
    try:
        installed_version = version("ielts-ai-coach")
    except PackageNotFoundError:
        installed_version = None
    checks = {
        "IELTS_HOME exists": target.exists(),
        f"installed package matches source ({__version__})": installed_version == __version__,
        "profile.yaml valid": False,
        "settings.yaml": (target / "config" / "settings.yaml").exists(),
        "SQLite database": db_path(target).exists(),
        "question bank directory": (target / "corpus").exists(),
        "seven source skills": all((root / "skills-source" / skill / "SKILL.md").exists() for skill in SKILLS),
        "Claude skills synced": skills_are_synced(root, TARGETS[0]),
        "Codex skills synced": skills_are_synced(root, TARGETS[1]),
        "OpenCode skills synced": skills_are_synced(root, TARGETS[2]),
    }
    try:
        profile = load_profile(target)
        checks["profile.yaml valid"] = True
    except Exception as exc:  # pragma: no cover - diagnostic output
        profile = None
        typer.echo(f"Profile validation error: {exc}")
    question_count = 0
    starter_questions = 0
    starter_reading_questions = 0
    starter_reading_passages = 0
    starter_listening_items = 0
    required_tables = {
        "sessions", "errors", "corpora", "question_passages", "questions",
        "question_options", "question_attempts", "reading_answers", "writing_versions",
        "criterion_scores", "speaking_reports", "allocation_history", "calibration_results",
        "calibration_cases", "diagnostic_runs", "schema_meta",
        "rubric_registry", "runtime_events", "runtime_telemetry",
        "study_drafts", "idempotency_records", "media_assets", "agent_runs",
        "agent_run_events", "ui_settings", "listening_items",
        "assessment_packs",
        "content_import_jobs", "content_import_files",
        "content_reviews",
        "assessment_runs", "section_runs", "question_responses",
        "coaching_artifacts",
    }
    if db_path(target).exists():
        with connect(target) as conn:
            tables = {
                row["name"] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            question_count = int(conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0])
            starter_questions = int(conn.execute(
                "SELECT COUNT(*) FROM questions WHERE corpus_id='ielts-ai-coach-starter'"
            ).fetchone()[0])
            starter_reading_questions = int(conn.execute(
                "SELECT COUNT(*) FROM questions WHERE corpus_id='ielts-ai-coach-starter' AND module='reading'"
            ).fetchone()[0])
            starter_reading_passages = int(conn.execute(
                "SELECT COUNT(*) FROM question_passages WHERE corpus_id='ielts-ai-coach-starter'"
            ).fetchone()[0])
            starter_listening_items = int(conn.execute(
                "SELECT COUNT(*) FROM listening_items WHERE source_type='project_original'"
            ).fetchone()[0])
            schema_row = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone() if "schema_meta" in tables else None
            rubric_count = int(conn.execute("SELECT COUNT(*) FROM rubric_registry").fetchone()[0])
        checks[f"database schema v{SCHEMA_VERSION}"] = (
            required_tables.issubset(tables)
            and schema_row is not None
            and schema_row["value"] == str(SCHEMA_VERSION)
        )
        checks["official rubric references registered"] = rubric_count >= 2
        demo_content_present = bool(
            starter_questions
            or starter_reading_passages
            or starter_listening_items
            or (target / "corpus" / "starter-open" / "manifest.yaml").exists()
        )
        if demo_content_present:
            checks["optional demo corpus is internally complete"] = (
                starter_questions == 61
                and starter_reading_passages == 4
                and starter_reading_questions == 16
                and starter_listening_items == 50
            )
        else:
            checks["public install has no bundled question bank"] = True
        health = audit_data_home(target)
        checks["cross-store consistency"] = health["status"] != "failed"
    failed = False
    typer.echo(f"IELTS_HOME: {target}")
    for label, ok in checks.items():
        typer.echo(f"[{'OK' if ok else 'FAIL'}] {label}")
        failed = failed or not ok
    typer.echo(f"Indexed questions: {question_count}")
    if profile:
        typer.echo(f"Target overall: {profile['target']['overall']}")
    if failed:
        raise typer.Exit(code=1)


@app.command()
def record(session_file: Path = typer.Argument(..., exists=True, readable=True), home: Optional[Path] = typer.Option(None)) -> None:
    data = load_session_file(session_file)
    record_session(resolve_home(home), data)
    typer.echo(f"Recorded session: {data['session_id']}")


@app.command()
def summary(days: int = typer.Option(14, min=1), home: Optional[Path] = typer.Option(None)) -> None:
    typer.echo(build_summary(resolve_home(home), days), nl=False)


@app.command("study-context")
def study_context_command(
    module: Optional[str] = typer.Option(None, help="Optional direct module intent"),
    days: int = typer.Option(14, min=1, max=365),
    pretty: bool = typer.Option(False, help="Pretty-print JSON for human inspection"),
    home: Optional[Path] = typer.Option(None),
) -> None:
    """Emit one compact, read-only context payload for an Agent study turn."""
    try:
        context = build_study_context(resolve_home(home), module=module, days=days)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        json.dumps(
            context,
            ensure_ascii=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
        )
    )


@app.command()
def allocation(home: Optional[Path] = typer.Option(None), save: bool = typer.Option(True, help="Persist this recommendation")) -> None:
    result = recommend_allocation(resolve_home(home), persist=save)
    typer.echo("Recommended allocation:")
    for module, value in result.allocation.items():
        avg = result.recent_average[module]
        avg_text = "n/a" if avg is None else f"{avg:.2f}"
        typer.echo(f"- {module}: {value * 100:.0f}% (recent avg: {avg_text})")
    typer.echo("Reasons:")
    for reason in result.reasons:
        typer.echo(f"- {reason}")


@app.command("weekly-report")
def weekly_report(output: Optional[Path] = typer.Option(None), home: Optional[Path] = typer.Option(None)) -> None:
    report = build_weekly_report(resolve_home(home))
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        typer.echo(f"Written: {output}")
    else:
        typer.echo(report, nl=False)


@app.command("trends")
def trends(home: Optional[Path] = typer.Option(None), limit: int = typer.Option(10, min=2, max=100)) -> None:
    typer.echo(build_trend_report(resolve_home(home), limit=limit), nl=False)


@app.command("learning-profile")
def learning_profile(home: Optional[Path] = typer.Option(None), output: Optional[Path] = typer.Option(None)) -> None:
    report = build_learning_profile(resolve_home(home))
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        typer.echo(f"Written: {output}")
    else:
        typer.echo(report, nl=False)


# Backwards-compatible flat corpus commands.
@app.command("corpus-import")
def corpus_import_legacy(manifest_file: Path = typer.Argument(..., exists=True, readable=True), home: Optional[Path] = typer.Option(None)) -> None:
    result = import_manifest(resolve_home(home), manifest_file)
    typer.echo(f"Imported corpus: {result['manifest']['corpus_id']} | indexed {result['index']['questions']} questions")


@app.command("corpus-list")
def corpus_list_legacy(home: Optional[Path] = typer.Option(None)) -> None:
    _print_corpora(resolve_home(home))


def _print_corpora(home: Path) -> None:
    rows = list_corpora(home)
    if not rows:
        typer.echo("No corpus manifests registered.")
        return
    for row in rows:
        path = row["local_path"] or "bundled/index-only"
        typer.echo(f"- {row['corpus_id']} | {row['source_type']} | {row['title']} | {path}")


@corpus_app.command("import")
def corpus_import(manifest_file: Path = typer.Argument(..., exists=True, readable=True), home: Optional[Path] = typer.Option(None), no_index: bool = typer.Option(False), force: bool = typer.Option(False)) -> None:
    result = import_manifest(resolve_home(home), manifest_file, index=not no_index, force=force)
    idx = result["index"]
    typer.echo(
        f"Imported {result['manifest']['corpus_id']}: passages={idx['passages']}, questions={idx['questions']}, duplicates={idx['duplicates']}"
    )


@corpus_app.command("list")
def corpus_list(home: Optional[Path] = typer.Option(None)) -> None:
    _print_corpora(resolve_home(home))


@corpus_app.command("reindex")
def corpus_reindex(corpus_id: str, home: Optional[Path] = typer.Option(None), force: bool = typer.Option(False)) -> None:
    result = reindex_corpus(resolve_home(home), corpus_id, force=force)
    typer.echo(f"Reindexed {corpus_id}: passages={result['passages']}, questions={result['questions']}, duplicates={result['duplicates']}")


@corpus_app.command("stats")
def corpus_stats_command(corpus_id: Optional[str] = typer.Option(None), home: Optional[Path] = typer.Option(None)) -> None:
    rows = corpus_stats(resolve_home(home), corpus_id=corpus_id)
    if not rows:
        typer.echo("No indexed questions.")
        return
    for row in rows:
        typer.echo(f"- {row['corpus_id']} | {row['module']} | questions={row['questions']} | passages={row['passages']} | types={row['question_types']}")


@question_app.command("list")
def question_list(
    module: Optional[str] = typer.Option(None), task: Optional[str] = typer.Option(None),
    question_type: Optional[str] = typer.Option(None, "--type"), topic: Optional[str] = typer.Option(None),
    source_type: Optional[str] = typer.Option(None), corpus_id: Optional[str] = typer.Option(None),
    passage_id: Optional[str] = typer.Option(None),
    exclude_completed: bool = typer.Option(False), limit: int = typer.Option(50, min=1, max=1000),
    home: Optional[Path] = typer.Option(None),
) -> None:
    rows = search_questions(
        resolve_home(home), module=module, task=task, question_type=question_type, topic=topic,
        source_type=source_type, corpus_id=corpus_id, passage_id=passage_id,
        exclude_completed=exclude_completed, limit=limit,
    )
    for row in rows:
        typer.echo(f"- {row['question_id']} | {row['module']} | {row.get('question_type') or '-'} | {row['content'][:100]}")
    typer.echo(f"Total: {len(rows)}")


@question_app.command("search")
def question_search(
    query: str = typer.Argument(...), module: Optional[str] = typer.Option(None),
    question_type: Optional[str] = typer.Option(None, "--type"), topic: Optional[str] = typer.Option(None),
    exclude_completed: bool = typer.Option(False), limit: int = typer.Option(50),
    home: Optional[Path] = typer.Option(None),
) -> None:
    rows = search_questions(resolve_home(home), query=query, module=module, question_type=question_type, topic=topic, exclude_completed=exclude_completed, limit=limit)
    for row in rows:
        typer.echo(f"- {row['question_id']} | {row['module']} | {row['content'][:120]}")
    typer.echo(f"Total: {len(rows)}")


@question_app.command("show")
def question_show(question_id: str = typer.Argument(...), with_answer: bool = typer.Option(False), home: Optional[Path] = typer.Option(None)) -> None:
    question = show_question(resolve_home(home), question_id, include_answer=with_answer)
    if not question:
        raise typer.BadParameter(f"Unknown question: {question_id}")
    typer.echo(json.dumps(question, ensure_ascii=False, indent=2))


@question_app.command("set")
def question_set(
    passage_id: str = typer.Argument(...),
    with_answers: bool = typer.Option(False),
    home: Optional[Path] = typer.Option(None),
) -> None:
    result = show_reading_set(resolve_home(home), passage_id, include_answers=with_answers)
    if not result:
        raise typer.BadParameter(f"Unknown Reading passage or no indexed questions: {passage_id}")
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@question_app.command("draw")
def question_draw(
    module: Optional[str] = typer.Option(None), task: Optional[str] = typer.Option(None),
    question_type: Optional[str] = typer.Option(None, "--type"), topic: Optional[str] = typer.Option(None),
    source_type: Optional[str] = typer.Option(None), corpus_id: Optional[str] = typer.Option(None),
    exclude_completed: bool = typer.Option(True), seed: Optional[int] = typer.Option(None),
    home: Optional[Path] = typer.Option(None),
) -> None:
    question = draw_question(
        resolve_home(home), seed=seed, module=module, task=task, question_type=question_type,
        topic=topic, source_type=source_type, corpus_id=corpus_id, exclude_completed=exclude_completed,
    )
    if not question:
        typer.echo("No matching question found.")
        raise typer.Exit(code=1)
    typer.echo(json.dumps(question, ensure_ascii=False, indent=2))


@session_app.command("start")
def session_start(
    module: str = typer.Argument(...), question_id: Optional[str] = typer.Option(None),
    source_id: Optional[str] = typer.Option(None), passage_id: Optional[str] = typer.Option(None),
    mode: Optional[str] = typer.Option(None),
    time_limit_minutes: Optional[float] = typer.Option(None, min=1),
    home: Optional[Path] = typer.Option(None),
) -> None:
    path = start_session(
        resolve_home(home), module, question_id=question_id, source_id=source_id,
        passage_id=passage_id, mode=mode, time_limit_minutes=time_limit_minutes,
    )
    typer.echo(f"Created draft: {path}")


@session_app.command("finish")
def session_finish(session_file: Path = typer.Argument(..., exists=True, readable=True), home: Optional[Path] = typer.Option(None)) -> None:
    data = finish_session(resolve_home(home), session_file)
    typer.echo(f"Completed and recorded: {data['session_id']}")


@session_app.command("transition")
def session_transition(
    session_file: Path = typer.Argument(..., exists=True, readable=True),
    status: str = typer.Argument(...),
    home: Optional[Path] = typer.Option(None),
) -> None:
    data = transition_session(resolve_home(home), session_file, status)
    typer.echo(f"Session {data['session_id']}: {data['status']}")


@session_app.command("show")
def session_show(session_id: str, home: Optional[Path] = typer.Option(None)) -> None:
    data = show_session(resolve_home(home), session_id)
    if not data:
        raise typer.BadParameter(f"Unknown session: {session_id}")
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


@session_app.command("list")
def session_list(module: Optional[str] = typer.Option(None), limit: int = typer.Option(50), home: Optional[Path] = typer.Option(None)) -> None:
    for row in list_sessions(resolve_home(home), module=module, limit=limit):
        typer.echo(
            f"- {row['session_id']} | {row['module']} | {row['status']} | "
            f"band={row['band']} | kind={row['score_kind'] or 'unspecified'} | "
            f"confidence={row['score_confidence'] or 'n/a'} | {row['occurred_at']}"
        )


@session_app.command("resume")
def session_resume(
    module: Optional[str] = typer.Option(None),
    home: Optional[Path] = typer.Option(None),
) -> None:
    data = resume_session(resolve_home(home), module=module)
    if not data:
        typer.echo("No active Session found.")
        raise typer.Exit(code=1)
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


@session_app.command("reconcile")
def session_reconcile(
    session_id: str,
    prefer: str = typer.Option(
        "auto",
        help="auto chooses the higher revision; equal-revision forks require markdown or sqlite",
    ),
    home: Optional[Path] = typer.Option(None),
) -> None:
    data = reconcile_session(resolve_home(home), session_id, prefer=prefer)
    typer.echo(
        json.dumps(
            {
                "session_id": data["session_id"],
                "revision": data.get("revision", 0),
                "reconciled_from": prefer,
            },
            ensure_ascii=False,
        )
    )


@session_app.command("submit-writing")
def session_submit_writing(
    session_id: str,
    content_file: Path = typer.Argument(..., exists=True, readable=True),
    label: str = typer.Option("v1", help="v1, v2, or final"),
    expected_revision: Optional[int] = typer.Option(None, min=0),
    home: Optional[Path] = typer.Option(None),
) -> None:
    data = submit_writing_version(
        resolve_home(home), session_id, label=label,
        content=content_file.read_text(encoding="utf-8"), expected_revision=expected_revision,
    )
    typer.echo(json.dumps({"session_id": session_id, "status": data["status"], "revision": data["revision"]}))


@session_app.command("apply-writing-review")
def session_apply_writing_review(
    session_id: str,
    review_file: Path = typer.Argument(..., exists=True, readable=True),
    expected_revision: Optional[int] = typer.Option(None, min=0),
    home: Optional[Path] = typer.Option(None),
) -> None:
    data = apply_writing_review(
        resolve_home(home), session_id, load_data_file(review_file),
        expected_revision=expected_revision,
    )
    typer.echo(json.dumps({"session_id": session_id, "status": data["status"], "revision": data["revision"]}))


@session_app.command("hint-reading")
def session_hint_reading(
    session_id: str,
    level: Optional[int] = typer.Option(None, min=1, max=3),
    expected_revision: Optional[int] = typer.Option(None, min=0),
    home: Optional[Path] = typer.Option(None),
) -> None:
    data = record_reading_hint(
        resolve_home(home), session_id, level=level, expected_revision=expected_revision
    )
    typer.echo(json.dumps({"session_id": session_id, "hint_level": data["hints_used"], "revision": data["revision"]}))


@session_app.command("submit-reading")
def session_submit_reading(
    session_id: str,
    answers_file: Path = typer.Argument(..., exists=True, readable=True),
    expected_revision: Optional[int] = typer.Option(None, min=0),
    home: Optional[Path] = typer.Option(None),
) -> None:
    payload = load_data_file(answers_file)
    answers = payload.get("answers", payload.get("questions"))
    if not isinstance(answers, list):
        raise typer.BadParameter("Reading submission file requires an answers list")
    data = submit_reading_answers(
        resolve_home(home), session_id, answers, expected_revision=expected_revision
    )
    typer.echo(json.dumps({"session_id": session_id, "status": data["status"], "revision": data["revision"]}))


@session_app.command("apply-reading-review")
def session_apply_reading_review(
    session_id: str,
    review_file: Path = typer.Argument(..., exists=True, readable=True),
    expected_revision: Optional[int] = typer.Option(None, min=0),
    home: Optional[Path] = typer.Option(None),
) -> None:
    data = apply_reading_review(
        resolve_home(home), session_id, load_data_file(review_file),
        expected_revision=expected_revision,
    )
    typer.echo(json.dumps({"session_id": session_id, "status": data["status"], "revision": data["revision"]}))


@teaching_app.command("validate-writing")
def teaching_validate_writing(
    review_file: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    data = validate_data(load_data_file(review_file), "writing-review")
    typer.echo(f"Valid Writing review: {data['session_id']} | {data['stage']}")


@teaching_app.command("validate-reading")
def teaching_validate_reading(
    review_file: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    data = validate_data(load_data_file(review_file), "reading-review")
    typer.echo(f"Valid Reading review: {data['session_id']} | {data['mode']}")


@rubric_app.command("register")
def rubric_register(
    manifest_file: Path = typer.Argument(..., exists=True, readable=True),
    home: Optional[Path] = typer.Option(None),
) -> None:
    data = register_rubric(resolve_home(home), load_data_file(manifest_file))
    typer.echo(f"Registered rubric: {data['rubric_id']} | {data['availability']}")


@rubric_app.command("list")
def rubric_list(home: Optional[Path] = typer.Option(None)) -> None:
    for row in list_rubrics(resolve_home(home)):
        typer.echo(
            f"- {row['rubric_id']} | {row['module']} | {row['availability']} | "
            f"{row['source_reference']}"
        )


@privacy_app.command("check")
def privacy_check(
    remote: bool = typer.Option(False, help="The selected model processes content remotely"),
    consent: bool = typer.Option(False, help="Explicit one-time consent for this operation"),
    source_type: Optional[str] = typer.Option(None),
    question_id: Optional[str] = typer.Option(None),
    corpus_id: Optional[str] = typer.Option(None),
    home: Optional[Path] = typer.Option(None),
) -> None:
    result = check_processing_permission(
        resolve_home(home), remote_processing=remote, explicit_consent=consent,
        source_type=source_type, question_id=question_id, corpus_id=corpus_id,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["allowed"]:
        raise typer.Exit(code=2)


@telemetry_app.command("record")
def telemetry_record(
    event_file: Path = typer.Argument(..., exists=True, readable=True),
    home: Optional[Path] = typer.Option(None),
) -> None:
    record_runtime_telemetry(resolve_home(home), load_data_file(event_file))
    typer.echo("Recorded metadata-only telemetry event.")


@telemetry_app.command("summary")
def telemetry_summary_command(
    days: int = typer.Option(30, min=1, max=3650),
    home: Optional[Path] = typer.Option(None),
) -> None:
    rows = telemetry_summary(resolve_home(home), days=days)
    if not rows:
        typer.echo("No telemetry recorded.")
        return
    for row in rows:
        typer.echo(
            f"- {row['module']} | events={row['events']} | in={row['input_tokens']} | "
            f"out={row['output_tokens']} | avg_ms={row['average_latency_ms']} | tools={row['tool_calls']}"
        )


@speaking_app.command("import-report")
def speaking_import_report(report_file: Path = typer.Argument(..., exists=True, readable=True), home: Optional[Path] = typer.Option(None)) -> None:
    data = import_speaking_report(resolve_home(home), report_file)
    typer.echo(f"Imported speaking report: {data['session_id']}")


@onboarding_app.command("status")
def onboarding_status_command(home: Optional[Path] = typer.Option(None)) -> None:
    typer.echo(json.dumps(onboarding_status(resolve_home(home)), ensure_ascii=False, indent=2))


@onboarding_app.command("complete")
def onboarding_complete_command(
    setup_file: Optional[Path] = typer.Option(
        None, "--setup-file", exists=True, readable=True,
        help="Optional YAML/JSON mapping with confirmed goal, baseline and preference updates.",
    ),
    home: Optional[Path] = typer.Option(None),
) -> None:
    updates = load_data_file(setup_file) if setup_file else None
    result = complete_onboarding(resolve_home(home), updates)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@diagnostic_app.command("start")
def diagnostic_start_command(
    mode: str = typer.Option("quick", help="quick or full"),
    home: Optional[Path] = typer.Option(None),
) -> None:
    typer.echo(json.dumps(start_diagnostic(resolve_home(home), mode), ensure_ascii=False, indent=2))


@diagnostic_app.command("attach")
def diagnostic_attach_command(
    diagnostic_id: str = typer.Argument(...),
    session_id: str = typer.Argument(...),
    home: Optional[Path] = typer.Option(None),
) -> None:
    result = attach_diagnostic_session(resolve_home(home), diagnostic_id, session_id)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@diagnostic_app.command("status")
def diagnostic_status_command(
    diagnostic_id: Optional[str] = typer.Argument(None),
    home: Optional[Path] = typer.Option(None),
) -> None:
    typer.echo(json.dumps(diagnostic_status(resolve_home(home), diagnostic_id), ensure_ascii=False, indent=2))


@diagnostic_app.command("complete")
def diagnostic_complete_command(
    diagnostic_id: str = typer.Argument(...),
    home: Optional[Path] = typer.Option(None),
) -> None:
    result = complete_diagnostic(resolve_home(home), diagnostic_id)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@diagnostic_app.command("cancel")
def diagnostic_cancel_command(
    diagnostic_id: str = typer.Argument(...),
    home: Optional[Path] = typer.Option(None),
) -> None:
    result = cancel_diagnostic(resolve_home(home), diagnostic_id)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@calibration_app.command("record")
def calibration_record(record_file: Path = typer.Argument(..., exists=True, readable=True), home: Optional[Path] = typer.Option(None)) -> None:
    record_calibration(resolve_home(home), load_data_file(record_file))
    typer.echo(f"Recorded calibration case from: {record_file}")


@calibration_app.command("case-import")
def calibration_case_import(
    case_file: Path = typer.Argument(..., exists=True, readable=True),
    home: Optional[Path] = typer.Option(None),
) -> None:
    result = import_calibration_case(
        resolve_home(home), load_data_file(case_file), base_path=case_file.parent
    )
    typer.echo(f"Imported calibration case: {result['case_id']}")


@calibration_app.command("case-list")
def calibration_case_list(home: Optional[Path] = typer.Option(None)) -> None:
    rows = list_calibration_cases(resolve_home(home))
    if not rows:
        typer.echo("No calibration cases registered.")
        return
    for row in rows:
        typer.echo(
            f"- {row['case_id']} | {row['module']} | {row.get('task') or '-'} | "
            f"{row['criterion']} | {row['input_path']}"
        )


@calibration_app.command("prepare")
def calibration_prepare(
    model: str = typer.Option(..., help="Model/client label used for this blind run"),
    output: Path = typer.Option(..., help="Write a blind scoring worksheet here"),
    home: Optional[Path] = typer.Option(None),
) -> None:
    run = prepare_calibration_run(resolve_home(home), model, output)
    typer.echo(f"Prepared {len(run['predictions'])} blind calibration cases: {output}")


@calibration_app.command("import-run")
def calibration_import_run(
    run_file: Path = typer.Argument(..., exists=True, readable=True),
    tolerance: float = typer.Option(0.5, min=0.0, max=2.0),
    home: Optional[Path] = typer.Option(None),
) -> None:
    count = import_calibration_run(
        resolve_home(home), load_data_file(run_file), tolerance=tolerance
    )
    typer.echo(f"Imported {count} calibration predictions from: {run_file}")


@calibration_app.command("report")
def calibration_report_command(home: Optional[Path] = typer.Option(None)) -> None:
    typer.echo(calibration_report(resolve_home(home)), nl=False)


@error_app.command("list")
def error_list(status: Optional[str] = typer.Option(None), limit: int = typer.Option(100), home: Optional[Path] = typer.Option(None)) -> None:
    rows = list_error_profile(resolve_home(home), status=status, limit=limit)
    if not rows:
        typer.echo("No matching error tags.")
        return
    for row in rows:
        typer.echo(f"- {row['tag']} | {row['status']} | count={row['total']} | sessions={row['sessions']} | last={row['last_seen']}")


@error_app.command("set-status")
def error_set_status(tag: str, status: str = typer.Argument(...), home: Optional[Path] = typer.Option(None)) -> None:
    count = update_error_status(resolve_home(home), tag, status)
    typer.echo(f"Updated {count} records for {tag} -> {status}")


@story_app.command("add")
def story_add(story_file: Path = typer.Argument(..., exists=True, readable=True), home: Optional[Path] = typer.Option(None)) -> None:
    data = add_story(resolve_home(home), story_file)
    typer.echo(f"Added story: {data['story_id']}")


@story_app.command("list")
def story_list(home: Optional[Path] = typer.Option(None)) -> None:
    rows = list_stories(resolve_home(home))
    if not rows:
        typer.echo("No personal stories saved.")
        return
    for row in rows:
        typer.echo(f"- {row['story_id']} | {row['title']} | topics={', '.join(row.get('usable_topics', []))}")


@story_app.command("show")
def story_show(story_id: str, home: Optional[Path] = typer.Option(None)) -> None:
    data = show_story(resolve_home(home), story_id)
    if not data:
        raise typer.BadParameter(f"Unknown story: {story_id}")
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
