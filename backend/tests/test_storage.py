import os
from pathlib import Path

import pytest

from app import storage


@pytest.fixture(autouse=True)
def temporary_database(tmp_path: Path):
    os.environ["CHESS_VISION_DB"] = str(tmp_path / "test.db")
    storage.init_db()
    yield
    os.environ.pop("CHESS_VISION_DB", None)


def test_saved_game_persists_moves_and_pgn() -> None:
    game = storage.create_game("Tester", "white", "tactician")
    turn = storage.play_saved_turn(game.id, "e2e4")
    restored = storage.get_game(game.id)

    assert turn.program_move is not None
    assert "1. e4" in restored.pgn
    assert "RulesVersion" in restored.pgn
    assert "Personality" in restored.pgn
    assert restored.personality_id == "tactician"
    assert storage.list_games()[0].personality_id == "tactician"
    assert storage.list_games()[0].ply_count == 2


def test_player_position_is_saved_before_program_reply() -> None:
    game = storage.create_game("Tester", "white")
    player = storage.play_saved_player_move(game.id, "e2e4")

    assert player.player_move is not None
    assert player.program_move is None
    assert player.fen.split()[1] == "b"
    assert storage.list_games()[0].ply_count == 1

    program = storage.play_saved_program_move(game.id)
    assert program.program_move is not None
    assert program.fen.split()[1] == "w"
    assert storage.list_games()[0].ply_count == 2


def test_rule_requires_backtest_before_approval() -> None:
    proposal = storage.create_rule_proposal("Test", "Rule", {"threshold": 2})

    with pytest.raises(ValueError):
        storage.approve_rule_proposal(proposal.id)
    backtested = storage.backtest_rule_proposal(proposal.id)
    approved = storage.approve_rule_proposal(proposal.id)
    assert backtested.status == "backtested"
    assert approved.status == "approved"
    assert approved.approved_version == f"0.1.{proposal.id}"
