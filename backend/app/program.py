import threading
import time

import chess

from .analysis import PIECE_VALUES, _analyze_position_cached, _best_capture_gain, _position_key, analysis_cache_info, analyze_position
from .contexts import PositionContext
from .dialogue import generate_utterance
from .models import GameTurnResponse, MoveCandidate, PersonalityProfile, ProgramMoveResponse, SearchMetrics

CENTER = {chess.D4, chess.E4, chess.D5, chess.E5}
DEVELOPMENT_SQUARES = {
    chess.WHITE: {chess.B1, chess.G1, chess.C1, chess.F1},
    chess.BLACK: {chess.B8, chess.G8, chess.C8, chess.F8},
}
PIECE_SYMBOLS = {"pawn": "P", "knight": "N", "bishop": "B", "rook": "R", "queen": "Q", "king": "K"}

_SEARCH_LOCAL = threading.local()


def set_wide_search(enabled: bool) -> None:
    """Фоновый ponder-поток расширяет лимиты перебора; запросы работают с обычными."""
    _SEARCH_LOCAL.wide = enabled


def _widen(base: int) -> int:
    return base * 2 if getattr(_SEARCH_LOCAL, "wide", False) else base


_HOME_MINORS = {
    chess.WHITE: {chess.B1: chess.KNIGHT, chess.G1: chess.KNIGHT, chess.C1: chess.BISHOP, chess.F1: chess.BISHOP},
    chess.BLACK: {chess.B8: chess.KNIGHT, chess.G8: chess.KNIGHT, chess.C8: chess.BISHOP, chess.F8: chess.BISHOP},
}
_CASTLED_KING = {chess.WHITE: {chess.C1, chess.G1}, chess.BLACK: {chess.C8, chess.G8}}
_CENTER_FILES = (3, 4)


def _undeveloped_minors(board: chess.Board, color: chess.Color) -> int:
    count = 0
    for square, piece_type in _HOME_MINORS[color].items():
        piece = board.piece_at(square)
        if piece is not None and piece.color == color and piece.piece_type == piece_type:
            count += 1
    return count


def _opening_phase(board: chess.Board, color: chess.Color) -> bool:
    return board.fullmove_number <= 14 and _undeveloped_minors(board, color) >= 2


def _development_progress(board: chess.Board, color: chess.Color) -> tuple[int, int]:
    """Развитие: лёгкие фигуры вне дома + рокировка + центральные пешки на чужой половине."""
    home = _HOME_MINORS[color]
    developed = 0
    for square, piece_type in home.items():
        piece = board.piece_at(square)
        if piece is None or piece.color != color or piece.piece_type != piece_type:
            developed += 1
    king = board.king(color)
    if king is not None and king in _CASTLED_KING[color]:
        developed += 1
    advance_rank = 3 if color == chess.WHITE else 4
    center_pawns = sum(
        1
        for file in _CENTER_FILES
        for square in board.pieces(chess.PAWN, color)
        if chess.square_file(square) == file and chess.square_rank(square) >= advance_rank
    )
    developed += min(2, center_pawns)
    return developed, len(home)


def _pawn_push_threatens(board: chess.Board, target: chess.Square, mover_color: chess.Color) -> bool:
    """Соперник следующим пешечным толчком (в т.ч. двойным) атакует поле."""
    enemy = not mover_color
    direction = 1 if enemy == chess.WHITE else -1
    rank = chess.square_rank(target)
    file = chess.square_file(target)
    for delta in (-1, 1):
        push_file = file + delta
        if not 0 <= push_file < 8:
            continue
        attack_square = chess.square(push_file, rank - direction)
        if not 0 <= chess.square_rank(attack_square) < 8:
            continue
        blocker = board.piece_at(attack_square)
        if blocker is not None:
            continue
        source = chess.square(push_file, rank - 2 * direction)
        pawn = board.piece_at(source) if 0 <= chess.square_rank(source) < 8 else None
        if pawn is not None and pawn.color == enemy and pawn.piece_type == chess.PAWN:
            return True
        home_rank = 1 if enemy == chess.WHITE else 6
        home_square = chess.square(push_file, home_rank)
        if chess.square_rank(attack_square) == home_rank + 2 * direction:
            pawn = board.piece_at(home_square)
            middle = board.piece_at(chess.square(push_file, home_rank + direction))
            if (
                pawn is not None and pawn.color == enemy and pawn.piece_type == chess.PAWN
                and middle is None
            ):
                return True
    return False


def _material(board: chess.Board, color: chess.Color) -> int:
    return sum(len(board.pieces(piece_type, color)) * value for piece_type, value in PIECE_VALUES.items() if piece_type != chess.KING)


def _strategic_score_cached(position_key: str, color: chess.Color) -> tuple[int, tuple[str, ...]]:
    analysis = _analyze_position_cached(position_key)
    side = "white" if color == chess.WHITE else "black"
    own = [piece for piece in analysis.pieces if piece.color == side]
    enemy = [piece for piece in analysis.pieces if piece.color != side]
    score = 0
    reasons: list[str] = []

    progress_board = chess.Board(analysis.position.fen)
    progress, total = _development_progress(progress_board, color)
    if progress < total + 3:
        score += progress * 12
        if progress < total:
            reasons.append(f"дебютное развитие: выведено фигур {min(progress, total)} из {total}")

    activity = sum(piece.activity.index for piece in own)
    enemy_activity = sum(piece.activity.index for piece in enemy)
    score += (activity - enemy_activity) // 10

    active_count = sum(piece.activity.state == "ACTIVE" for piece in own)
    limited_count = sum(piece.activity.state in {"LIMITED", "PASSIVE"} for piece in own)
    score += active_count * 8 - limited_count * 4
    if active_count:
        reasons.append(f"активных фигур: {active_count}")

    center_control = 0
    for square in CENTER:
        item = analysis.squares[square]
        center_control += len(item.white_effective) - len(item.black_effective)
    score += center_control * (4 if color == chess.WHITE else -4)
    if center_control:
        reasons.append("усилен контроль центра")

    king_square = analysis.position.fen
    king = chess.Board(king_square).king(color) if king_square else None
    if king is not None:
        home_rank = 0 if color == chess.WHITE else 7
        if chess.square_rank(king) == home_rank and chess.square_file(king) in {6, 2}:
            score += 18
            reasons.append("король в безопасности после рокировки")
        elif analysis.situation.white.king_safety != "STABLE" if color == chess.WHITE else analysis.situation.black.king_safety != "STABLE":
            score -= 18
            reasons.append("король требует внимания")

    critical = [piece for piece in own if piece.state == "CRITICAL" and piece.piece != "king"]
    score -= sum(PIECE_VALUES[chess.Piece.from_symbol(PIECE_SYMBOLS[piece.piece]).piece_type] * 25 for piece in critical)
    if critical:
        reasons.append("есть критически уязвимые фигуры")

    own_passers = [pawn for pawn in analysis.passed_pawns if pawn.side == side]
    enemy_passers = [pawn for pawn in analysis.passed_pawns if pawn.side != side]
    passer_score = int(sum(pawn.dynamic_value for pawn in own_passers) * 12)
    passer_danger = int(sum(pawn.dynamic_value for pawn in enemy_passers) * 14)
    score += passer_score - passer_danger
    dangerous_enemy = [pawn for pawn in enemy_passers if pawn.moves_to_promotion <= 2]
    if own_passers:
        reasons.append(f"свои проходные: {len(own_passers)}, ценность {sum(p.dynamic_value for p in own_passers):g}")
    if dangerous_enemy:
        reasons.append(
            "опасная проходная соперника: "
            + ", ".join(f"{pawn.square} ({pawn.moves_to_promotion} до превращения)" for pawn in dangerous_enemy)
        )
    return score, tuple(reasons)


def _strategic_score(board: chess.Board, color: chess.Color) -> tuple[int, list[str]]:
    score, reasons = _strategic_score_cached(_position_key(board.fen()), color)
    return score, list(reasons)


def _cheap_order_score(board: chess.Board, move: chess.Move) -> int:
    mover = board.piece_at(move.from_square)
    score = 0
    if board.is_capture(move):
        captured = board.piece_at(move.to_square)
        if captured:
            score += PIECE_VALUES[captured.piece_type] * 40
            if mover:
                score -= PIECE_VALUES[mover.piece_type] * 5
    if board.gives_check(move):
        score += 80
    if move.to_square in CENTER:
        score += 18
    centrality = 3.5 - max(
        abs(chess.square_file(move.to_square) - 3.5),
        abs(chess.square_rank(move.to_square) - 3.5),
    )
    score += int(centrality * 8)
    if mover and move.from_square in DEVELOPMENT_SQUARES[board.turn] and mover.piece_type in {chess.KNIGHT, chess.BISHOP}:
        score += 24
    if board.is_castling(move):
        score += 55
    if move.promotion:
        score += PIECE_VALUES[move.promotion] * 50
    return score


def _mandatory_moves(board: chess.Board) -> list[chess.Move]:
    moves = list(board.legal_moves)
    analysis = analyze_position(board.fen())
    side = "white" if board.turn == chess.WHITE else "black"
    vulnerable = {
        chess.parse_square(piece.square)
        for piece in analysis.pieces
        if piece.color == side
        and piece.piece != "pawn"
        and (
            piece.state in {"EXPOSED", "CRITICAL"}
            or (piece.state == "CONTESTED" and piece.exchange_loss >= 2)
        )
    }
    mandatory = [move for move in moves if move.from_square in vulnerable]
    opponent = not board.turn
    if _mate_in_one_available(board, opponent):
        for move in moves:
            after = board.copy(stack=False)
            after.push(move)
            if not _mate_in_one_available(after, opponent):
                mandatory.append(move)
    dangerous_passers = [pawn for pawn in analysis.passed_pawns if pawn.side != side and pawn.moves_to_promotion <= 2]
    if dangerous_passers:
        passer_squares = {chess.parse_square(pawn.square) for pawn in dangerous_passers}
        promotion_squares = {chess.parse_square(pawn.promotion_square) for pawn in dangerous_passers}
        for move in moves:
            if move.to_square in passer_squares or move.to_square in promotion_squares:
                mandatory.append(move)
            else:
                after = board.copy(stack=False)
                after.push(move)
                if len(_dangerous_enemy_passers(after, board.turn)) < len([p for p in dangerous_passers if p.moves_to_promotion <= 1]):
                    mandatory.append(move)
    return list(dict.fromkeys(mandatory))


def _prefilter_moves(board: chess.Board, limit: int = 7) -> list[chess.Move]:
    moves = list(board.legal_moves)
    mandatory = _mandatory_moves(board)
    forcing = sorted(
        [move for move in moves if board.gives_check(move) or board.is_capture(move) or move.promotion],
        key=lambda move: (-_cheap_order_score(board, move), move.uci()),
    )
    quiet = sorted(
        [move for move in moves if move not in forcing],
        key=lambda move: (-_cheap_order_score(board, move), move.uci()),
    )
    selected: list[chess.Move] = []
    target = max(limit, len(mandatory))
    for move in mandatory:
        if move not in selected:
            selected.append(move)
    forcing_budget = max(3, min(4, target - len(selected)))
    for move in forcing:
        if move not in selected and sum(candidate in forcing for candidate in selected) < forcing_budget:
            selected.append(move)
    for move in quiet:
        if move not in selected:
            selected.append(move)
        if len(selected) >= target:
            break
    if len(selected) < target:
        for move in forcing:
            if move not in selected:
                selected.append(move)
            if len(selected) >= target:
                break
    return selected[:target]


def _static_candidate(board: chess.Board, move: chess.Move) -> MoveCandidate:
    color = board.turn
    san = board.san(move)
    mover = board.piece_at(move.from_square)
    captured = board.piece_at(move.to_square) if board.is_capture(move) else None
    before_material = _material(board, color) - _material(board, not color)
    before_strategy, _ = _strategic_score(board, color)
    reasons: list[str] = []
    score = 0

    material_balance = before_material
    if captured:
        gain = PIECE_VALUES[captured.piece_type]
        score += gain * 20
        reasons.append(f"взятие материала +{gain}")
        mover_value = PIECE_VALUES[mover.piece_type] if mover else 0
        is_major_exchange = captured.piece_type in {chess.QUEEN, chess.ROOK} or (mover and mover.piece_type in {chess.QUEEN, chess.ROOK})
        if is_major_exchange:
            if material_balance >= 3:
                score += 24
                reasons.append("при материальном перевесе упрощение выгодно")
            elif material_balance <= -3:
                score -= 38
                reasons.append("при материальном дефиците размен крупных фигур невыгоден")
        if material_balance <= -3 and mover_value >= gain:
            score -= 12
            reasons.append("при отставании материал следует сохранять для контригры")

    after = board.copy(stack=False)
    after.push(move)
    after_material = _material(after, color) - _material(after, not color)
    score += (after_material - before_material) * 15
    if after.is_checkmate():
        return MoveCandidate(uci=move.uci(), san=san, score=10000, reasons=["мат"], plan="немедленно завершить партию")
    if after.is_check():
        score += 24
        reasons.append("форсирующий шах")

    after_strategy, strategy_reasons = _strategic_score(after, color)
    score += after_strategy - before_strategy
    reasons.extend(strategy_reasons[:2])

    if mover and move.from_square in DEVELOPMENT_SQUARES[color] and mover.piece_type in {chess.KNIGHT, chess.BISHOP}:
        score += 18
        reasons.append("развитие фигуры с начальной позиции")
    if move.to_square in CENTER:
        score += 10
        reasons.append("фигура выходит в центр")
    if board.is_castling(move):
        score += 35
        reasons.append("рокировка и безопасность короля")

    if _opening_phase(board, color):
        undeveloped = _undeveloped_minors(board, color)
        quiet = not board.is_capture(move) and not board.gives_check(move) and not board.is_castling(move) and not move.promotion
        mover_on_home = mover is not None and _HOME_MINORS[color].get(move.from_square) == (mover.piece_type if mover else None)
        target_is_home = _HOME_MINORS[color].get(move.to_square) is not None
        if quiet and not board.is_check() and mover is not None and mover.piece_type != chess.PAWN:
            if undeveloped >= 2 and not mover_on_home:
                score -= 20
                reasons.append("темп: в дебюте приоритет у развития новых фигур")
            if target_is_home:
                score -= 28
                reasons.append("фигура возвращается на стартовое поле: потеря темпа развития")
            if mover is not None and PIECE_VALUES[mover.piece_type] >= 3 and _pawn_push_threatens(board, move.to_square, color):
                score -= 16
                reasons.append("поле простреливается пешечным толчком — темп будет потерян")

    analysis = analyze_position(after.fen())
    own_side = "white" if color == chess.WHITE else "black"
    moved = next((piece for piece in analysis.pieces if piece.color == own_side and piece.square == chess.square_name(move.to_square)), None)
    if moved:
        score += moved.activity.index // 6
        captured_value = PIECE_VALUES[captured.piece_type] if captured else 0
        if moved.state == "CRITICAL":
            threat_loss, _ = _cheapest_threat_loss(after, move.to_square, color)
            net_loss = threat_loss - captured_value
            if net_loss > 0:
                score -= net_loss * 60
                reasons.append(f"фигура остаётся под немедленной потерей (чистая {net_loss})")
                if net_loss >= 3:
                    reasons.append("ценная фигура поставлена под прямое взятие")
        elif moved.state == "SAFE":
            score += 5
            reasons.append("фигура остаётся устойчивой")

    strong_motifs = [
        motif for motif in analysis.motifs
        if motif.side == own_side and motif.actor_safe and motif.material_potential > 0
    ]
    if strong_motifs:
        best = max(strong_motifs, key=lambda motif: motif.material_potential)
        score += best.material_potential * 5
        reasons.append(f"создан реалистичный мотив {best.code} с потенциалом {best.material_potential:+d}")

    plan = "развить и согласовать фигуры"
    if captured:
        plan = "выиграть материал без потери атакующей фигуры"
    elif after.is_check():
        plan = "создать форсирующую угрозу и улучшить позицию"
    elif mover and move.from_square in DEVELOPMENT_SQUARES[color]:
        plan = "ввести новую фигуру в игру"
    return MoveCandidate(uci=move.uci(), san=san, score=score, reasons=reasons or ["улучшение координации"], plan=plan)


def _reply_candidates(board: chess.Board, limit: int = 5) -> list[MoveCandidate]:
    candidates: list[MoveCandidate] = []
    for move in _prefilter_moves(board, limit=max(limit, 5)):
        candidate = _static_candidate(board, move)
        allowed, reasons = _preflight(board, move)
        if not allowed:
            candidate = candidate.model_copy(update={
                "score": candidate.score - 1000,
                "reasons": [*reasons, *candidate.reasons],
            })
        candidates.append(candidate)
    candidates.sort(key=lambda item: (-item.score, item.uci))
    return candidates[:limit]


def _recapture_summaries(board: chess.Board, move: chess.Move) -> list[str]:
    if not board.is_capture(move):
        return []
    after = board.copy(stack=False)
    after.push(move)
    return [
        after.san(reply)
        for reply in after.legal_moves
        if after.is_capture(reply) and reply.to_square == move.to_square
    ]


def _forcing_combo(board: chess.Board, move: chess.Move) -> tuple[int, list[str], list[str]] | None:
    if not board.is_capture(move):
        return None
    color = board.turn
    mover = board.piece_at(move.from_square)
    first_target = board.piece_at(move.to_square)
    if mover is None or first_target is None:
        return None
    first = board.copy(stack=False)
    first.push(move)
    recaptures = [reply for reply in first.legal_moves if first.is_capture(reply) and reply.to_square == move.to_square]
    best: tuple[int, list[str], list[str]] | None = None
    for reply in recaptures:
        reply_san = first.san(reply)
        second = first.copy(stack=False)
        second.push(reply)
        forcing_moves = [candidate for candidate in second.legal_moves if second.gives_check(candidate)]
        for forcing in forcing_moves:
            forcing_san = second.san(forcing)
            third = second.copy(stack=False)
            third.push(forcing)
            legal_replies = list(third.legal_moves)
            if not legal_replies:
                continue
            reply_results: list[tuple[int, str, str]] = []
            for forced_reply in legal_replies:
                forced_san = third.san(forced_reply)
                fourth = third.copy(stack=False)
                fourth.push(forced_reply)
                queen_wins = [
                    finish
                    for finish in fourth.legal_moves
                    if fourth.is_capture(finish)
                    and fourth.piece_type_at(finish.to_square) == chess.QUEEN
                ]
                if not queen_wins:
                    break
                finish = max(queen_wins, key=lambda candidate: _static_candidate(fourth, candidate).score)
                finish_san = fourth.san(finish)
                fifth = fourth.copy(stack=False)
                fifth.push(finish)
                material_gain = (_material(fifth, color) - _material(fifth, not color)) - (
                    _material(board, color) - _material(board, not color)
                )
                reply_results.append((material_gain, forced_san, finish_san))
            else:
                if reply_results:
                    worst_gain = min(result[0] for result in reply_results)
                    line = [board.san(move), reply_san, forcing_san, reply_results[0][1], reply_results[0][2]]
                    ucis = [move.uci(), reply.uci(), forcing.uci()]
                    if best is None or worst_gain > best[0]:
                        best = (worst_gain, line, ucis)
    return best


def _critical_exposure(board: chess.Board, color: chess.Color) -> dict[str, int]:
    analysis = analyze_position(board.fen())
    side = "white" if color == chess.WHITE else "black"
    return {
        piece.square: PIECE_VALUES[chess.Piece.from_symbol(PIECE_SYMBOLS[piece.piece]).piece_type]
        for piece in analysis.pieces
        if piece.color == side and piece.state in {"EXPOSED", "CRITICAL"}
    }


def _mate_in_one_available(board: chess.Board, color: chess.Color) -> bool:
    candidate = board.copy(stack=False)
    candidate.turn = color
    for move in candidate.legal_moves:
        after = candidate.copy(stack=False)
        after.push(move)
        if after.is_checkmate():
            return True
    return False


def _cheapest_threat_loss(board: chess.Board, square: chess.Square, color: chess.Color) -> tuple[int, str | None]:
    """Чистый материальный выигрыш соперника в немедленной серии взятий на поле."""
    attackers = [s for s in board.attackers(not color, square)]
    if not attackers:
        return 0, None
    loss = _best_capture_gain(board, square, not color)
    if loss <= 0:
        return 0, None
    cheapest_square = min(attackers, key=lambda s: PIECE_VALUES[board.piece_type_at(s)])
    return loss, chess.square_name(cheapest_square)


def _dangerous_enemy_passers(board: chess.Board, color: chess.Color):
    side = "white" if color == chess.WHITE else "black"
    return [
        pawn for pawn in analyze_position(board.fen()).passed_pawns
        if pawn.side != side and pawn.moves_to_promotion <= 1
    ]


def _preflight(board: chess.Board, move: chess.Move) -> tuple[bool, list[str]]:
    color = board.turn
    before_exposure = _critical_exposure(board, color)
    after = board.copy(stack=False)
    after.push(move)
    reasons: list[str] = []

    if _mate_in_one_available(after, not color):
        return False, ["ход допускает мат в один"]

    after_passers = _dangerous_enemy_passers(after, color)
    if after_passers:
        promotion_squares = {pawn.promotion_square for pawn in after_passers}
        handles_passer = (
            board.is_capture(move)
            and board.piece_at(move.to_square) is not None
            and board.piece_at(move.to_square).piece_type == chess.PAWN
        ) or chess.square_name(move.to_square) in promotion_squares
        gives_forcing_mate = after.is_checkmate()
        if not handles_passer and not gives_forcing_mate:
            levels = ", ".join(f"{pawn.square}:{pawn.threat_level}" for pawn in after_passers)
            return False, [f"ход игнорирует немедленную угрозу превращения: {levels}"]

    moved_piece = after.piece_at(move.to_square)
    if moved_piece is not None:
        moved_value = PIECE_VALUES[moved_piece.piece_type]
        captured = board.piece_at(move.to_square) if board.is_capture(move) else None
        captured_value = PIECE_VALUES[captured.piece_type] if captured else 0
        moved_assessment = next(
            (piece for piece in analyze_position(after.fen()).pieces if piece.square == chess.square_name(move.to_square)),
            None,
        )
        if moved_assessment and moved_assessment.state == "CRITICAL" and moved_value > captured_value:
            combo = _forcing_combo(board, move)
            captured_was_dangerous_passer = bool(
                captured
                and captured.piece_type == chess.PAWN
                and any(pawn.square == chess.square_name(move.to_square) and pawn.moves_to_promotion <= 1 for pawn in analyze_position(board.fen()).passed_pawns)
            )
            if (combo is None or combo[0] <= 0) and not captured_was_dangerous_passer:
                return False, [f"фигура стоимостью {moved_value} остаётся под потерей ради {captured_value}"]
        if moved_value >= 3:
            loss, attacker = _cheapest_threat_loss(after, move.to_square, color)
            net_loss = loss - captured_value
            if net_loss >= 2:
                combo = _forcing_combo(board, move)
                tempo, _ = _tempo_rescue_bonus(board, move)
                captured_was_dangerous_passer = bool(
                    captured
                    and captured.piece_type == chess.PAWN
                    and any(pawn.square == chess.square_name(move.to_square) and pawn.moves_to_promotion <= 1 for pawn in analyze_position(board.fen()).passed_pawns)
                )
                if (combo is None or combo[0] <= 0) and tempo <= 0 and not captured_was_dangerous_passer:
                    return False, [
                        f"фигура стоимостью {moved_value} приходит на поле под более дешёвую атаку "
                        f"({attacker}): чистая потеря {net_loss}"
                    ]

    after_exposure = _critical_exposure(after, color)
    unresolved = [square for square, value in before_exposure.items() if value >= 3 and square in after_exposure]
    resolved_promotion = bool(
        captured
        and captured.piece_type == chess.PAWN
        and any(pawn.square == chess.square_name(move.to_square) and pawn.moves_to_promotion <= 1 for pawn in analyze_position(board.fen()).passed_pawns)
    )
    if unresolved and not resolved_promotion:
        reasons.append("не устранена угроза фигурам: " + ", ".join(unresolved))
        return False, reasons
    return True, reasons


def _forcing_reply_danger(board_after_our_move: chess.Board, reply: MoveCandidate, our_color: chess.Color) -> tuple[int, list[str]]:
    position = board_after_our_move.copy(stack=False)
    reply_move = chess.Move.from_uci(reply.uci)
    position.push(reply_move)
    analysis = analyze_position(position.fen())
    enemy_side = "white" if not our_color == chess.WHITE else "black"
    danger = 0
    reasons: list[str] = []
    for motif in analysis.motifs:
        if motif.side != enemy_side or motif.code != "FORK":
            continue
        king_targeted = any(value == 100 for value in motif.target_values.values())
        gains = motif.target_gains or {
            name: value for name, value in motif.target_values.items() if 1 <= value < 100
        }
        best_gain = max(gains.values(), default=0)
        if best_gain <= 0:
            continue
        if king_targeted:
            danger = max(danger, best_gain * 55)
            reasons.append(f"королевская вилка после {reply.san}: чистый выигрыш соперника {best_gain}")
        elif len(gains) >= 2 and motif.actor_safe:
            danger = max(danger, best_gain * 40)
            reasons.append(f"двойной удар после {reply.san} по двум выгодным целям (лучшее {best_gain})")
    if position.is_check():
        checking_square = reply_move.to_square
        checking_piece = position.piece_at(checking_square)
        if checking_piece:
            attacked_gains = [
                _best_capture_gain(position, target, not our_color)
                for target in position.attacks(checking_square)
                if position.color_at(target) == our_color and position.piece_type_at(target) != chess.KING
            ]
            real_gains = [gain for gain in attacked_gains if gain >= 1]
            if real_gains:
                loss = max(real_gains)
                danger = max(danger, loss * 55)
                reasons.append(f"шах одновременно выигрывает материал (чистыми {loss})")
    return danger, reasons


def _tempo_rescue_bonus(board: chess.Board, move: chess.Move) -> tuple[int, list[str]]:
    color = board.turn
    before = analyze_position(board.fen())
    side = "white" if color == chess.WHITE else "black"
    attacked_before = [
        piece for piece in before.pieces
        if piece.color == side and (piece.legal_attackers or piece.attackers) and piece.piece != "pawn"
    ]
    if not attacked_before:
        return 0, []
    after_board = board.copy(stack=False)
    after_board.push(move)
    moved_piece = after_board.piece_at(move.to_square)
    if moved_piece is None or PIECE_VALUES[moved_piece.piece_type] > 3:
        return 0, []
    attacked_enemy_values = [
        PIECE_VALUES[after_board.piece_type_at(target)]
        for target in after_board.attacks(move.to_square)
        if after_board.color_at(target) == (not color)
    ]
    if not attacked_enemy_values or max(attacked_enemy_values) < 9:
        return 0, []
    after = analyze_position(after_board.fen())
    moved_assessment = next((piece for piece in after.pieces if piece.square == chess.square_name(move.to_square)), None)
    if moved_assessment is None or moved_assessment.state == "CRITICAL":
        return 0, []
    unresolved = [piece for piece in attacked_before if piece.square != chess.square_name(move.from_square)]
    if not unresolved:
        return 0, []
    bonus = 145
    return bonus, [
        "темповая атака на ферзя выигрывает время для спасения атакованных фигур",
        "использована связка: геометрический контроль связанной фигуры не считается эффективным",
    ]


def _opponent_reply_set(board_after: chess.Board, limit: int = 5) -> list[MoveCandidate]:
    replies = [_static_candidate(board_after, move) for move in _prefilter_moves(board_after, limit=max(limit, 5))]
    replies.sort(key=lambda item: (-item.score, item.uci))
    selected: list[MoveCandidate] = []
    for item in replies:
        selected.append(item)
        if len(selected) >= limit:
            break
    forcing = [item for item in replies if "+" in item.san or "#" in item.san or "x" in item.san]
    for item in forcing:
        if item.uci not in {candidate.uci for candidate in selected}:
            selected.append(item)
    return selected


def _planned_candidate(board: chess.Board, move: chess.Move) -> MoveCandidate:
    allowed, preflight_reasons = _preflight(board, move)
    immediate = _static_candidate(board, move)
    if not allowed:
        return immediate.model_copy(update={
            "score": immediate.score - 1000,
            "reasons": [*preflight_reasons, *immediate.reasons],
        })
    after_safety = board.copy(stack=False)
    after_safety.push(move)
    moved_piece = after_safety.piece_at(move.to_square)
    if moved_piece and PIECE_VALUES[moved_piece.piece_type] >= 5:
        opponent_wins = _best_capture_gain(after_safety, move.to_square, after_safety.turn)
        captured = board.piece_at(move.to_square) if board.is_capture(move) else None
        captured_value = PIECE_VALUES[captured.piece_type] if captured else 0
        if opponent_wins - captured_value >= 2:
            return immediate.model_copy(update={
                "score": immediate.score - 1000,
                "reasons": [
                    f"крупная фигура теряется: получено {captured_value}, ответный выигрыш соперника {opponent_wins}",
                    *immediate.reasons,
                ],
            })
    combo = _forcing_combo(board, move)
    if combo and combo[0] > 0:
        gain, line, _ = combo
        recaptures = _recapture_summaries(board, move)
        return immediate.model_copy(update={
            "score": immediate.score + 300 + gain * 45,
            "reasons": [
                f"форсированная комбинация с материальным итогом {gain:+d}",
                f"проверены ответные взятия: {', '.join(recaptures)}" if recaptures else "ответных взятий нет",
                " → ".join(line),
                *immediate.reasons,
            ],
            "plan": "провести форсированное вскрытие линии и выиграть ферзя",
            "expected_reply": line[1],
            "continuation": line[2],
            "expected_reply_uci": combo[2][1],
            "continuation_uci": combo[2][2],
        })
    after = board.copy(stack=False)
    after.push(move)
    if after.is_game_over():
        return immediate

    replies = _opponent_reply_set(after, limit=_widen(5))
    evaluated_replies: list[tuple[int, MoveCandidate, MoveCandidate | None]] = []
    root_balance = _material(board, board.turn) - _material(board, not board.turn)
    for reply in replies:
        after_reply = after.copy(stack=False)
        after_reply.push_uci(reply.uci)
        continuations = _reply_candidates(after_reply, limit=_widen(3))
        continuation = continuations[0] if continuations else None
        continuation_gain = max(-100, min(100, continuation.score if continuation else 0))
        line_end = after_reply.copy(stack=False)
        if continuation:
            line_end.push_uci(continuation.uci)
        line_balance = _material(line_end, board.turn) - _material(line_end, not board.turn)
        line_material_loss = max(0, root_balance - line_balance)
        danger, _ = _forcing_reply_danger(after, reply, board.turn)
        effective_cost = (
            max(-150, min(200, reply.score))
            - int(continuation_gain * 0.3)
            + danger
            + line_material_loss * 95
        )
        evaluated_replies.append((effective_cost, reply, continuation))
    _, worst_reply, best_continuation = max(evaluated_replies, key=lambda item: item[0])

    reply_cost = max(-150, min(200, worst_reply.score))
    continuation_gain = max(-100, min(100, best_continuation.score if best_continuation else 0))
    fork_danger, fork_reasons = _forcing_reply_danger(after, worst_reply, board.turn)
    tempo_bonus, tempo_reasons = _tempo_rescue_bonus(board, move)
    planned_score = immediate.score - int(reply_cost * 0.65) + int(continuation_gain * 0.3) - fork_danger + tempo_bonus
    reasons = [*immediate.reasons, *fork_reasons, *tempo_reasons]
    considered_replies = ", ".join(reply.san for _, reply, _ in evaluated_replies[:8])
    reasons.append(f"проверены ответы соперника: {considered_replies}")
    reasons.append(f"ожидаемый сильный ответ: {worst_reply.san}")
    if best_continuation:
        reasons.append(f"намеченное продолжение: {best_continuation.san}")
    return immediate.model_copy(update={
        "score": planned_score,
        "reasons": reasons,
        "expected_reply": worst_reply.san,
        "continuation": best_continuation.san if best_continuation else None,
        "expected_reply_uci": worst_reply.uci,
        "continuation_uci": best_continuation.uci if best_continuation else None,
        "plan": "темпом на ферзя спасти атакованные фигуры и усилить давление" if tempo_bonus else immediate.plan,
    })


def _candidate(board: chess.Board, move: chess.Move) -> MoveCandidate:
    return _static_candidate(board, move)


def _quiescent_recovery(board: chess.Board) -> int:
    """Лучший немедленный материальный возврат: чистый выигрыш серии взятий (SEE)."""
    color = board.turn
    best = 0
    for move in board.legal_moves:
        if not board.is_capture(move):
            continue
        occupant = board.piece_at(move.to_square)
        if occupant is None or occupant.color == color:
            continue
        best = max(best, _best_capture_gain(board, move.to_square, color))
    return best


def _resignation_reason(board: chess.Board, contextual_hope: int = 0) -> str | None:
    color = board.turn
    deficit = _material(board, not color) - _material(board, color)
    recovery = _quiescent_recovery(board)
    effective_deficit = deficit - recovery
    if effective_deficit < 5:
        return None
    analysis = analyze_position(board.fen())
    side = "white" if color == chess.WHITE else "black"
    own = [piece for piece in analysis.pieces if piece.color == side]
    active = sum(piece.activity.state == "ACTIVE" for piece in own)
    critical = sum(piece.state == "CRITICAL" for piece in own)
    forcing = [move for move in board.legal_moves if board.is_capture(move) or board.gives_check(move)]
    tactical_resources = []
    for move in forcing:
        candidate = _static_candidate(board, move)
        if candidate.score >= 80:
            tactical_resources.append(candidate)
    if tactical_resources:
        return None
    hopeless_threshold = 12 if contextual_hope >= 4 else 9
    if effective_deficit >= hopeless_threshold:
        return (
            f"материальный дефицит {deficit} (с учётом немедленного возврата {recovery}: {effective_deficit}), "
            "убедительных шахов, взятий или контригры не найдено"
        )
    if contextual_hope >= 4:
        return None
    if effective_deficit >= 5 and active <= 1 and critical >= 1:
        return f"материальный дефицит {deficit} (возврат {recovery}), фигуры пассивны и сохраняется критическая слабость"
    if effective_deficit >= 5 and board.fullmove_number >= 15 and active == 0:
        return f"материальный дефицит {deficit} (возврат {recovery}), активной контригры нет"
    return None


def _damage_control_candidate(board: chess.Board) -> MoveCandidate | None:
    color = board.turn
    analysis = analyze_position(board.fen())
    side = "white" if color == chess.WHITE else "black"
    doomed_queens = [piece for piece in analysis.pieces if piece.color == side and piece.piece == "queen" and piece.state == "CRITICAL"]
    if not doomed_queens:
        return None

    options: list[tuple[int, MoveCandidate]] = []
    for move in board.legal_moves:
        after = board.copy(stack=False)
        after.push(move)
        if _mate_in_one_available(after, not color) or _dangerous_enemy_passers(after, color):
            continue
        captured = board.piece_at(move.to_square) if board.is_capture(move) else None
        compensation = PIECE_VALUES[captured.piece_type] if captured else 0
        after_analysis = analyze_position(after.fen())
        queen = next((piece for piece in after_analysis.pieces if piece.color == side and piece.piece == "queen"), None)
        expected_loss = 0 if queen is None or queen.state not in {"EXPOSED", "CRITICAL"} else 9
        net_loss = expected_loss - compensation
        candidate = _static_candidate(board, move).model_copy(update={
            "score": 500 - net_loss * 60,
            "reasons": [
                "режим минимизации ущерба: ферзь пойман",
                f"компенсация {compensation}, ожидаемая потеря {expected_loss}, чистый ущерб {net_loss}",
            ],
            "plan": "перед неизбежной потерей ферзя забрать максимально ценную фигуру",
        })
        options.append((net_loss, candidate))
    options.sort(key=lambda item: (item[0], -item[1].score, item[1].uci))
    if not options:
        return None
    best_loss = options[0][0]
    if best_loss <= 0:
        return None
    return options[0][1]


def _style_delta(board: chess.Board, move: chess.Move, personality: PersonalityProfile) -> int:
    """Отклонение хода от нейтрального вкуса: сколько характер добавляет/убавляет к его цене."""
    color = board.turn
    weights = personality.weights
    is_check = board.gives_check(move)
    is_capture = board.is_capture(move)
    captured_value = 0
    if is_capture:
        captured = board.piece_at(move.to_square)
        captured_value = PIECE_VALUES[captured.piece_type] if captured else 0
    enemy_half = chess.square_rank(move.to_square) >= 4 if color == chess.BLACK else chess.square_rank(move.to_square) <= 3
    develops = move.from_square in DEVELOPMENT_SQUARES[color] and (board.piece_type_at(move.from_square) or 0) in {chess.KNIGHT, chess.BISHOP}
    center_push = board.piece_type_at(move.from_square) == chess.PAWN and move.to_square in CENTER
    after = board.copy(stack=False)
    after.push(move)
    landing_attacked = bool(after.attackers(not color, move.to_square))
    castle = board.is_castling(move)

    delta = 0
    delta += int((personality.initiative - 1.0) * (60 * is_check + 35 * is_capture + 20 * enemy_half))
    delta += int((weights.get("tactics", 1.0) - 1.0) * 45 * is_check)
    delta += int((weights.get("center", 1.0) - 1.0) * 30 * (move.to_square in CENTER))
    delta += int((weights.get("development", 1.0) - 1.0) * 25 * develops)
    delta += int((weights.get("king_safety", 1.0) - 1.0) * (35 * castle + 15 * (not landing_attacked)))
    delta += int((weights.get("material", 1.0) - 1.0) * 14 * captured_value + (1.0 - personality.exchange_preference) * 10 * is_capture)
    delta += int((personality.caution - 1.0) * (12 * castle - 15 * enemy_half - 12 * landing_attacked))
    delta += int((personality.risk - 1.0) * 18 * (is_check or center_push))
    delta += 10 * int(center_push) * int(personality.initiative >= 1.4)
    return delta


def _personality_adjustment(
    candidate: MoveCandidate,
    personality: PersonalityProfile | None,
    board: chess.Board | None = None,
) -> MoveCandidate:
    if personality is None:
        return candidate
    reasons = list(candidate.reasons)
    text = " ".join(candidate.reasons).lower()
    hard_rejection = any(
        marker in text
        for marker in (
            "допускает мат",
            "под более дешёвую атаку",
            "остаётся под потерей",
            "не устранена угроза",
            "крупная фигура теряется",
            "игнорирует немедленную угрозу",
        )
    )
    if hard_rejection:
        return candidate
    adjustment = 0
    weights = personality.weights
    if "материал" in text or "взятие" in text:
        adjustment += int((weights.get("material", 1.0) - 1.0) * 55)
    if "актив" in text or "координац" in text:
        adjustment += int((weights.get("activity", 1.0) - 1.0) * 40)
    if "центр" in text:
        adjustment += int((weights.get("center", 1.0) - 1.0) * 35)
    if "развит" in text:
        adjustment += int((weights.get("development", 1.0) - 1.0) * 30)
    if "шах" in text or "fork" in text or "вилка" in text or "комбинац" in text:
        adjustment += int((weights.get("tactics", 1.0) - 1.0) * 50)
    if "потер" in text or "критич" in text:
        adjustment -= int(max(0.0, personality.caution - 1.0) * 60 + 12)
    if "размен" in text:
        adjustment += int((personality.exchange_preference - 1.0) * 40)
    if "мотив" in text or "форсирован" in text or "давлен" in text:
        adjustment += int((personality.risk - 1.0) * 25)

    if board is not None and len(candidate.uci) >= 4:
        try:
            move = chess.Move.from_uci(candidate.uci)
        except ValueError:
            move = None
        if move is not None and board.is_legal(move):
            delta = _style_delta(board, move, personality)
            if delta:
                adjustment += delta
                if delta >= 8:
                    reasons.append("стиль: ход в характере")
                elif delta <= -8:
                    reasons.append("стиль: ход против характера")
    if adjustment:
        reasons.append(f"характер {personality.name}: поправка {adjustment:+d}")
    return candidate.model_copy(update={"score": candidate.score + adjustment, "reasons": reasons})


def _context_adjustment(candidate: MoveCandidate, contexts: list[PositionContext]) -> MoveCandidate:
    if not contexts:
        return candidate
    bonus = 0
    reasons: list[str] = []
    for context in contexts:
        if context.suggested_uci and context.suggested_uci == candidate.uci:
            if bonus < 140:
                bonus = 140
            reasons.append(f"реализация отслеживаемого контекста: {context.note}")
            continue
        if not context.actor or not context.target_square or len(candidate.uci) < 4:
            continue
        try:
            source = chess.parse_square(context.actor)
            target = chess.parse_square(context.target_square)
            move_from = chess.parse_square(candidate.uci[:2])
            move_to = chess.parse_square(candidate.uci[2:4])
        except ValueError:
            continue
        if move_from != source or move_to == target:
            continue
        before = max(abs(chess.square_file(source) - chess.square_file(target)), abs(chess.square_rank(source) - chess.square_rank(target)))
        after = max(abs(chess.square_file(move_to) - chess.square_file(target)), abs(chess.square_rank(move_to) - chess.square_rank(target)))
        if after < before:
            step = 30 if context.kind == "fork_opportunity" else 18
            if bonus < step:
                bonus = step
            reasons.append(f"прогресс контекста ({context.kind}) к {context.target_square}")
    if bonus:
        return candidate.model_copy(update={"score": candidate.score + bonus, "reasons": [*reasons, *candidate.reasons]})
    return candidate


def choose_program_move(
    fen: str,
    planned_continuation: str | None = None,
    personality: PersonalityProfile | None = None,
    learned_rules: list[dict] | None = None,
    contexts: list[dict] | None = None,
    quiet: bool = False,
) -> ProgramMoveResponse:
    started = time.perf_counter()
    cache_before = analysis_cache_info()
    analyzed_branches = 0
    try:
        board = chess.Board(fen)
    except ValueError as error:
        raise ValueError(f"Некорректный FEN: {error}") from error
    if board.is_game_over():
        return ProgramMoveResponse(move=None, alternatives=[], fen_after=board.fen(), game_over=True, result=board.result())
    damage_control = _damage_control_candidate(board)
    if damage_control:
        alternatives = [_static_candidate(board, move) for move in board.legal_moves if move.uci != damage_control.uci]
        alternatives.sort(key=lambda item: (-item.score, item.uci))
        move_number = board.fullmove_number
        board.push_uci(damage_control.uci)
        utterance, emotion = (
            generate_utterance(personality, damage_control, move_number=move_number, mate_after=board.is_checkmate())
            if personality and not quiet
            else (None, None)
        )
        return ProgramMoveResponse(
            move=damage_control,
            alternatives=alternatives[:5],
            fen_after=board.fen(),
            game_over=board.is_game_over(),
            result=board.result() if board.is_game_over() else None,
            utterance=utterance,
            emotion=emotion,
        )
    parsed_contexts = [PositionContext.from_dict(item) for item in (contexts or []) if isinstance(item, dict)]
    active_contexts = [context for context in parsed_contexts if context.status == "active"]
    contextual_hope = max((context.target_value for context in active_contexts), default=0)
    resignation_reason = _resignation_reason(board, contextual_hope)
    if resignation_reason:
        result = "0-1" if board.turn == chess.WHITE else "1-0"
        utterance, emotion = generate_utterance(personality, None, True, resignation_reason) if personality else (None, None)
        return ProgramMoveResponse(
            move=None,
            alternatives=[],
            fen_after=board.fen(),
            game_over=True,
            result=result,
            resigned=True,
            resignation_reason=resignation_reason,
            utterance=utterance,
            emotion=emotion,
        )

    legal_moves = list(board.legal_moves)
    root_moves = _prefilter_moves(board, limit=_widen(7))
    candidate_ucis = {move.uci() for move in root_moves}
    candidate_ucis.update(
        move.uci()
        for move in legal_moves
        if _tempo_rescue_bonus(board, move)[0] > 0
    )
    if personality is not None:
        forcing_extra = sorted(
            [
                move for move in legal_moves
                if move.uci() not in candidate_ucis and (board.is_capture(move) or board.gives_check(move))
            ],
            key=lambda move: (-_cheap_order_score(board, move), move.uci()),
        )
        quiet_extra = sorted(
            [
                move for move in legal_moves
                if move.uci() not in candidate_ucis
                and not board.is_capture(move)
                and not board.gives_check(move)
                and not board.is_castling(move)
            ],
            key=lambda move: (-_cheap_order_score(board, move), move.uci()),
        )
        if personality.initiative >= 1.3:
            candidate_ucis.update(move.uci() for move in forcing_extra[:2])
        if personality.caution >= 1.3:
            candidate_ucis.update(move.uci() for move in quiet_extra[:2])
        if personality.weights.get("material", 1.0) >= 1.5:
            candidate_ucis.update(move.uci() for move in forcing_extra[:1])
    if planned_continuation and chess.Move.from_uci(planned_continuation) in board.legal_moves:
        candidate_ucis.add(planned_continuation)
    for context in active_contexts:
        if not context.suggested_uci:
            continue
        try:
            suggested = chess.Move.from_uci(context.suggested_uci)
        except ValueError:
            continue
        if suggested in board.legal_moves:
            candidate_ucis.add(context.suggested_uci)
    planned = [_planned_candidate(board, chess.Move.from_uci(uci)) for uci in candidate_ucis]
    analyzed_branches = len(planned)
    planned = [
        candidate if candidate.score <= -900 else _personality_adjustment(candidate, personality, board)
        for candidate in planned
    ]
    planned = [_context_adjustment(candidate, active_contexts) for candidate in planned]
    if learned_rules:
        adjusted = []
        situation_context = analyze_position(board.fen()).situation.context
        for candidate in planned:
            bonus = 0
            rule_reasons = []
            candidate_text = " ".join(candidate.reasons).lower()
            for rule in learned_rules:
                pattern = str(rule.get("pattern", ""))
                response = str(rule.get("response", ""))
                weight = float(rule.get("weight", 0))
                confidence = float(rule.get("confidence", 0.5))
                pattern_parts = pattern.split(":", 1)
                motif = pattern_parts[0]
                context = pattern_parts[1] if len(pattern_parts) > 1 else ""
                exact_decision = f"решения {candidate.san}" in response or f"решение {candidate.san}" in response
                structured_match = context == situation_context and (
                    exact_decision
                    or motif.lower() in candidate_text
                    or (motif == "HANGING_PIECE" and "под более дешёвую атаку" in candidate_text)
                )
                if structured_match:
                    adjustment = int(weight * confidence)
                    bonus += adjustment
                    rule_reasons.append(f"урок памяти ({motif}): {response}; поправка {adjustment:+d}")
            adjusted.append(candidate.model_copy(update={"score": candidate.score + bonus, "reasons": [*candidate.reasons, *rule_reasons]}))
        planned = adjusted
    planned.sort(key=lambda item: (-item.score, item.uci))
    color = board.turn
    deficit = _material(board, not color) - _material(board, color)
    viable = [item for item in planned if item.score > -900]
    if not viable and deficit - _quiescent_recovery(board) >= 5:
        resignation_reason = (
            f"материальный дефицит {deficit}, все рассмотренные ходы допускают мат или крупную немедленную потерю"
        )
        utterance, emotion = generate_utterance(personality, None, True, resignation_reason) if personality and not quiet else (None, None)
        return ProgramMoveResponse(
            move=None,
            alternatives=planned[:5],
            fen_after=board.fen(),
            game_over=True,
            result="0-1" if board.turn == chess.WHITE else "1-0",
            resigned=True,
            resignation_reason=resignation_reason,
            utterance=utterance,
            emotion=emotion,
        )
    chosen = (viable if viable else planned)[0]
    if planned_continuation:
        remembered = next((item for item in planned if item.uci == planned_continuation), None)
        if remembered and remembered.score >= chosen.score - 25:
            chosen = remembered.model_copy(update={
                "score": remembered.score + 12,
                "reasons": ["продолжение сохранённого микроплана", *remembered.reasons],
                "plan": f"продолжить ранее намеченную идею: {remembered.plan}",
            })
    move_number = board.fullmove_number
    board.push_uci(chosen.uci)
    utterance, emotion = (
        generate_utterance(personality, chosen, move_number=move_number, mate_after=board.is_checkmate())
        if personality and not quiet
        else (None, None)
    )
    cache_after = analysis_cache_info()
    metrics = SearchMetrics(
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        legal_moves=len(legal_moves),
        root_candidates=len(candidate_ucis),
        analyzed_branches=analyzed_branches,
        cache_hits=cache_after.hits - cache_before.hits,
        cache_misses=cache_after.misses - cache_before.misses,
    )
    alternatives = [item for item in planned if item.uci != chosen.uci][:5]
    return ProgramMoveResponse(
        move=chosen,
        alternatives=alternatives,
        fen_after=board.fen(),
        game_over=board.is_game_over(),
        result=board.result() if board.is_game_over() else None,
        utterance=utterance,
        emotion=emotion,
        metrics=metrics,
    )


def play_turn(fen: str, player_move: str) -> GameTurnResponse:
    board = chess.Board(fen)
    try:
        move = chess.Move.from_uci(player_move)
    except ValueError as error:
        raise ValueError(f"Некорректный ход: {error}") from error
    if move not in board.legal_moves:
        raise ValueError(f"Ход {player_move} нелегален")
    player_candidate = _static_candidate(board, move)
    board.push(move)
    if board.is_game_over():
        return GameTurnResponse(
            player_move=player_candidate, program_move=None, fen_after=board.fen(), game_over=True, result=board.result()
        )
    program = choose_program_move(board.fen())
    return GameTurnResponse(
        player_move=player_candidate, program_move=program.move, fen_after=program.fen_after,
        game_over=program.game_over, result=program.result,
    )
