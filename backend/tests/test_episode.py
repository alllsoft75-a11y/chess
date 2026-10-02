from app.episode import analyze_episode
from app.transition import analyze_move


def test_check_and_reply_form_completed_episode() -> None:
    episode = analyze_episode(
        "Qn1qkbnr/3p1ppp/1p2p3/p7/2B1PB2/8/PP3PPP/RN2K1NR b KQk - 0 8",
        "f8b4",
        "b1c3",
    )

    assert episode.kind == "CHECK_PARRIED"
    assert episode.headline == "Шах и ответ"
    assert "парировало" in episode.message


def test_pawn_retake_is_equal_exchange() -> None:
    episode = analyze_episode(
        "4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1",
        "e4d5",
        "e8d7",
    )

    assert episode.kind == "UNANSWERED_CAPTURE"


def test_rook_for_bishop_is_unfavorable_exchange() -> None:
    episode = analyze_episode(
        "8/8/4k3/3b4/3R4/8/8/4K3 w - - 0 1",
        "d4d5",
        "e6d5",
    )

    assert episode.kind == "UNFAVORABLE_EXCHANGE"
    assert episode.first_side_net == -2
    assert "+3" in episode.message
    assert "5" in episode.message


def test_equal_rook_exchange() -> None:
    episode = analyze_episode(
        "3rk3/8/8/8/3R4/8/8/4K3 w - - 0 1",
        "d4d8",
        "e8d8",
    )

    assert episode.kind == "EQUAL_EXCHANGE"
    assert episode.first_side_net == 0


def test_completed_exchange_remains_completed_before_next_move() -> None:
    episode = analyze_episode(
        "rn1qkbnr/3ppppp/bp6/p2p4/2P1PB2/8/PP3PPP/RN1QKBNR w KQkq - 0 6",
        "d1d5",
        "e7e6",
    )

    assert episode.kind == "UNANSWERED_CAPTURE"


def test_single_capture_reports_immediate_material_risk() -> None:
    move = analyze_move("8/8/4k3/3b4/3R4/8/8/4K3 w - - 0 1", "d4d5")

    assert move.action == "CAPTURE"
    assert move.captured_value == 3
    assert move.mover_value == 5
    assert move.immediate_risk == 5
    assert move.material_outlook == "UNFAVORABLE"
