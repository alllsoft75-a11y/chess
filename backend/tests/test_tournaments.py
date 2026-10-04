import os
import time
from pathlib import Path

import pytest

from app import storage
from app.personalities import get_personality
from app.ratings import apply_game_result, get_rating, list_ratings
from app.tournament import get_tournament_report, start_round_robin


@pytest.fixture(autouse=True)
def temporary_database(tmp_path: Path):
    os.environ["CHESS_VISION_DB"] = str(tmp_path / "test.db")
    storage.init_db()
    yield
    os.environ.pop("CHESS_VISION_DB", None)


def test_elo_updates_asymmetric_and_persists() -> None:
    before_white = get_rating("sanguine")
    before_black = get_rating("choleric")

    rating = apply_game_result("sanguine", "choleric", "1-0")

    after_white = get_rating("sanguine")
    after_black = get_rating("choleric")
    assert rating["white_after"] == pytest.approx(after_white)
    assert after_white > before_white
    assert after_black < before_black
    gain = after_white - before_white
    loss = before_black - after_black
    assert gain == pytest.approx(16.0, abs=0.5)
    assert loss == pytest.approx(16.0, abs=0.5)

    apply_game_result("choleric", "sanguine", "1-0")
    rows = {row["personality_id"]: row for row in list_ratings()}
    assert rows["sanguine"]["games"] == 2
    assert rows["sanguine"]["wins"] == 1
    assert rows["sanguine"]["losses"] == 1


def test_equal_ratings_draw_keeps_ratings() -> None:
    before = get_rating("universal")
    apply_game_result("universal", "sanguine", "1/2-1/2")
    assert get_rating("universal") == pytest.approx(before, abs=1.0)


def test_round_robin_persists_games_and_updates_ratings() -> None:
    tournament_id = start_round_robin(
        max_fullmoves=4, games_per_pair=1, personality_ids=["sanguine", "choleric", "phlegmatic"]
    )

    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        report = get_tournament_report(tournament_id)
        if report["status"] in {"finished", "failed"}:
            break
        time.sleep(1)

    assert report["status"] == "finished", report.get("error")
    assert report["total_games"] == 3
    assert report["played_games"] == 3
    assert len(report["games"]) == 3
    points = sum(
        1 if game.result == "1-0" else 0 if game.result == "0-1" else 0.5
        for game in report["games"]
    ) + sum(
        0 if game.result == "1-0" else 1 if game.result == "0-1" else 0.5
        for game in report["games"]
    )
    assert points == pytest.approx(3.0)
    for game in report["games"]:
        assert game.white_rating_before is not None
        assert game.white_rating_after is not None

    rows = {row["personality_id"]: row for row in list_ratings()}
    assert sum(row["games"] for row in rows.values()) >= 6
    total_games = sum(row["wins"] + row["draws"] + row["losses"] for row in rows.values())
    assert total_games == sum(row["games"] for row in rows.values())


def test_unknown_personality_rejected() -> None:
    with pytest.raises(ValueError):
        start_round_robin(personality_ids=["sanguine", "nope"])


def test_get_rating_seeds_from_profile() -> None:
    assert get_rating("universal") == get_personality("universal").rating
