import os
from pathlib import Path

import pytest

from app import storage
from app.contexts import ContextLedger
from app.program import choose_program_move


@pytest.fixture(autouse=True)
def temporary_database(tmp_path: Path):
    os.environ["CHESS_VISION_DB"] = str(tmp_path / "test.db")
    storage.init_db()
    yield
    os.environ.pop("CHESS_VISION_DB", None)


def test_recapture_after_queen_trade_is_not_resignation() -> None:
    result = choose_program_move("3Q4/4k3/8/8/8/8/P6P/6K1 b - - 0 20")

    assert result.resigned is False
    assert result.move is not None
    assert result.move.uci == "e7d8"


def test_recapture_chosen_even_when_landing_attacked_by_cheaper_piece() -> None:
    result = choose_program_move("3rk3/p5pp/8/8/3Q4/2B5/P5PP/6K1 b - - 0 5")

    assert result.resigned is False
    assert result.move is not None
    assert result.move.uci == "d8d4"


def test_fork_context_is_detected_and_kept_across_plies() -> None:
    ledger = ContextLedger()

    ledger.update(__import__("chess").Board("4k3/8/8/8/4n3/5R2/8/1B4K1 b - - 0 1"))
    forks = [item for item in ledger.active() if item.kind == "fork_opportunity"]

    assert forks
    assert any(item.suggested_uci == "e4d2" and item.target_value == 5 for item in forks)

    ledger.update(__import__("chess").Board("4k3/8/8/8/4n3/5R2/8/1B5K b - - 1 1"))
    kept = [item for item in ledger.active() if item.kind == "fork_opportunity"]

    assert any(item.suggested_uci == "e4d2" for item in kept)


def test_fork_context_expires_when_window_closes() -> None:
    ledger = ContextLedger()
    ledger.update(__import__("chess").Board("4k3/8/8/8/4n3/8/8/1B5K b - - 0 1"))

    ledger.update(__import__("chess").Board("4k3/8/8/8/4n3/8/8/1B5K b - - 12 7"))

    assert not [item for item in ledger.active() if item.kind == "fork_opportunity" and item.actor == "e4"]


def test_fork_context_cancelled_when_knight_disappears() -> None:
    ledger = ContextLedger()
    ledger.update(__import__("chess").Board("4k3/8/8/8/4n3/5R2/8/1B4K1 b - - 0 1"))

    ledger.update(__import__("chess").Board("4k3/8/8/8/8/5R2/8/1B4K1 b - - 1 1"))

    assert not [item for item in ledger.active() if item.kind == "fork_opportunity"]


def test_latent_attack_on_defended_pawn_is_tracked() -> None:
    ledger = ContextLedger()

    ledger.update(__import__("chess").Board("r3k3/8/8/8/P7/1P6/8/7K b - - 0 1"))

    latent = [item for item in ledger.active() if item.kind == "latent_attack"]
    assert any(item.target_square == "a4" for item in latent)


def test_pending_exchange_on_contested_knight_is_tracked() -> None:
    ledger = ContextLedger()

    ledger.update(__import__("chess").Board("4k3/8/8/8/1b6/2N5/PP6/7K b - - 0 1"))

    exchanges = [item for item in ledger.active() if item.kind == "pending_exchange"]
    assert any(item.target_square == "c3" for item in exchanges)


def test_context_suggested_move_is_injected_into_search() -> None:
    contexts = [{
        "kind": "fork_opportunity",
        "motif": "FORK",
        "actor": "e4",
        "target_square": "d2",
        "target_value": 5,
        "note": "коневая вилка Nd2: цели b1(+3), f3(+5)",
        "suggested_uci": "e4d2",
        "ttl_plies": 8,
        "status": "active",
    }]

    result = choose_program_move("4k3/8/8/8/4n3/5R2/8/1B4K1 b - - 0 1", contexts=contexts)

    fork_move = next((item for item in [result.move, *result.alternatives] if item and item.uci == "e4d2"), None)
    assert fork_move is not None
    assert any("отслеживаемого контекста" in reason for reason in fork_move.reasons)


def test_active_fork_context_prevents_hopeless_resignation() -> None:
    contexts = [{
        "kind": "fork_opportunity",
        "motif": "FORK",
        "actor": "e4",
        "target_square": "d2",
        "target_value": 5,
        "note": "коневая вилка",
        "suggested_uci": None,
        "ttl_plies": 8,
        "status": "active",
    }]

    result = choose_program_move("4k3/8/8/8/8/8/8/3QK3 b - - 0 20", contexts=contexts)

    assert result.resigned is False


def test_ledger_survives_storage_roundtrip() -> None:
    import chess

    game = storage.create_game("Player", "white", "sanguine")
    storage.play_saved_player_move(game.id, "e2e4")
    storage.play_saved_program_move(game.id)

    with storage.connection() as db:
        row = db.execute("SELECT contexts_json FROM games WHERE id = ?", (game.id,)).fetchone()

    assert row["contexts_json"]
    ledger = ContextLedger.loads(row["contexts_json"])
    assert isinstance(ledger.active(), list)
    assert chess.Board().fen()
