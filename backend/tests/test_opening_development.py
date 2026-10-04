import chess

from app.contexts import ContextLedger, detect_contexts
from app.program import choose_program_move


def test_program_develops_instead_of_knight_sortie_in_opening() -> None:
    result = choose_program_move("rnbqkb1r/pppppppp/5n2/8/3P4/4P3/PPP2PPP/RNBQKBNR b KQkq - 0 2")

    assert result.resigned is False
    assert result.move is not None
    assert result.move.uci != "f6e4"


def test_attacked_knight_retreats_to_active_center_not_backwards() -> None:
    result = choose_program_move("r1bqkbnr/pppppppp/8/8/1n6/2P2N2/PP1PPPPP/RNBQKB1R b KQkq - 1 3")

    assert result.move is not None
    assert result.move.uci == "b4d5"


def test_knight_dance_home_return_is_penalised() -> None:
    result = choose_program_move("r1bqkbnr/pppppppp/2n5/8/8/2P2N2/PP1PPPPP/RNBQKB1R b KQkq - 0 2")

    assert result.move is not None
    if result.move.uci.startswith("c6"):
        assert result.move.uci != "c6b8"


def test_fork_context_ignores_pawn_only_targets() -> None:
    board = chess.Board("r1bqkbnr/pppppppp/8/8/1n6/2P5/PP1PPPPP/RNBQKBNR b KQkq - 0 2")

    records = detect_contexts(board)

    forks = [item for item in records if item["kind"] == "fork_opportunity"]
    assert not any(item["actor"] == "b4" for item in forks)


def test_fork_context_keeps_valuable_target_forks() -> None:
    ledger = ContextLedger()

    ledger.update(chess.Board("4k3/8/8/8/4n3/5R2/8/1B4K1 b - - 0 1"))

    forks = [item for item in ledger.active() if item.kind == "fork_opportunity"]
    assert any(item.suggested_uci == "e4d2" for item in forks)
