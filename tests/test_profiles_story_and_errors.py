from pathlib import Path

from ielts_coach.corpus import corpus_stats, reindex_corpus
from ielts_coach.init_home import initialise_home
from ielts_coach.storage import list_error_profile, record_session, update_error_status
from ielts_coach.story_bank import add_story, list_stories


def test_error_lifecycle_story_bank_and_reindex(tmp_path: Path):
    home = tmp_path / "home"
    initialise_home(home)
    record_session(home, {
        "session_id": "W-20260722-020",
        "module": "writing",
        "status": "completed",
        "errors": [{"tag": "GRA_ARTICLE", "count": 2}],
    })
    assert list_error_profile(home, status="active")[0]["tag"] == "GRA_ARTICLE"
    assert update_error_status(home, "GRA_ARTICLE", "resolved") == 1
    assert list_error_profile(home, status="resolved")[0]["total"] == 2

    story = tmp_path / "story.yaml"
    story.write_text(
        "story_id: project-story\ntitle: A difficult project\nevents: [solved a problem]\nusable_topics: [project, challenge]\n",
        encoding="utf-8",
    )
    add_story(home, story)
    assert list_stories(home)[0]["story_id"] == "project-story"

    result = reindex_corpus(home, "ielts-ai-coach-starter")
    assert result["questions"] >= 40
    stats = corpus_stats(home, "ielts-ai-coach-starter")
    assert any(row["module"] == "reading" for row in stats)
