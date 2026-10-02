from pathlib import Path

from app.batch import _time_pressure_contexts, analyze_player_games
from app.pgn import parse_pgn


PGN_PATH = Path(__file__).parents[2] / "lichess_pgn_2026.09.28_xadrez24_vs_AlexTaran.vNYxnIIn.pgn"


def test_batch_report_finds_allowed_mate_for_black_player() -> None:
    report = analyze_player_games([PGN_PATH.read_text(encoding="utf-8")], "AlexTaran")

    assert report.games_analyzed == 1
    assert report.moves_analyzed == 20
    assert report.clean_moves > 0
    assert 0 < report.clean_move_rate <= 1
    assert any(item.category == "STABLE_PLAY" for item in report.strengths)
    assert report.long_pauses
    mate_errors = [item for item in report.aggregates if item.category == "IGNORED_MATE_THREAT"]
    material_blunders = [item for item in report.aggregates if item.category == "MATERIAL_BLUNDER"]
    assert len(mate_errors) == 1
    assert mate_errors[0].count == 1
    assert mate_errors[0].samples[0].san == "f6"
    assert mate_errors[0].samples[0].timing is not None
    assert mate_errors[0].samples[0].timing.clock_after_seconds == 159
    assert mate_errors[0].samples[0].timing.under_pressure is False
    assert material_blunders
    assert any(sample.san == "Bxc4" for sample in material_blunders[0].samples)
    assert report.time_pressure.games_with_usable_clock == 1
    assert report.time_pressure.moves_with_usable_clock == 19


def test_batch_ignores_games_without_player() -> None:
    report = analyze_player_games([PGN_PATH.read_text(encoding="utf-8")], "Unknown")

    assert report.games_analyzed == 0
    assert report.errors_total == 0
    assert report.warnings


def test_time_pressure_tracks_low_clock_and_sustained_run() -> None:
    game = parse_pgn("""[White "Alice"]
[Black "Bob"]
[Result "*"]
[TimeControl "180+2"]

1. e4 { [%clk 0:00:19] } e5 { [%clk 0:00:20] }
2. Nf3 { [%clk 0:00:18] } Nc6 { [%clk 0:00:20] }
3. Bc4 { [%clk 0:00:17] } Nf6 { [%clk 0:00:20] }
4. d3 { [%clk 0:00:16] } *
""")

    contexts = _time_pressure_contexts(game, "white")

    assert contexts[3].low_clock_before is False
    assert contexts[3].low_clock_after is True
    assert contexts[5].low_clock_before is True
    assert contexts[7].sustained_pressure is True


def test_time_pressure_detects_large_deficit_and_recent_depletion() -> None:
    game = parse_pgn("""[White "Alice"]
[Black "Bob"]
[Result "*"]
[TimeControl "180+2"]

1. e4 { [%clk 0:01:00] [%emt 0:00:02] } e5 { [%clk 0:01:30] }
2. Nf3 { [%clk 0:00:40] [%emt 0:00:22] } Nc6 { [%clk 0:01:28] }
3. Bc4 { [%clk 0:00:39] [%emt 0:00:02] } Nf6 { [%clk 0:01:27] }
4. d3 { [%clk 0:00:38] [%emt 0:00:02] } *
""")

    contexts = _time_pressure_contexts(game, "white")

    assert contexts[3].long_think_depletion is True
    assert contexts[5].large_time_deficit_before is True
    assert contexts[5].under_pressure is True
    assert contexts[7].large_time_deficit_before is True
    assert contexts[7].sustained_pressure is True
