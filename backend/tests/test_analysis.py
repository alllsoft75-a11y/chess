from app.analysis import analyze_position


def piece_at(fen: str, square: str):
    result = analyze_position(fen)
    return next(piece for piece in result.pieces if piece.square == square)


def square_at(fen: str, square: str):
    result = analyze_position(fen)
    return next(item for item in result.squares if item.square == square)


def test_advanced_passed_pawn_has_dynamic_value() -> None:
    result = analyze_position("8/6P1/8/8/8/8/8/4k2K w - - 0 1")

    pawn = next(item for item in result.passed_pawns if item.square == "g7")
    assert pawn.moves_to_promotion == 1
    assert pawn.dynamic_value >= 7
    assert pawn.threat_level in {"PROMOTION_THREAT", "FORCED_PROMOTION", "PROMOTION_WITH_CHECK"}


def test_starting_position_is_not_under_immediate_attack() -> None:
    result = analyze_position("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

    assert len(result.pieces) == 32
    assert not [piece for piece in result.pieces if piece.state in {"CRITICAL", "EXPOSED"}]


def test_undefended_attacked_queen_is_exposed() -> None:
    queen = piece_at("4k3/8/8/8/3q4/8/3R4/4K3 w - - 0 1", "d4")

    assert queen.state == "CRITICAL"
    assert queen.legal_attackers == ["d2"]
    assert queen.defenders == []
    assert "Ферзь на d4 теряется" in queen.explanation


def test_feminine_piece_uses_feminine_forms() -> None:
    rook = piece_at("4k3/8/8/8/3r4/8/3R4/4K3 w - - 0 1", "d4")

    assert "Ладья на d4 теряется" in rook.explanation


def test_defended_attacked_piece_is_contested() -> None:
    pawn = piece_at("4k3/8/8/3p4/4P3/5P2/8/4K3 b - - 0 1", "e4")

    assert pawn.state == "CONTESTED"
    assert pawn.legal_attackers == ["d5"]
    assert pawn.defenders == ["f3"]


def test_checked_king_is_critical() -> None:
    king = piece_at("4k3/8/8/8/8/8/4R3/4K3 b - - 0 1", "e8")

    assert king.state == "CRITICAL"


def test_defended_pawn_advance_is_a_safe_retreat() -> None:
    pawn = piece_at("3r2k1/ppp2ppp/r7/8/3P2P1/4BP1P/PP6/2R1R1K1 w - - 3 24", "a2")

    assert pawn.state == "EXPOSED"
    assert "a3" in pawn.safe_moves


def test_starting_center_contains_pawn_control() -> None:
    d3 = square_at("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "d3")

    assert d3.white_pawn_control is True
    assert d3.white_effective == ["c2", "e2"]
    assert d3.black_effective == []
    assert d3.balance == 2


def test_square_control_marks_tension() -> None:
    d5 = square_at("4k3/8/5n2/3p4/4P3/2N2N2/8/4K3 w - - 0 1", "d5")

    assert d5.white_effective == ["c3", "e4"]
    assert d5.black_effective == ["f6"]
    assert d5.tension == 1


def test_pinned_piece_has_geometric_but_not_effective_control() -> None:
    f4 = square_at("4r1k1/8/8/8/8/8/4N3/4K3 w - - 0 1", "f4")

    assert f4.white_attackers == ["e2"]
    assert f4.white_effective == []


def test_rook_on_open_file_gets_activity_feature() -> None:
    rook = piece_at("4k3/8/8/8/8/8/8/R3K3 w Q - 0 1", "a1")

    assert "занимает открытую вертикаль" in rook.activity.features
    assert rook.activity.state in {"NORMAL", "ACTIVE"}


def test_blocked_bishop_is_limited_by_own_pawns() -> None:
    bishop = piece_at("4k3/8/8/8/8/1P1P1P2/2B5/4K3 w - - 0 1", "c2")

    assert len(bishop.activity.safe_moves) <= 3
    assert bishop.activity.state in {"PASSIVE", "LIMITED", "NORMAL"}


def test_knight_on_edge_with_a_job_avoids_generic_penalty() -> None:
    knight = piece_at("4k3/8/8/8/8/N7/2P5/4K3 w - - 0 1", "a3")

    assert "находится на краю и имеет мало влияния" not in knight.activity.features
    assert "находится на краю, но выполняет конкретную функцию" in knight.activity.features


def test_situation_detects_tactical_crisis() -> None:
    result = analyze_position("4k3/8/8/8/3q4/8/3R4/4K3 w - - 0 1")

    assert result.situation.context == "TACTICAL_CRISIS"
    assert "d4" in result.situation.focus_squares
    assert result.situation.black.defense == "CRITICAL"


def test_bishop_e7_turns_critical_after_knight_leaves() -> None:
    bishop = piece_at("r2q1rk1/ppp1bppp/5n2/7b/3n4/2NBQ2P/PPPP1PP1/R1B1R1K1 w - - 0 12", "e7")

    assert bishop.legal_attackers == ["e3"]
    assert bishop.defenders == ["d8"]
    assert bishop.exchange_loss == 3
    assert bishop.state == "CRITICAL"
