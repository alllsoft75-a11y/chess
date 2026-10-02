import os
from pathlib import Path

import pytest

from app import storage
from app.models import ExperienceEpisode
from app.personalities import list_personalities
from app.storage import learn_from_experience, list_learned_rules, record_experience
from app.tournament import _technical_result


@pytest.fixture(autouse=True)
def temporary_database(tmp_path: Path):
    os.environ["CHESS_VISION_DB"] = str(tmp_path / "test.db")
    storage.init_db()
    yield
    os.environ.pop("CHESS_VISION_DB", None)


def test_ten_distinct_personalities() -> None:
    personalities = list_personalities()

    assert len(personalities) == 10
    assert len({personality.id for personality in personalities}) == 10
    assert all(personality.rating == 500 for personality in personalities)


def test_negative_experience_creates_and_strengthens_rule() -> None:
    first = record_experience("tactician", "FORK", "king_rook", "ignored", "lost rook", -5)
    rule = learn_from_experience(first)
    second = record_experience("tactician", "FORK", "king_rook", "ignored", "lost rook", -5)
    strengthened = learn_from_experience(second)

    assert rule is not None
    assert strengthened is not None
    assert strengthened.confirmations == 2
    assert strengthened.confidence > rule.confidence
    assert list_learned_rules("tactician")[0].pattern == "FORK:king_rook"


def test_nonnegative_experience_does_not_create_avoidance_rule() -> None:
    episode = ExperienceEpisode(
        id=1, personality_id="universal", motif="FORK", context="center", decision="played", consequence="won", material_delta=3,
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert learn_from_experience(episode) is None


def test_technical_result_thresholds() -> None:
    assert _technical_result(45) == "1-0"
    assert _technical_result(-45) == "0-1"
    assert _technical_result(44) == "1/2-1/2"
