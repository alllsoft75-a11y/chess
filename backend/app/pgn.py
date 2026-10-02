import io
import re

import chess.pgn

from .analysis import PIECE_NAMES, PIECE_VALUES
from .models import CaptureChain, CaptureEvent, GameHeaders, ParsedGame, TimelineNode

CLOCK_RE = re.compile(r"\[%clk\s+(\d+):(\d{2}):(\d{2}(?:\.\d+)?)\]")
ELAPSED_RE = re.compile(r"\[%emt\s+(\d+):(\d{2}):(\d{2}(?:\.\d+)?)\]")


def _seconds(match: re.Match[str] | None) -> float | None:
    if match is None:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _integer(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _time_control(value: str | None) -> tuple[float | None, float | None]:
    if not value or value in {"-", "?"} or ":" in value:
        return None, None
    match = re.fullmatch(r"(?:(\d+)/)?(\d+)(?:\+(\d+(?:\.\d+)?))?", value)
    if not match:
        return None, None
    _, initial, increment = match.groups()
    return float(initial), float(increment or 0)


def _capture_chain(events: list[CaptureEvent]) -> CaptureChain:
    white_gain = sum(event.captured_value for event in events if event.side == "white")
    black_gain = sum(event.captured_value for event in events if event.side == "black")
    balance = white_gain - black_gain
    if balance == 0:
        kind = "EQUAL_EXCHANGE"
        headline = "Равноценная цепочка взятий"
    elif balance > 0:
        kind = "WHITE_MATERIAL_GAIN"
        headline = "Материальный выигрыш белых"
    else:
        kind = "BLACK_MATERIAL_GAIN"
        headline = "Материальный выигрыш чёрных"

    white_parts = [f"{event.captured_piece} +{event.captured_value}" for event in events if event.side == "white"]
    black_parts = [f"{event.captured_piece} +{event.captured_value}" for event in events if event.side == "black"]
    message = (
        f"Белые взяли: {', '.join(white_parts) or 'ничего'} (всего {white_gain}). "
        f"Чёрные взяли: {', '.join(black_parts) or 'ничего'} (всего {black_gain}). "
        f"Баланс цепочки: {balance:+d} в пользу белых."
    )
    return CaptureChain(
        start_ply=events[0].ply,
        end_ply=events[-1].ply,
        events=events,
        white_gain=white_gain,
        black_gain=black_gain,
        balance=balance,
        kind=kind,
        headline=headline,
        message=message,
    )


def parse_pgn(text: str) -> ParsedGame:
    stream = io.StringIO(text.lstrip("\ufeff"))
    game = chess.pgn.read_game(stream)
    if game is None:
        raise ValueError("PGN не содержит партии")

    board = game.board()
    headers = game.headers
    initial_seconds, increment_seconds = _time_control(headers.get("TimeControl"))
    previous_clock: dict[bool, float | None] = {
        chess.WHITE: initial_seconds,
        chess.BLACK: initial_seconds,
    }
    timeline = [
        TimelineNode(
            ply=0,
            move_number=board.fullmove_number,
            side="initial",
            fen=board.fen(),
        )
    ]
    warnings: list[str] = []
    capture_chains: list[CaptureChain] = []
    current_captures: list[CaptureEvent] = []

    for ply, node in enumerate(game.mainline(), start=1):
        move = node.move
        side = board.turn
        san = board.san(move)
        mover = board.piece_at(move.from_square)
        is_capture = board.is_capture(move)
        captured_square = move.to_square
        if board.is_en_passant(move):
            captured_square = move.to_square + (-8 if side == chess.WHITE else 8)
        captured = board.piece_at(captured_square) if is_capture else None
        if is_capture and mover and captured:
            current_captures.append(
                CaptureEvent(
                    ply=ply,
                    move_number=(ply + 1) // 2,
                    side="white" if side == chess.WHITE else "black",
                    san=san,
                    uci=move.uci(),
                    from_square=chess.square_name(move.from_square),
                    to_square=chess.square_name(move.to_square),
                    attacker_piece=PIECE_NAMES[mover.piece_type],
                    captured_piece=PIECE_NAMES[captured.piece_type],
                    captured_value=PIECE_VALUES[captured.piece_type],
                )
            )
        elif current_captures:
            capture_chains.append(_capture_chain(current_captures))
            current_captures = []
        board.push(move)
        comment = node.comment.strip() or None
        clock = _seconds(CLOCK_RE.search(comment or ""))
        elapsed = _seconds(ELAPSED_RE.search(comment or ""))
        estimated = False

        if elapsed is None and clock is not None and previous_clock[side] is not None and increment_seconds is not None:
            elapsed = max(0.0, previous_clock[side] + increment_seconds - clock)
            estimated = True
        if clock is not None:
            previous_clock[side] = clock

        timeline.append(
            TimelineNode(
                ply=ply,
                move_number=(ply + 1) // 2,
                side="white" if side == chess.WHITE else "black",
                san=san,
                uci=move.uci(),
                fen=board.fen(),
                clock_seconds=clock,
                elapsed_seconds=elapsed,
                elapsed_is_estimated=estimated,
                comment=comment,
            )
        )

    if current_captures:
        capture_chains.append(_capture_chain(current_captures))

    if len(timeline) == 1:
        warnings.append("В PGN не найдено ходов")
    if not any(node.elapsed_seconds is not None for node in timeline):
        warnings.append("Временные данные отсутствуют: доступен только равномерный режим")

    return ParsedGame(
        headers=GameHeaders(
            event=headers.get("Event"),
            site=headers.get("Site"),
            date=headers.get("Date"),
            white=headers.get("White"),
            black=headers.get("Black"),
            white_elo=_integer(headers.get("WhiteElo")),
            black_elo=_integer(headers.get("BlackElo")),
            result=headers.get("Result"),
            time_control=headers.get("TimeControl"),
            initial_time_seconds=initial_seconds,
            increment_seconds=increment_seconds,
            opening=headers.get("Opening"),
        ),
        timeline=timeline,
        capture_chains=capture_chains,
        warnings=warnings,
    )
