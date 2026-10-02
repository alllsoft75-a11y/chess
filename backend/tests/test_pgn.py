from app.pgn import parse_pgn


PGN = """[White "Alice"]
[Black "Bob"]
[Result "*"]
[TimeControl "180+2"]

1. e4 { [%clk 0:03:00] } e5 { [%clk 0:02:58] } 2. Nf3 { [%emt 0:00:03] } *
"""


def test_parse_timeline_and_clocks() -> None:
    game = parse_pgn(PGN)

    assert len(game.timeline) == 4
    assert game.timeline[1].san == "e4"
    assert game.timeline[1].elapsed_seconds == 2
    assert game.timeline[1].elapsed_is_estimated is True
    assert game.timeline[2].elapsed_seconds == 4
    assert game.timeline[3].elapsed_seconds == 3
    assert game.timeline[3].elapsed_is_estimated is False
    assert game.headers.white == "Alice"
    assert game.headers.initial_time_seconds == 180
    assert game.headers.increment_seconds == 2


def test_missing_time_control_does_not_assume_zero_increment() -> None:
    game = parse_pgn("""[White "Alice"]
[Black "Bob"]
[Result "*"]

1. e4 { [%clk 0:00:58] } e5 { [%clk 0:00:57] } *
""")

    assert game.headers.initial_time_seconds is None
    assert game.headers.increment_seconds is None
    assert game.timeline[1].clock_seconds == 58
    assert game.timeline[1].elapsed_seconds is None


def test_zero_increment_is_preserved() -> None:
    game = parse_pgn("""[White "Alice"]
[Black "Bob"]
[Result "*"]
[TimeControl "60"]

1. e4 { [%clk 0:00:58] } *
""")

    assert game.headers.initial_time_seconds == 60
    assert game.headers.increment_seconds == 0
    assert game.timeline[1].elapsed_seconds == 2
