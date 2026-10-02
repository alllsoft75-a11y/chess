import chess

from app.analysis import analyze_position, clear_analysis_cache
from app.personalities import get_personality
from app.program import _mate_in_one_available, choose_program_move, play_turn


def test_knight_does_not_walk_into_pawn_capture() -> None:
    fen = "r1bqkbnr/ppp1pppp/2n5/3pP3/8/5N2/PPPP1PPP/RNBQKB1R b KQkq - 0 3"
    result = choose_program_move(fen, personality=get_personality("choleric"))

    assert result.move is not None
    assert result.move.uci != "g8f6"
    candidate = next((item for item in [result.move, *result.alternatives] if item.uci == "g8f6"), None)
    if candidate:
        assert candidate.score < -900
        assert any("под более дешёвую атаку" in reason for reason in candidate.reasons)


def test_structured_memory_penalizes_repeated_decision() -> None:
    fen = "r1bqkbnr/ppp1pppp/2n5/3pP3/8/5N2/PPPP1PPP/RNBQKB1R b KQkq - 0 3"
    baseline = choose_program_move(fen, personality=get_personality("choleric"))
    rules = [{
        "pattern": f"HANGING_PIECE:{analyze_position(fen).situation.context}",
        "response": "избегать решения Nf6; прошлый результат -2",
        "weight": -40,
        "confidence": 0.8,
    }]
    learned = choose_program_move(fen, personality=get_personality("choleric"), learned_rules=rules)

    baseline_candidate = next((item for item in [baseline.move, *baseline.alternatives] if item.uci == "g8f6"), None)
    learned_candidate = next((item for item in [learned.move, *learned.alternatives] if item.uci == "g8f6"), None)
    if baseline_candidate and learned_candidate:
        assert learned_candidate.score < baseline_candidate.score
        assert any("урок памяти" in reason for reason in learned_candidate.reasons)


def test_prefilter_keeps_quiet_escape_and_does_not_resign_equal_position() -> None:
    fen = "3q1rk1/1pp1ppbp/2n1b2p/r3P3/2BP4/pP3NNP/P4PP1/R2QR1K1 b - - 0 15"
    result = choose_program_move(fen, personality=get_personality("sanguine"))

    assert result.resigned is False
    assert result.move is not None
    assert result.move.score > -900


def test_search_is_pruned_and_cached() -> None:
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    clear_analysis_cache()
    first = choose_program_move(fen)
    second = choose_program_move(fen)

    assert first.metrics.legal_moves == 20
    assert first.metrics.root_candidates <= 7
    assert first.metrics.analyzed_branches <= 7
    assert second.metrics.cache_misses == 0
    assert second.metrics.cache_hits > 0


def test_program_takes_free_queen() -> None:
    result = choose_program_move("4k3/8/8/8/3q4/8/3R4/4K3 w - - 0 1")

    assert result.move is not None
    assert result.move.uci == "d2d4"
    assert any("+9" in reason for reason in result.move.reasons)


def test_trapped_queen_takes_bishop_for_compensation() -> None:
    fen = "2kr3r/ppp2Q1p/2n1Bpp1/2b1p3/6q1/1P4P1/P1bP1P1P/R1B2RK1 b - - 1 15"
    result = choose_program_move(fen)

    assert result.move is not None
    assert result.move.uci == "g4e6"
    assert result.move.san == "Qxe6"
    assert "минимизации ущерба" in result.move.reasons[0]
    assert "чистый ущерб 6" in result.move.reasons[1]


def test_bxc3_accounts_for_queen_recapture_not_only_pawn() -> None:
    fen = "r1b1k1nr/pppp1ppp/8/3Pp3/1b1nP2q/2P1Q3/PP3PPP/RNB1KBNR b KQkq - 4 6"
    result = choose_program_move(fen, personality=get_personality("sanguine"))

    bishop_sacrifice = next(item for item in [result.move, *result.alternatives] if item.uci == "b4c3")
    assert any("Qxc3" in reason for reason in bishop_sacrifice.reasons)
    assert any("Nxc3" in reason and "bxc3" in reason for reason in bishop_sacrifice.reasons)


def test_program_prefers_free_rook_on_h1() -> None:
    fen = "r1b1k1nr/pppp1ppp/8/4p3/2Bn4/2Q1B3/PP3PqP/RN2K1NR b KQkq - 0 10"
    result = choose_program_move(fen, personality=get_personality("sanguine"))

    assert result.move is not None
    assert result.move.uci == "g2h1"


def test_program_rejects_queen_for_bishop_on_c4() -> None:
    fen = "r1b2r1k/ppp2ppp/5n2/3p4/2B4q/5QB1/PP1NNP1P/2KR2R1 b - - 1 17"
    result = choose_program_move(fen, personality=get_personality("sanguine"))

    assert result.move is not None
    assert result.move.uci != "h4c4"


def test_sanguine_uses_pin_for_tempo_counterattack() -> None:
    fen = "r1b1k1nr/pppp1ppp/2n5/3Pp3/1b2P2q/2P2Q2/PP3PPP/RNB1KBNR b KQkq - 2 5"
    result = choose_program_move(fen, personality=get_personality("sanguine"))

    assert result.move is not None
    assert result.move.uci == "c6d4"
    assert any("связк" in reason for reason in result.move.reasons)
    assert any("темповая атака на ферзя" in reason for reason in result.move.reasons)


def test_program_prioritizes_stopping_pawn_on_g7() -> None:
    fen = "8/6P1/6R1/p2k4/3b4/1K1P4/r7/8 b - - 8 44"
    result = choose_program_move(fen, personality=get_personality("choleric"))

    assert result.move is not None
    assert result.move.uci == "d4g7"
    after = chess.Board(fen)
    after.push_uci(result.move.uci)
    assert not [pawn for pawn in analyze_position(after.fen()).passed_pawns if pawn.side == "white" and pawn.moves_to_promotion <= 1]


def test_damage_control_cannot_ignore_mate_in_one() -> None:
    fen = "r4r1k/ppp2ppp/5n2/3pB3/2B4q/5Q2/PP1NNP1P/2KR2R1 b - - 1 17"
    result = choose_program_move(fen, personality=get_personality("choleric"))

    if result.move:
        after = chess.Board(fen)
        after.push_uci(result.move.uci)
        assert not _mate_in_one_available(after, chess.WHITE)


def test_program_avoids_queen_losing_check_fork_in_game7() -> None:
    fen = "2kr3r/ppp2Q1p/2n2p2/2b1p3/2B4q/1P4P1/P1bP1P1P/R1B2RK1 b - - 0 14"
    result = choose_program_move(fen)

    assert result.move is not None
    assert result.move.uci != "h4g4"
    queen_move = next((item for item in [result.move, *result.alternatives] if item and item.uci == "h4g4"), None)
    if queen_move:
        assert queen_move.expected_reply == "Qe6+"
        assert any("вилка" in reason and "9" in reason for reason in queen_move.reasons)


def test_program_saves_attacked_knight_in_game4() -> None:
    fen = "r1bqkbnr/ppp1pppp/2n2n2/3p4/4n3/1B1P1N2/PPP2PPP/RNBQK2R b KQkq - 2 5"
    result = choose_program_move(fen)

    assert result.move is not None
    assert result.move.uci != "c8f5"


def test_program_saves_checked_bishop_after_c3_in_game4() -> None:
    fen = "r2qkbnr/ppp1pppp/2n2n2/3p1bN1/1b2P3/2PP1P2/PP4PP/RNBQK2R b KQkq - 0 9"
    result = choose_program_move(fen)

    assert result.move is not None
    assert result.move.uci != "c8f5"


def test_program_rejects_qxc5_when_it_allows_mate() -> None:
    fen = "2kr1b1r/ppp1pppp/2n5/1NN5/5Q2/8/PPq2PPP/R1B2RK1 b - - 3 15"
    result = choose_program_move(fen)

    assert result.move is not None
    assert result.move.uci != "c2c5"


def test_program_finds_discovered_queen_winning_combination() -> None:
    result = choose_program_move("2kr4/ppp2ppp/8/4pb2/2Pb1q2/1P1P1B2/P3QPPP/4RRK1 b - - 5 17")

    assert result.move is not None
    assert result.move.uci == "f5d3"
    assert result.move.expected_reply == "Qxd3"
    assert result.move.continuation == "Bxf2+"
    assert "выиграть ферзя" in result.move.plan
    assert any("+5" in reason for reason in result.move.reasons)


def test_program_resigns_when_hopeless_without_counterplay() -> None:
    result = choose_program_move("4k3/8/8/8/8/8/8/3QK3 b - - 0 20")

    assert result.resigned is True
    assert result.move is None
    assert result.result == "1-0"
    assert "материальный дефицит" in result.resignation_reason


def test_program_does_not_resign_with_forcing_resource() -> None:
    result = choose_program_move("6k1/8/8/8/8/8/5q2/6KQ b - - 0 20")

    assert result.resigned is False
    assert result.move is not None


def test_program_does_not_resign_when_material_up_despite_pessimistic_scores() -> None:
    fen = "2kr1b1r/ppp1pppp/2n4n/q3Pb2/2Pp1B2/3P1N2/PP1QBPPP/R3K2R b KQ - 6 10"
    result = choose_program_move(fen, personality=get_personality("universal"))

    assert result.resigned is False
    assert result.move is not None
    assert result.move.uci in {"d8d5", "a5d5", "a5d8", "f5d3", "h6f5"}


def test_program_rejects_poisoned_knight_fork() -> None:
    result = choose_program_move("r1bqkbnr/pppppppp/2n5/8/1n2P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 2 2")

    assert result.move is not None
    assert result.move.uci != "b4c2"


def test_expected_reply_is_plausible_not_losing_bishop_for_pawn() -> None:
    result = choose_program_move("r1b2rk1/ppppnppp/2nq4/6B1/1PBpP3/P4N2/1P3PPP/RN1Q1RK1 b - - 4 9")

    assert result.move is not None
    assert result.move.expected_reply != "Bxf7+"


def test_material_deficit_penalizes_major_piece_exchange() -> None:
    board_fen = "4k3/8/8/8/3q4/8/3R4/4K3 w - - 0 1"
    result = choose_program_move(board_fen)

    assert result.move is not None
    assert result.move.uci == "d2d4"


def test_remembered_plan_is_used_when_still_reasonable() -> None:
    fen = "r1bqkbnr/pppppppp/2n5/8/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 2 2"
    baseline = choose_program_move(fen)
    remembered = baseline.alternatives[0]
    result = choose_program_move(fen, remembered.uci)

    assert result.move is not None
    if remembered.score >= baseline.move.score - 25:
        assert result.move.uci == remembered.uci
        assert "продолжение сохранённого микроплана" in result.move.reasons


def test_program_move_contains_human_plan() -> None:
    result = choose_program_move("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")

    assert result.move is not None
    assert result.move.plan
    assert result.move.expected_reply


def test_player_turn_returns_program_reply() -> None:
    result = play_turn("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1", "e2e4")

    assert result.player_move.uci == "e2e4"
    assert result.program_move is not None
    assert result.fen_after
