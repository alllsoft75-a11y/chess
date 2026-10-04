import os
import threading
import time
from pathlib import Path

import chess
import pytest

from app import storage
from app.personalities import get_personality
from app.ponder import (
    PonderEntry,
    _ponder_round,
    cancel_ponder,
    clear_game,
    ponder_entries,
    take_pondered,
)
from app.program import _widen, choose_program_move, set_wide_search


def _stop_ponder_threads() -> None:
    for game_id in range(200):
        cancel_ponder(game_id)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        workers = [t for t in threading.enumerate() if t.name.startswith("ponder-")]
        if not workers:
            break
        workers[0].join(timeout=2)
    for game_id in range(200):
        clear_game(game_id)


@pytest.fixture(autouse=True)
def temporary_database(tmp_path: Path):
    os.environ["CHESS_VISION_DB"] = str(tmp_path / "test.db")
    storage.init_db()
    _stop_ponder_threads()
    yield
    _stop_ponder_threads()
    os.environ.pop("CHESS_VISION_DB", None)


def test_wide_search_limits_are_thread_local() -> None:
    assert _widen(7) == 7
    set_wide_search(True)
    try:
        assert _widen(7) == 14
    finally:
        set_wide_search(False)
    assert _widen(7) == 7


def test_quiet_mode_skips_utterance() -> None:
    result = choose_program_move(
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        personality=get_personality("sanguine"),
        quiet=True,
    )

    assert result.move is not None
    assert result.utterance is None
    assert result.emotion is None


def test_ponder_round_precomputes_replies() -> None:
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"

    _ponder_round(1, fen, "g1f3", None, get_personality("sanguine"), [], "[]", moves_limit=2, budget_seconds=60.0)

    entries = ponder_entries(1)
    assert entries
    assert any(entry.player_uci == "g1f3" for entry in entries)
    hit = take_pondered(1, "g1f3", "rnbqkbnr/pppppppp/8/8/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2")
    assert hit is not None
    assert hit.decision.move is not None
    assert hit.decision.utterance is None
    assert take_pondered(1, "g1f3", "rnbqkbnr/pppppppp/8/8/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2") is None


def test_storage_uses_seeded_ponder_entry() -> None:
    game = storage.create_game("Player", "white", "sanguine")
    first = storage.play_saved_player_move(game.id, "e2e4")
    assert first.status == "active"
    program = storage.play_saved_program_move(game.id)
    assert program.program_move is not None

    board = chess.Board(program.fen)
    player_move = "g1f3" if chess.Move.from_uci("g1f3") in board.legal_moves else "d2d4"
    board.push_uci(player_move)
    seeded = choose_program_move(board.fen(), quiet=True)
    from app import ponder as ponder_module

    ponder_module._ENTRIES[game.id] = [PonderEntry(player_move, board.fen(), seeded)]

    storage.play_saved_player_move(game.id, player_move)
    answer = storage.play_saved_program_move(game.id)

    assert answer.program_move is not None
    assert answer.program_move.uci == seeded.move.uci
    assert answer.utterance is not None or answer.resignation_reason
    assert not ponder_entries(game.id)
