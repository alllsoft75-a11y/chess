from app.analysis import analyze_position
from app.transition import analyze_move


def test_queen_double_attack_on_defended_targets_is_not_fork() -> None:
    fen = "r1bqkbnr/ppp1pppp/2n5/3q4/8/3P1N2/PPP2PPP/RNBQKB1R b KQkq - 0 4"

    motifs = [m for m in analyze_position(fen).motifs if m.code == "FORK" and m.side == "black"]

    assert not [m for m in motifs if m.actor == "d5"]


def test_transition_does_not_call_fake_fork_strong() -> None:
    fen_before = "r1bqkbnr/ppp1pppp/2n5/3P4/8/5N2/PPP2PPP/RNBQKB1R b KQkq - 0 3"

    result = analyze_move(fen_before, "d8d5")

    assert all(change.category != "STRONG_FORK" for change in result.changes)


def test_knight_fork_of_two_defended_rooks_is_fork_with_see_potential() -> None:
    fen = "4k3/8/8/8/4n3/2R3R1/1P4P1/4K3 b - - 0 1"

    motifs = [m for m in analyze_position(fen).motifs if m.code == "FORK" and m.side == "black"]

    fork = next((m for m in motifs if m.actor == "e4"), None)
    assert fork is not None
    assert fork.material_potential == 2
    assert fork.target_gains == {"c3": 2, "g3": 2}


def test_royal_fork_counts_with_single_profitable_target() -> None:
    fen = "4k3/8/8/8/3R4/2P5/1P2n3/6K1 w - - 0 1"

    motifs = [m for m in analyze_position(fen).motifs if m.code == "FORK" and m.side == "black"]

    fork = next((m for m in motifs if m.actor == "e2"), None)
    assert fork is not None
    assert any(value == 100 for value in fork.target_values.values())
    assert fork.target_gains == {"d4": 2}
    assert fork.material_potential == 2
