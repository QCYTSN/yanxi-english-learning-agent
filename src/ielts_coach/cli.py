from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Optional

import typer

from .allocation import recommend_allocation
from . import __version__
from .calibration import calibration_report, record_calibration
from .config import load_profile
from .corpus import corpus_stats, import_manifest, reindex_corpus
from .init_home import initialise_home
from .paths import find_project_root, resolve_home
from .profiles import build_learning_profile
from .question_bank import draw_question, search_questions, show_question
from .reports import build_summary, build_trend_report, build_weekly_report
from .session_io import load_data_file, load_session_file
from .session_manager import finish_session, show_session, start_session
from .speaking_io import import_speaking_report
from .storage import connect, db_path, list_corpora, list_error_profile, list_sessions, record_session, update_error_status
from .story_bank import add_story, list_stories, show_story
from .sync import SKILLS, TARGETS, skills_are_synced, sync_skills

app = typer.Typer(no_args_is_help=True, help="Local CLI for IELTS AI Coach")
question_app = typer.Typer(no_args_is_help=True, help="Search and draw indexed IELTS questions")
session_app = typer.Typer(no_args_is_help=True, help="Create and complete structured practice sessions")
corpus_app = typer.Typer(no_args_is_help=True, help="Register and index user-owned corpora")
speaking_app = typer.Typer(no_args_is_help=True, help="Import structured speaking reports")
calibration_app = typer.Typer(no_args_is_help=True, help="Track model score calibration against authorised references")
error_app = typer.Typer(no_args_is_help=True, help="Inspect and update recurring error status")
story_app = typer.Typer(no_args_is_help=True, help="Manage reusable personal Speaking stories")
app.add_typer(question_app, name="question")
app.add_typer(session_app, name="session")
app.add_typer(corpus_app, name="corpus")
app.add_typer(speaking_app, name="speaking")
app.add_typer(calibration_app, name="calibration")
app.add_typer(error_app, name="error")
app.add_typer(story_app, name="story")


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
        "starter corpus": (target / "corpus" / "starter-open" / "manifest.yaml").exists(),
        "six source skills": all((root / "skills-source" / skill / "SKILL.md").exists() for skill in SKILLS),
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
    required_tables = {
        "sessions", "errors", "corpora", "question_passages", "questions",
        "question_options", "question_attempts", "reading_answers", "writing_versions",
        "criterion_scores", "speaking_reports", "allocation_history", "calibration_results",
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
        checks["V0.2 database tables"] = required_tables.issubset(tables)
        checks["starter corpus indexed (41 questions)"] = starter_questions == 41
        checks["starter Reading indexed (4 passages / 16 questions)"] = (
            starter_reading_passages == 4 and starter_reading_questions == 16
        )
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
    exclude_completed: bool = typer.Option(False), limit: int = typer.Option(50, min=1, max=1000),
    home: Optional[Path] = typer.Option(None),
) -> None:
    rows = search_questions(
        resolve_home(home), module=module, task=task, question_type=question_type, topic=topic,
        source_type=source_type, corpus_id=corpus_id, exclude_completed=exclude_completed, limit=limit,
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
    source_id: Optional[str] = typer.Option(None), mode: Optional[str] = typer.Option(None),
    home: Optional[Path] = typer.Option(None),
) -> None:
    path = start_session(resolve_home(home), module, question_id=question_id, source_id=source_id, mode=mode)
    typer.echo(f"Created draft: {path}")


@session_app.command("finish")
def session_finish(session_file: Path = typer.Argument(..., exists=True, readable=True), home: Optional[Path] = typer.Option(None)) -> None:
    data = finish_session(resolve_home(home), session_file)
    typer.echo(f"Completed and recorded: {data['session_id']}")


@session_app.command("show")
def session_show(session_id: str, home: Optional[Path] = typer.Option(None)) -> None:
    data = show_session(resolve_home(home), session_id)
    if not data:
        raise typer.BadParameter(f"Unknown session: {session_id}")
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


@session_app.command("list")
def session_list(module: Optional[str] = typer.Option(None), limit: int = typer.Option(50), home: Optional[Path] = typer.Option(None)) -> None:
    for row in list_sessions(resolve_home(home), module=module, limit=limit):
        typer.echo(f"- {row['session_id']} | {row['module']} | {row['status']} | band={row['band']} | {row['occurred_at']}")


@speaking_app.command("import-report")
def speaking_import_report(report_file: Path = typer.Argument(..., exists=True, readable=True), home: Optional[Path] = typer.Option(None)) -> None:
    data = import_speaking_report(resolve_home(home), report_file)
    typer.echo(f"Imported speaking report: {data['session_id']}")


@calibration_app.command("record")
def calibration_record(record_file: Path = typer.Argument(..., exists=True, readable=True), home: Optional[Path] = typer.Option(None)) -> None:
    record_calibration(resolve_home(home), load_data_file(record_file))
    typer.echo(f"Recorded calibration case from: {record_file}")


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
