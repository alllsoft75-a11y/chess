from app.analysis import analyze_position


def motifs(fen: str, code: str):
    return [motif for motif in analyze_position(fen).motifs if motif.code == code]


def test_immediate_knight_fork() -> None:
    found = motifs("4k3/3q1r2/8/4N3/8/8/8/4K3 w - - 0 1", "FORK")

    assert len(found) == 1
    assert found[0].actor == "e5"
    assert found[0].targets == ["d7", "f7"]
    assert found[0].actor_piece == "knight"
    assert found[0].actor_safe is True
    assert found[0].material_potential == 6
    assert found[0].target_gains == {"d7": 6, "f7": 2}
    assert "коневая вилка" in found[0].explanation


def test_absolute_pin() -> None:
    found = motifs("4k3/4n3/8/8/8/8/4R3/4K3 w - - 0 1", "PIN")

    assert len(found) == 1
    assert found[0].actor == "e2"
    assert found[0].targets == ["e7", "e8"]


def test_blocked_bishop_queen_battery() -> None:
    found = motifs("4k3/8/8/8/4P3/3B4/2Q5/4K3 w - - 0 1", "BATTERY")

    assert len(found) == 1
    assert found[0].kind == "PATTERN"
    assert found[0].blocker == "e4"
    assert "перекрыта пешка на e4" in found[0].explanation


def test_only_defender_pattern() -> None:
    found = motifs("4k3/8/8/8/8/7n/5P2/5R1K w - - 0 1", "ONLY_DEFENDER")

    assert any(motif.actor == "f1" and motif.targets == ["f2"] for motif in found)
