import chess

from .models import EpisodeResponse
from .transition import analyze_move


def _captured_square(board: chess.Board, move: chess.Move) -> chess.Square | None:
    if not board.is_capture(move):
        return None
    if board.is_en_passant(move):
        return move.to_square + (-8 if board.turn == chess.WHITE else 8)
    return move.to_square


def analyze_episode(fen: str, first_uci: str, second_uci: str) -> EpisodeResponse:
    try:
        board = chess.Board(fen)
        first_move = chess.Move.from_uci(first_uci)
    except ValueError as error:
        raise ValueError(f"Некорректный первый ход: {error}") from error
    if first_move not in board.legal_moves:
        raise ValueError(f"Первый ход {first_uci} нелегален")

    first_origin = first_move.from_square
    first_target = first_move.to_square
    first_capture_square = _captured_square(board, first_move)
    first = analyze_move(board.fen(), first_uci)
    board.push(first_move)

    try:
        second_move = chess.Move.from_uci(second_uci)
    except ValueError as error:
        raise ValueError(f"Некорректный второй ход: {error}") from error
    if second_move not in board.legal_moves:
        raise ValueError(f"Второй ход {second_uci} нелегален")

    second_capture_square = _captured_square(board, second_move)
    second = analyze_move(board.fen(), second_uci)
    local_reply = second_capture_square in {first_target, first_origin, first_capture_square}
    both_capture = first.action == "CAPTURE" and second.action == "CAPTURE"
    recaptures_mover = second_capture_square == first_target

    first_side_net = first.captured_value - (second.captured_value if recaptures_mover else 0)
    second_side_net = -first_side_net
    subjects = sorted(
        {
            chess.square_name(square)
            for square in [first_origin, first_target, first_capture_square, second_move.from_square, second_move.to_square, second_capture_square]
            if square is not None
        }
    )

    first_created_check = not first.before.position.is_check and first.after.position.is_check
    second_parried_check = first.after.position.is_check and not second.after.position.is_check

    if first_created_check and second_parried_check and not both_capture:
        kind = "CHECK_PARRIED"
        headline = "Шах и ответ"
        message = (
            f"{first.san} впервые создало шах. {second.san} немедленно парировало угрозу; "
            "эпизод шаха завершён."
        )
    elif both_capture and recaptures_mover:
        if first_side_net == 0:
            kind = "EQUAL_EXCHANGE"
            headline = "Равноценный размен"
            message = (
                f"{first.san}: взято +{first.captured_value}; {second.san}: атакующая фигура стоимостью "
                f"{second.captured_value} потеряна. Материальный итог 0."
            )
        elif first_side_net < 0:
            kind = "UNFAVORABLE_EXCHANGE"
            headline = "Невыгодный размен"
            message = (
                f"{first.san}: получено +{first.captured_value}, но после {second.san} потеряна фигура "
                f"стоимостью {second.captured_value}. Материальный итог для первой стороны: {first_side_net}."
            )
        else:
            kind = "FAVORABLE_EXCHANGE"
            headline = "Выгодный размен"
            message = (
                f"{first.san}: получено +{first.captured_value}, ответным {second.san} потеряно "
                f"{second.captured_value}. Материальный итог: +{first_side_net}."
            )
    elif first.action == "CAPTURE" and second.action != "CAPTURE":
        if first.material_outlook == "UNFAVORABLE":
            kind = "POTENTIAL_SACRIFICE"
            headline = "Возможная жертва или ошибка"
            message = (
                f"{first.san} берёт материал стоимостью {first.captured_value}, но атакующая фигура стоит "
                f"{first.mover_value} и доступна для взятия. {second.san} не завершает этот эпизод."
            )
        else:
            kind = "UNANSWERED_CAPTURE"
            headline = "Взятие без немедленного ответа"
            message = f"{first.san} принесло материал +{first.captured_value}; ответ {second.san} не вернул материал сразу."
    elif both_capture and local_reply:
        kind = "CAPTURE_SEQUENCE"
        headline = "Серия взятий"
        message = (
            f"Последовали два локально связанных взятия: {first.san} (+{first.captured_value}) и "
            f"{second.san} (+{second.captured_value} для другой стороны)."
        )
    elif first.action == "CAPTURE" and first.material_outlook == "UNFAVORABLE":
        kind = "POTENTIAL_SACRIFICE"
        headline = "Возможная жертва или ошибка"
        message = (
            f"{first.san} берёт материал стоимостью {first.captured_value}, но атакующая фигура стоит "
            f"{first.mover_value} и доступна для немедленного взятия. Дальнейший смысл пока не установлен."
        )
    else:
        kind = "ACTION_RESPONSE"
        headline = "Действие и ответ"
        message = f"{first.san}, затем {second.san}. Материально завершённый размен не обнаружен."

    return EpisodeResponse(
        kind=kind,
        headline=headline,
        message=message,
        first=first,
        second=second,
        first_side_net=first_side_net,
        second_side_net=second_side_net,
        subjects=subjects,
    )
