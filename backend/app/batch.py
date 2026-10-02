import io
import statistics
from collections import defaultdict

import chess
import chess.pgn

from .models import (
    BatchPlayerReport,
    ErrorAggregate,
    LongPauseSample,
    PlayerErrorSample,
    StrengthAggregate,
    TimePressureAggregate,
    TimePressureContext,
)
from .pgn import parse_pgn
from .transition import analyze_move

ERROR_CATEGORIES = {
    "ALLOWED_MATE_IN_ONE",
    "IGNORED_MATE_THREAT",
    "IGNORED_MATERIAL_THREAT",
    "DEFENSIVE_BREAKDOWN",
    "MATERIAL_BLUNDER",
}


def _time_pressure_contexts(parsed, player_side: str) -> dict[int, TimePressureContext]:
    initial = parsed.headers.initial_time_seconds
    increment = parsed.headers.increment_seconds
    if initial is None or increment is None:
        return {}

    player_times = [
        node.elapsed_seconds
        for node in parsed.timeline[1:]
        if node.side == player_side and node.elapsed_seconds is not None
    ]
    median_time = statistics.median(player_times) if player_times else None
    low_threshold = min(initial, max(5.0, 3 * increment, min(60.0, initial * 0.1)))
    practical_threshold = min(initial, max(15.0, 6 * increment, min(90.0, initial * 0.35)))
    deficit_threshold = max(5 * increment, initial * 0.15)
    long_threshold = (
        max(3.0, median_time * 2.5, 4 * increment, initial * 0.05)
        if median_time is not None
        else None
    )
    depletion_threshold = max(2 * increment, initial * 0.03)
    clocks: dict[str, float | None] = {"white": None, "black": None}
    pressure_run = 0
    player_ordinal = 0
    last_pressure_ordinal: int | None = None
    contexts: dict[int, TimePressureContext] = {}

    for node in parsed.timeline[1:]:
        side = node.side
        opponent = "black" if side == "white" else "white"
        if side == player_side:
            player_ordinal += 1
            before = clocks[side]
            opponent_clock = clocks[opponent]
            low_before = before is not None and before <= low_threshold
            low_after = node.clock_seconds is not None and node.clock_seconds <= low_threshold
            practical_before = before is not None and before <= practical_threshold
            practical_after = node.clock_seconds is not None and node.clock_seconds <= practical_threshold
            large_deficit = (
                before is not None
                and opponent_clock is not None
                and opponent_clock - before >= deficit_threshold
                and before <= opponent_clock * 0.5
            )
            under_pressure = practical_before or large_deficit
            pressure_run = pressure_run + 1 if under_pressure else 0
            sustained = pressure_run >= 3
            net_depletion = (
                max(0.0, before - node.clock_seconds)
                if before is not None and node.clock_seconds is not None
                else None
            )
            long_depletion = (
                long_threshold is not None
                and node.elapsed_seconds is not None
                and net_depletion is not None
                and node.elapsed_seconds >= long_threshold
                and net_depletion >= depletion_threshold
            )
            recently_after = (
                not under_pressure
                and last_pressure_ordinal is not None
                and player_ordinal - last_pressure_ordinal <= 2
            )
            contexts[node.ply] = TimePressureContext(
                clock_before_seconds=before,
                clock_before_is_observed=before is not None,
                clock_after_seconds=node.clock_seconds,
                opponent_clock_seconds=opponent_clock,
                elapsed_seconds=node.elapsed_seconds,
                elapsed_is_estimated=node.elapsed_is_estimated,
                net_clock_depletion_seconds=net_depletion,
                low_clock_before=low_before,
                low_clock_after=low_after,
                practical_pressure_before=practical_before,
                practical_pressure_after=practical_after,
                large_time_deficit_before=large_deficit,
                sustained_pressure=sustained,
                long_think_depletion=long_depletion,
                under_pressure=under_pressure,
                recently_after_pressure=recently_after,
            )
            if under_pressure or sustained or long_depletion:
                last_pressure_ordinal = player_ordinal
        if node.clock_seconds is not None:
            clocks[side] = node.clock_seconds

    return contexts


def analyze_player_games(pgns: list[str], player: str) -> BatchPlayerReport:
    grouped: dict[tuple[str, str], list[PlayerErrorSample]] = defaultdict(list)
    warnings: list[str] = []
    games_analyzed = 0
    moves_analyzed = 0
    clean_moves = 0
    clean_games = 0
    strength_samples: dict[tuple[str, str], list[PlayerErrorSample]] = defaultdict(list)
    long_pauses: list[LongPauseSample] = []
    games_with_usable_clock = 0
    moves_with_usable_clock = 0
    low_clock_moves = 0
    practical_pressure_moves = 0
    sustained_pressure_moves = 0
    large_time_deficit_moves = 0
    long_think_depletions = 0
    error_moves_with_usable_clock = 0
    error_moves_under_pressure = 0
    error_moves_during_long_think_depletion = 0
    error_moves_recently_after_pressure = 0
    error_moves_under_or_recent_pressure = 0

    for game_index, pgn in enumerate(pgns):
        game = chess.pgn.read_game(io.StringIO(pgn.lstrip("\ufeff")))
        if game is None:
            warnings.append(f"Партия {game_index + 1}: PGN не разобран")
            continue
        white = game.headers.get("White", "")
        black = game.headers.get("Black", "")
        if player not in {white, black}:
            warnings.append(f"Партия {game_index + 1}: игрок {player} не найден")
            continue
        player_color = chess.WHITE if player == white else chess.BLACK
        board = game.board()
        games_analyzed += 1
        game_errors = 0
        parsed = parse_pgn(pgn)
        player_times = [
            node.elapsed_seconds
            for node in parsed.timeline[1:]
            if node.side == ("white" if player_color == chess.WHITE else "black") and node.elapsed_seconds is not None
        ]
        median_time = statistics.median(player_times) if player_times else None
        long_threshold = max(8.0, median_time * 2.5) if median_time is not None else None
        player_side = "white" if player_color == chess.WHITE else "black"
        timing_by_ply = _time_pressure_contexts(parsed, player_side)
        if timing_by_ply:
            games_with_usable_clock += 1
        elif parsed.headers.initial_time_seconds is None or parsed.headers.increment_seconds is None:
            warnings.append(f"Партия {game_index + 1}: контроль времени не поддержан; давление времени не оценивалось")
        else:
            warnings.append(f"Партия {game_index + 1}: часы игрока отсутствуют; давление времени не оценивалось")

        for ply, move in enumerate(game.mainline_moves(), start=1):
            san = board.san(move)
            if board.turn == player_color:
                result = analyze_move(board.fen(), move.uci())
                moves_analyzed += 1
                timing = timing_by_ply.get(ply)
                if timing is not None and timing.clock_before_is_observed:
                    moves_with_usable_clock += 1
                    low_clock_moves += int(timing.low_clock_before)
                    practical_pressure_moves += int(timing.practical_pressure_before)
                    sustained_pressure_moves += int(timing.sustained_pressure)
                    large_time_deficit_moves += int(timing.large_time_deficit_before)
                    long_think_depletions += int(timing.long_think_depletion)
                error_changes = [change for change in result.changes if change.category in ERROR_CATEGORIES]
                if error_changes and timing is not None and timing.clock_before_is_observed:
                    error_moves_with_usable_clock += 1
                    error_moves_under_pressure += int(timing.under_pressure)
                    error_moves_during_long_think_depletion += int(timing.long_think_depletion)
                    error_moves_recently_after_pressure += int(timing.recently_after_pressure)
                    error_moves_under_or_recent_pressure += int(
                        timing.under_pressure or timing.recently_after_pressure
                    )
                if not error_changes:
                    clean_moves += 1
                    if any(change.category in {"STRONG_FORK", "CREATED_CHECK"} for change in result.changes):
                        sample = PlayerErrorSample(
                            game_index=game_index,
                            ply=ply,
                            san=san,
                            fen_before=board.fen(),
                            category="TACTICAL_STRENGTH",
                            headline="Сильное тактическое решение",
                            message="; ".join(change.message for change in result.changes if change.impact == "positive"),
                            subjects=sorted({subject for change in result.changes if change.impact == "positive" for subject in change.subjects}),
                            timing=timing,
                        )
                        strength_samples[(sample.category, sample.headline)].append(sample)
                for change in error_changes:
                    game_errors += 1
                    sample = PlayerErrorSample(
                        game_index=game_index,
                        ply=ply,
                        san=san,
                        fen_before=board.fen(),
                        category=change.category,
                        headline=change.headline,
                        message=change.message,
                        subjects=change.subjects,
                        timing=timing,
                    )
                    grouped[(change.category, change.headline)].append(sample)
                timeline_node = parsed.timeline[ply]
                if long_threshold is not None and timeline_node.elapsed_seconds is not None and timeline_node.elapsed_seconds >= long_threshold:
                    long_pauses.append(
                        LongPauseSample(
                            game_index=game_index,
                            ply=ply,
                            san=san,
                            elapsed_seconds=timeline_node.elapsed_seconds,
                            fen_before=board.fen(),
                            context=result.before.situation.context,
                            headline=result.before.situation.headline,
                        )
                    )
            board.push(move)
        if game_errors == 0:
            clean_games += 1

    errors_total = sum(len(samples) for samples in grouped.values())
    aggregates = [
        ErrorAggregate(
            category=category,
            headline=headline,
            count=len(samples),
            share=round(len(samples) / errors_total, 4) if errors_total else 0,
            samples=samples[:10],
        )
        for (category, headline), samples in grouped.items()
    ]
    aggregates.sort(key=lambda item: (-item.count, item.category))
    strengths = [
        StrengthAggregate(category=category, headline=headline, count=len(samples), samples=samples[:10])
        for (category, headline), samples in strength_samples.items()
    ]
    if clean_moves:
        strengths.append(
            StrengthAggregate(
                category="STABLE_PLAY",
                headline="Стабильная игра без явных ошибок",
                count=clean_moves,
                samples=[],
            )
        )
    strengths.sort(key=lambda item: (-item.count, item.category))
    long_pauses.sort(key=lambda item: item.elapsed_seconds, reverse=True)
    return BatchPlayerReport(
        player=player,
        games_total=len(pgns),
        games_analyzed=games_analyzed,
        moves_analyzed=moves_analyzed,
        errors_total=errors_total,
        clean_moves=clean_moves,
        clean_move_rate=round(clean_moves / moves_analyzed, 4) if moves_analyzed else 0,
        clean_games=clean_games,
        aggregates=aggregates,
        strengths=strengths,
        long_pauses=long_pauses[:25],
        time_pressure=TimePressureAggregate(
            games_with_usable_clock=games_with_usable_clock,
            moves_with_usable_clock=moves_with_usable_clock,
            low_clock_moves=low_clock_moves,
            practical_pressure_moves=practical_pressure_moves,
            sustained_pressure_moves=sustained_pressure_moves,
            large_time_deficit_moves=large_time_deficit_moves,
            long_think_depletions=long_think_depletions,
            error_moves_with_usable_clock=error_moves_with_usable_clock,
            error_moves_under_pressure=error_moves_under_pressure,
            error_moves_during_long_think_depletion=error_moves_during_long_think_depletion,
            error_moves_recently_after_pressure=error_moves_recently_after_pressure,
            error_moves_under_or_recent_pressure=error_moves_under_or_recent_pressure,
            error_move_pressure_rate=(
                round(error_moves_under_or_recent_pressure / error_moves_with_usable_clock, 4)
                if error_moves_with_usable_clock
                else 0
            ),
        ),
        warnings=warnings,
    )
