from pathlib import Path

from app.pgn import parse_pgn


PGN_PATH = Path(__file__).parents[2] / "lichess_pgn_2026.09.28_xadrez24_vs_AlexTaran.vNYxnIIn.pgn"


def test_example_game_collects_capture_chains() -> None:
    game = parse_pgn(PGN_PATH.read_text(encoding="utf-8"))

    chain = next(item for item in game.capture_chains if item.start_ply == 13 and item.end_ply == 15)
    assert chain.white_gain == 8
    assert chain.black_gain == 1
    assert chain.balance == 7
    assert chain.kind == "WHITE_MATERIAL_GAIN"
    assert [event.san for event in chain.events] == ["Qxa8", "Bxc4", "Bxc4"]


def test_example_game_detects_equal_four_capture_chain() -> None:
    game = parse_pgn(PGN_PATH.read_text(encoding="utf-8"))

    chain = next(item for item in game.capture_chains if item.start_ply == 19 and item.end_ply == 22)
    assert chain.white_gain == 12
    assert chain.black_gain == 12
    assert chain.balance == 0
    assert chain.kind == "EQUAL_EXCHANGE"
    assert [event.san for event in chain.events] == ["Qxb8", "Qxb8", "Bxb8", "dxc4"]
