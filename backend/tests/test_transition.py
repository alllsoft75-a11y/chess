from app.transition import analyze_move


def test_knight_departure_makes_bishop_critical() -> None:
    result = analyze_move(
        "r2q1rk1/ppp1bppp/2n2n2/7b/3N4/2NBQ2P/PPP2PP1/R1B1R1K1 b - - 0 11",
        "c6d4",
    )

    events = [event for event in result.events if event.code == "BECAME_VULNERABLE" and "e7" in event.subjects]
    assert len(events) == 1
    assert events[0].before == "CONTESTED"
    assert events[0].after == "CRITICAL"
    assert "c6" in events[0].subjects
    assert result.changes[0].category == "DEFENSIVE_BREAKDOWN"
    assert "После ухода фигуры с c6" in result.changes[0].message


def test_new_fork_is_reported() -> None:
    result = analyze_move("4k3/3q1r2/8/8/2N5/8/8/4K3 w - - 0 1", "c4e5")

    created = [event for event in result.events if event.code == "CREATED_MOTIF"]
    assert any(event.after == "FORK" and "e5" in event.subjects for event in created)


def test_move_20_allows_mate_in_one_and_is_a_blunder() -> None:
    result = analyze_move(
        "6k1/n4ppp/4p3/pp2N3/2p1P3/5N2/PP3PPP/3R2K1 b - - 0 20",
        "f7f6",
    )

    assert len(result.changes) == 1
    assert result.changes[0].category == "IGNORED_MATE_THREAT"
    assert result.changes[0].headline == "Грубая ошибка: допущен мат в один ход"
    assert "d1d8" in result.changes[0].message


def test_move_17_is_strong_safe_knight_fork() -> None:
    result = analyze_move(
        "5rk1/n4ppp/1p2p3/p1N5/2p1P3/5N2/PP3PPP/R4RK1 w - - 0 17",
        "c5d7",
    )

    forks = [motif for motif in result.after.motifs if motif.code == "FORK" and motif.actor == "d7"]
    assert len(forks) == 1
    assert forks[0].actor_safe is True
    assert forks[0].target_values == {"b6": 1, "f8": 5}
    assert forks[0].target_gains == {"b6": 1, "f8": 2}
    assert forks[0].material_potential == 2
    strong = [change for change in result.changes if change.category == "STRONG_FORK"]
    assert len(strong) == 1
    assert strong[0].headline == "Очень сильный ход: вилка"
    assert "Коневая" in strong[0].message


def test_new_check_is_not_called_intensified_pressure() -> None:
    result = analyze_move(
        "Qn1qkbnr/3p1ppp/1p2p3/p7/2B1PB2/8/PP3PPP/RN2K1NR b KQk - 0 8",
        "f8b4",
    )

    checks = [change for change in result.changes if change.category == "CREATED_CHECK"]
    assert len(checks) == 1
    assert checks[0].headline == "Шах"
    assert "впервые" in checks[0].message
    assert not [change for change in result.changes if change.category == "INTENSIFIED_ATTACK" and "e1" in change.subjects]


def test_qxe7_creates_threat_instead_of_ignoring_one() -> None:
    result = analyze_move(
        "r2q1rk1/ppp1bppp/5n2/7b/3n4/2NBQ2P/PPPP1PP1/R1B1R1K1 w - - 0 12",
        "e3e7",
    )

    assert not [change for change in result.changes if change.category == "IGNORED_MATERIAL_THREAT"]
    assert any(
        change.category in {"CREATED_ATTACK", "INTENSIFIED_ATTACK"} and "d8" in change.subjects
        for change in result.changes
    )


def test_qxd8_creates_threat_to_a8_instead_of_ignoring_one() -> None:
    result = analyze_move(
        "r2q1rk1/ppp1Qppp/5n2/7b/8/2NB3P/PPnP1PP1/R1B1R1K1 w - - 0 13",
        "e7d8",
    )

    assert not [change for change in result.changes if change.category == "IGNORED_MATERIAL_THREAT"]
    assert any(
        change.category in {"CREATED_ATTACK", "INTENSIFIED_ATTACK"} and "a8" in change.subjects
        for change in result.changes
    )
    compensated = [change for change in result.changes if change.category == "COMPENSATED_RISK"]
    assert compensated
    assert any("взят материал стоимостью 9" in change.message for change in compensated)
    assert not [change for change in result.changes if change.category == "DEFENSIVE_BREAKDOWN" and "e1" in change.subjects]


def test_capture_is_named_as_capture() -> None:
    result = analyze_move(
        "rnbqkbnr/3ppppp/1pp5/p2P4/2P1P3/8/PP3PPP/RNBQKBNR b KQkq - 0 5",
        "c6d5",
    )

    assert result.action == "CAPTURE"
    assert result.action_text == "Взятие на d5: взята пешка (+1)"
    assert result.san == "cxd5"


def test_enemy_piece_becoming_contested_is_created_attack() -> None:
    result = analyze_move(
        "rnbqkbnr/3ppppp/1pp5/p7/2PP4/8/PP3PPP/RNBQKBNR w KQkq - 0 4",
        "d4d5",
    )

    changes = [change for change in result.changes if "c6" in change.subjects]
    assert len(changes) == 1
    assert changes[0].category == "CREATED_ATTACK"
    assert changes[0].headline == "Атака"
    assert "Ослабление защиты" not in changes[0].message


def test_bishop_takes_pawn_and_is_lost_without_solving_knight() -> None:
    result = analyze_move(
        "Qn1qkbnr/3p1ppp/bp2p3/p7/2P1PB2/8/PP3PPP/RN2KBNR b KQk - 0 7",
        "a6c4",
    )

    assert len(result.changes) == 1
    assert result.changes[0].category == "MATERIAL_BLUNDER"
    assert result.changes[0].headline == "Грубая материальная ошибка"
    assert "+1" in result.changes[0].message
    assert "3" in result.changes[0].message
    assert "b8" in result.changes[0].message


def test_d6_reduces_knight_and_bishop_risk() -> None:
    result = analyze_move(
        "Qn1qkbnr/3p1ppp/bp2p3/p7/2P1PB2/8/PP3PPP/RN2KBNR b KQk - 0 7",
        "d7d6",
    )

    before_knight = next(piece for piece in result.before.pieces if piece.square == "b8")
    after_knight = next(piece for piece in result.after.pieces if piece.square == "b8")
    before_bishop = next(piece for piece in result.before.pieces if piece.square == "a6")
    after_bishop = next(piece for piece in result.after.pieces if piece.square == "a6")
    assert before_knight.state == "CRITICAL"
    assert after_knight.state == "CONTESTED"
    assert before_bishop.state == "CONTESTED"
    assert after_bishop.state == "CONTESTED"
    assert after_bishop.activity.index > before_bishop.activity.index
    assert after_knight.exchange_loss == 0
    assert after_bishop.exchange_loss == 0
    assert not [change for change in result.changes if change.category == "MATERIAL_BLUNDER"]


def test_queen_capture_intensifies_attack_on_b8_and_a6() -> None:
    result = analyze_move(
        "rn1qkbnr/3p1ppp/bp2p3/p2Q4/2P1PB2/8/PP3PPP/RN2KBNR w KQkq - 0 7",
        "d5a8",
    )

    changes = [change for change in result.changes if change.category == "INTENSIFIED_ATTACK"]
    assert any("b8" in change.subjects for change in changes)
    assert any(
        "a6" in change.subjects
        for change in result.changes
        if change.category in {"CREATED_ATTACK", "INTENSIFIED_ATTACK"}
    )
    assert all(change.headline == "Усиление атаки" for change in changes)
    assert not [change for change in result.changes if change.category == "INEFFECTIVE_ATTACK"]


def test_attack_on_already_attacking_queen_is_not_called_created_attack() -> None:
    result = analyze_move(
        "rn1qkbnr/3ppppp/bp6/p2Q4/2P1PB2/8/PP3PPP/RN2KBNR b KQkq - 0 6",
        "e7e6",
    )

    changes = [change for change in result.changes if "d5" in change.subjects]
    assert changes
    assert changes[0].category == "IGNORED_MATERIAL_THREAT"
    assert changes[0].headline == "Зевок материальной угрозы"
    assert "a8" in changes[0].message


def test_unrelated_bishop_move_does_not_newly_endanger_b8_knight() -> None:
    result = analyze_move(
        "Qn1qkbnr/3p1ppp/bp2p3/p7/2P1PB2/8/PP3PPP/RN2KBNR b KQk - 0 7",
        "a6c4",
    )

    before_knight = next(piece for piece in result.before.pieces if piece.square == "b8")
    after_knight = next(piece for piece in result.after.pieces if piece.square == "b8")
    assert before_knight.state == "CRITICAL"
    assert after_knight.state == "CRITICAL"
    assert not [event for event in result.events if event.code == "BECAME_VULNERABLE" and "b8" in event.subjects]


def test_illegal_move_is_rejected() -> None:
    try:
        analyze_move("4k3/8/8/8/8/8/8/4K3 w - - 0 1", "e1e8")
    except ValueError as error:
        assert "нелегален" in str(error)
    else:
        raise AssertionError("Ожидалась ошибка нелегального хода")
