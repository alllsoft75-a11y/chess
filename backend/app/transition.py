import chess

from .analysis import PIECE_NAMES, PIECE_VALUES, _best_capture_gain, analyze_position
from .models import (
    AnalyzeMoveResponse,
    AnalyzePositionResponse,
    SituationChange,
    TransitionEvent,
)

STATE_RANK = {"SAFE": 0, "WATCH": 1, "CONTESTED": 2, "EXPOSED": 3, "CRITICAL": 4}


def _mate_in_one_moves(fen: str, color: chess.Color) -> list[str]:
    board = chess.Board(fen)
    board.turn = color
    mating_moves: list[str] = []
    for move in board.legal_moves:
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate():
            mating_moves.append(move.uci())
    return mating_moves


def _piece_map(analysis: AnalyzePositionResponse) -> dict[str, object]:
    return {piece.square: piece for piece in analysis.pieces}


def _motif_key(motif) -> tuple[str, str, tuple[str, ...], str | None]:
    return motif.code, motif.actor, tuple(motif.targets), motif.blocker


def _subject_name(piece) -> str:
    return PIECE_NAMES[chess.Piece.from_symbol({
        "pawn": "P",
        "knight": "N",
        "bishop": "B",
        "rook": "R",
        "queen": "Q",
        "king": "K",
    }[piece.piece]).piece_type]


def _piece_events(before: AnalyzePositionResponse, after: AnalyzePositionResponse, move: chess.Move) -> list[TransitionEvent]:
    events: list[TransitionEvent] = []
    before_map = _piece_map(before)
    after_map = _piece_map(after)
    moved_from = chess.square_name(move.from_square)
    moved_to = chess.square_name(move.to_square)

    for square in sorted(set(before_map) & set(after_map)):
        old = before_map[square]
        new = after_map[square]
        if old.color != new.color or old.piece != new.piece:
            continue

        if STATE_RANK[new.state] > STATE_RANK[old.state]:
            lost = sorted(set(old.defenders) - set(new.defenders))
            detail = f" Потеряны защитники: {', '.join(lost)}." if lost else ""
            events.append(
                TransitionEvent(
                    code="BECAME_VULNERABLE",
                    severity="critical" if new.state == "CRITICAL" else "warning",
                    subjects=[square, *lost, moved_from, moved_to],
                    before=old.state,
                    after=new.state,
                    message=(
                        f"{_subject_name(new).capitalize()} на {square}: состояние изменилось "
                        f"с {old.state} на {new.state}.{detail}"
                    ),
                )
            )
        elif STATE_RANK[new.state] < STATE_RANK[old.state]:
            gained = sorted(set(new.defenders) - set(old.defenders))
            detail = f" Новые защитники: {', '.join(gained)}." if gained else ""
            events.append(
                TransitionEvent(
                    code="BECAME_SAFER",
                    severity="positive",
                    subjects=[square, *gained, moved_from, moved_to],
                    before=old.state,
                    after=new.state,
                    message=(
                        f"{_subject_name(new).capitalize()} на {square}: состояние улучшилось "
                        f"с {old.state} до {new.state}.{detail}"
                    ),
                )
            )

        defender_delta = len(new.defenders) - len(old.defenders)
        if defender_delta < 0 and STATE_RANK[new.state] == STATE_RANK[old.state]:
            lost = sorted(set(old.defenders) - set(new.defenders))
            events.append(
                TransitionEvent(
                    code="LOST_DEFENDER",
                    severity="warning",
                    subjects=[square, *lost, moved_from, moved_to],
                    before=len(old.defenders),
                    after=len(new.defenders),
                    message=(
                        f"{_subject_name(new).capitalize()} на {square} потеряла защиту: "
                        f"ушли {', '.join(lost)}."
                    ),
                )
            )
        elif defender_delta > 0 and STATE_RANK[new.state] == STATE_RANK[old.state]:
            gained = sorted(set(new.defenders) - set(old.defenders))
            events.append(
                TransitionEvent(
                    code="GAINED_DEFENDER",
                    severity="positive",
                    subjects=[square, *gained, moved_from, moved_to],
                    before=len(old.defenders),
                    after=len(new.defenders),
                    message=(
                        f"{_subject_name(new).capitalize()} на {square} получила дополнительную защиту: "
                        f"{', '.join(gained)}."
                    ),
                )
            )

        activity_delta = new.activity.index - old.activity.index
        if abs(activity_delta) >= 20:
            events.append(
                TransitionEvent(
                    code="GAINED_ACTIVITY" if activity_delta > 0 else "LOST_ACTIVITY",
                    severity="positive" if activity_delta > 0 else "info",
                    subjects=[square, moved_from, moved_to],
                    before=old.activity.index,
                    after=new.activity.index,
                    message=(
                        f"Активность фигуры на {square} {'выросла' if activity_delta > 0 else 'снизилась'}: "
                        f"{old.activity.index} → {new.activity.index}."
                    ),
                )
            )
    return events


def _motif_events(before: AnalyzePositionResponse, after: AnalyzePositionResponse) -> list[TransitionEvent]:
    before_motifs = {_motif_key(motif): motif for motif in before.motifs}
    after_motifs = {_motif_key(motif): motif for motif in after.motifs}
    events: list[TransitionEvent] = []

    for key in sorted(after_motifs.keys() - before_motifs.keys()):
        motif = after_motifs[key]
        events.append(
            TransitionEvent(
                code="CREATED_MOTIF",
                severity="warning" if motif.kind == "IMMEDIATE" else "info",
                subjects=[motif.actor, *motif.targets, *([motif.blocker] if motif.blocker else [])],
                after=motif.code,
                message=f"Создан мотив {motif.code}: {motif.explanation}",
            )
        )

    for key in sorted(before_motifs.keys() - after_motifs.keys()):
        motif = before_motifs[key]
        events.append(
            TransitionEvent(
                code="REMOVED_MOTIF",
                severity="positive",
                subjects=[motif.actor, *motif.targets, *([motif.blocker] if motif.blocker else [])],
                before=motif.code,
                message=f"Мотив {motif.code} исчез: {motif.explanation}",
            )
        )
    return events


def _group_changes(
    events: list[TransitionEvent],
    move: chess.Move,
    moving_side: str,
    before: AnalyzePositionResponse,
    after: AnalyzePositionResponse,
    action: str,
) -> list[SituationChange]:
    changes: list[SituationChange] = []
    moved_from = chess.square_name(move.from_square)
    moved_to = chess.square_name(move.to_square)
    moving_color = chess.WHITE if moving_side == "white" else chess.BLACK
    opponent_mates_before = _mate_in_one_moves(before.position.fen, not moving_color)
    opponent_mates_after = _mate_in_one_moves(after.position.fen, not moving_color)
    before_board_for_capture = chess.Board(before.position.fen)
    captured_on_move = before_board_for_capture.piece_at(move.to_square) if action == "CAPTURE" else None
    mover_on_move = before_board_for_capture.piece_at(move.from_square)
    captured_value_on_move = PIECE_VALUES[captured_on_move.piece_type] if captured_on_move else 0
    mover_value_on_move = PIECE_VALUES[mover_on_move.piece_type] if mover_on_move else 0
    moved_piece_after = next((piece for piece in after.pieces if piece.square == moved_to), None)
    if (
        action == "CAPTURE"
        and moved_piece_after is not None
        and moved_piece_after.exchange_loss >= mover_value_on_move
        and captured_value_on_move < mover_value_on_move
    ):
        unresolved = [
            piece.square
            for piece in after.pieces
            if piece.color == moving_side and piece.state == "CRITICAL" and piece.square != moved_to
        ]
        unresolved_text = (
            f" Кроме того, критическая проблема фигур {', '.join(unresolved)} не решена."
            if unresolved
            else ""
        )
        changes.append(
            SituationChange(
                category="MATERIAL_BLUNDER",
                impact="negative",
                headline="Грубая материальная ошибка",
                message=(
                    f"Взятие {moved_from}–{moved_to} получает материал +{captured_value_on_move}, "
                    f"но оставляет атакующую фигуру стоимостью {mover_value_on_move} под немедленным взятием. "
                    f"Ожидаемый материальный итог: {captured_value_on_move - mover_value_on_move:+d}."
                    + unresolved_text
                ),
                subjects=[moved_from, moved_to, *unresolved],
                evidence=[
                    f"получено {captured_value_on_move}",
                    f"под риском {mover_value_on_move}",
                    f"баланс {captured_value_on_move - mover_value_on_move:+d}",
                ],
            )
        )
        return changes
    if opponent_mates_after:
        mate_squares = sorted(
            {
                square
                for uci in opponent_mates_after
                for square in (uci[:2], uci[2:4])
            }
        )
        changes.append(
            SituationChange(
                category="IGNORED_MATE_THREAT" if opponent_mates_before else "ALLOWED_MATE_IN_ONE",
                impact="negative",
                headline="Грубая ошибка: допущен мат в один ход",
                message=(
                    f"Ход {moved_from}–{moved_to} не устранил матовую угрозу. "
                    if opponent_mates_before
                    else f"Ход {moved_from}–{moved_to} допустил новую матовую угрозу. "
                )
                + f"У соперника доступно: {', '.join(opponent_mates_after)}.",
                subjects=[moved_from, moved_to, *mate_squares],
                evidence=["мат в один", *opponent_mates_after],
            )
        )
    if opponent_mates_after:
        return changes

    action_phrase = "Взятие" if action == "CAPTURE" else "Ход"
    action_verb = "усилило" if action == "CAPTURE" else "усилил"
    vulnerability = [event for event in events if event.code == "BECAME_VULNERABLE"]
    created = [event for event in events if event.code == "CREATED_MOTIF"]
    removed = [event for event in events if event.code == "REMOVED_MOTIF"]
    positive = [event for event in events if event.code in {"BECAME_SAFER", "GAINED_DEFENDER", "GAINED_ACTIVITY"}]

    before_pieces = {piece.square: piece for piece in before.pieces}
    after_pieces = {piece.square: piece for piece in after.pieces}
    for event in vulnerability:
        target = after_pieces.get(event.subjects[0])
        lost = [square for square in event.subjects[1:] if square not in {moved_from, moved_to}]
        if target is not None and target.color != moving_side:
            old_target = before_pieces.get(target.square)
            created_check = target.piece == "king" and not before.position.is_check and after.position.is_check
            if created_check:
                changes.append(
                    SituationChange(
                        category="CREATED_CHECK",
                        impact="positive",
                        headline="Шах",
                        message=(
                            f"{action_phrase} {moved_from}–{moved_to} впервые создаёт непосредственную "
                            f"угрозу королю на {target.square}. Требуется обязательный ответ."
                        ),
                        subjects=event.subjects,
                        evidence=[event.code, "шаха до хода не было", "шах после хода"],
                    )
                )
                continue
            already_attacked = old_target is not None and bool(old_target.legal_attackers)
            pressure_increased = (
                already_attacked
                and old_target is not None
                and (
                    STATE_RANK[target.state] > STATE_RANK[old_target.state]
                    or len(target.legal_attackers) > len(old_target.legal_attackers)
                    or target.exchange_loss > old_target.exchange_loss
                )
            )
            before_board = chess.Board(before.position.fen)
            after_board = chess.Board(after.position.fen)
            target_square = chess.parse_square(target.square)
            persistent_targets = []
            for attacked_square in before_board.attacks(target_square) & after_board.attacks(target_square):
                before_piece = before_board.piece_at(attacked_square)
                after_piece = after_board.piece_at(attacked_square)
                if (
                    before_piece
                    and after_piece
                    and before_piece.color == after_piece.color == moving_color
                    and PIECE_VALUES[after_piece.piece_type] >= PIECE_VALUES[chess.ROOK]
                ):
                    persistent_targets.append(chess.square_name(attacked_square))
            ignored_threat = bool(persistent_targets)
            category = (
                "IGNORED_MATERIAL_THREAT"
                if ignored_threat
                else "INTENSIFIED_ATTACK"
                if pressure_increased
                else "INEFFECTIVE_ATTACK"
                if already_attacked
                else "CREATED_ATTACK"
            )
            headline = (
                "Зевок материальной угрозы"
                if ignored_threat
                else "Усиление атаки"
                if pressure_increased
                else "Атака не снимает угрозу"
                if already_attacked
                else "Атака"
            )
            prefix = (
                f"{action_phrase} {moved_from}–{moved_to} атакует фигуру, но оставляет ей взятие "
                f"ценной цели на {', '.join(persistent_targets)}. "
                if ignored_threat
                else f"{action_phrase} {moved_from}–{moved_to} усиливает уже существующее давление. "
                if pressure_increased
                else f"{action_phrase} {moved_from}–{moved_to} атакует уже активную фигуру, "
                "но не устраняет её прежнюю угрозу. "
                if already_attacked
                else f"{action_phrase} {moved_from}–{moved_to} {action_verb} давление. "
            )
            changes.append(
                SituationChange(
                    category=category,
                    impact=(
                        "negative"
                        if ignored_threat
                        else "positive"
                        if pressure_increased
                        else "context"
                        if already_attacked
                        else "positive"
                    ),
                    headline=headline,
                    message=prefix + f"Цель на {target.square}: {target.explanation}",

                    subjects=event.subjects,
                    evidence=[event.code, f"{action_phrase.lower()} {moved_from}–{moved_to}", "цель соперника"],
                )
            )
            continue

        cause = f"После ухода фигуры с {moved_from}"
        if lost:
            cause += f" и потери защитника {', '.join(lost)}"
        target_value = PIECE_VALUES[chess.Piece.from_symbol({
            "pawn": "P",
            "knight": "N",
            "bishop": "B",
            "rook": "R",
            "queen": "Q",
            "king": "K",
        }[target.piece]).piece_type] if target is not None else 0
        captured_value = 0
        if action == "CAPTURE":
            before_board = chess.Board(before.position.fen)
            captured = before_board.piece_at(move.to_square)
            if captured:
                captured_value = PIECE_VALUES[captured.piece_type]
        compensated = captured_value > target_value
        changes.append(
            SituationChange(
                category="COMPENSATED_RISK" if compensated else "DEFENSIVE_BREAKDOWN",
                impact="context" if compensated else "negative",
                headline="Допустимый риск с компенсацией" if compensated else "Ослабление защиты",
                message=(
                    f"{cause} {event.message[0].lower() + event.message[1:]} "
                    f"При этом взят материал стоимостью {captured_value}, потенциальная потеря — {target_value}."
                    if compensated
                    else f"{cause} {event.message[0].lower() + event.message[1:]}"
                ),
                subjects=event.subjects,
                evidence=[
                    event.code,
                    f"{action_phrase.lower()} {moved_from}–{moved_to}",
                    "собственная фигура",
                    f"компенсация {captured_value}" if compensated else "компенсация не установлена",
                ],
            )
        )

    if created:
        created_forks = [
            motif
            for motif in after.motifs
            if motif.code == "FORK" and any(event.after == "FORK" and motif.actor in event.subjects for event in created)
        ]
        strong_forks = [motif for motif in created_forks if motif.actor_safe and motif.material_potential > 0]
        if strong_forks:
            motif = max(strong_forks, key=lambda item: item.material_potential)
            piece_name = "Коневая" if motif.actor_piece == "knight" else "Тактическая"
            changes.append(
                SituationChange(
                    category="STRONG_FORK",
                    impact="positive",
                    headline="Очень сильный ход: вилка",
                    message=(
                        f"{piece_name} вилка с {motif.actor}: {motif.explanation} "
                        "Непосредственного нападения на атакующую фигуру нет."
                    ),
                    subjects=[motif.actor, *motif.targets],
                    evidence=["FORK", "атакующая фигура безопасна", f"потенциал {motif.material_potential:+d}"],
                )
            )
        remaining_created = [
            event
            for event in created
            if not any(motif.actor in event.subjects and event.after == "FORK" for motif in strong_forks)
        ]
        if remaining_created:
            changes.append(
                SituationChange(
                    category="CREATED_PRESSURE",
                    impact="positive",
                    headline="Созданы новые мотивы",
                    message="После хода появились: " + "; ".join(event.message for event in remaining_created[:3]),
                    subjects=sorted({subject for event in remaining_created for subject in event.subjects}),
                    evidence=[event.code for event in remaining_created],
                )
            )

    if removed:
        changes.append(
            SituationChange(
                category="REMOVED_RESOURCES",
                impact="context",
                headline="Изменение координации",
                message="После хода исчезли: " + "; ".join(event.message for event in removed[:3]),
                subjects=sorted({subject for event in removed for subject in event.subjects}),
                evidence=[event.code for event in removed],
            )
        )

    if positive:
        changes.append(
            SituationChange(
                category="IMPROVEMENT",
                impact="positive",
                headline="Позиционное улучшение",
                message="; ".join(event.message for event in positive[:3]),
                subjects=sorted({subject for event in positive for subject in event.subjects}),
                evidence=[event.code for event in positive],
            )
        )

    if not changes and events:
        changes.append(
            SituationChange(
                category="LOCAL_CHANGES",
                impact="neutral",
                headline="Локальные изменения",
                message="; ".join(event.message for event in events[:3]),
                subjects=sorted({subject for event in events[:3] for subject in event.subjects}),
                evidence=[event.code for event in events[:3]],
            )
        )
    return changes


def analyze_move(fen: str, uci: str) -> AnalyzeMoveResponse:
    try:
        board = chess.Board(fen)
        move = chess.Move.from_uci(uci)
    except ValueError as error:
        raise ValueError(f"Некорректная позиция или ход: {error}") from error
    if move not in board.legal_moves:
        raise ValueError(f"Ход {uci} нелегален в заданной позиции")

    san = board.san(move)
    mover = board.piece_at(move.from_square)
    if mover is None:
        raise ValueError("На исходном поле нет фигуры")
    is_capture = board.is_capture(move)
    action = "CAPTURE" if is_capture else "MOVE"
    captured_square = move.to_square
    if board.is_en_passant(move):
        captured_square = move.to_square + (-8 if board.turn == chess.WHITE else 8)
    captured_piece = board.piece_at(captured_square) if is_capture else None
    captured_value = PIECE_VALUES[captured_piece.piece_type] if captured_piece else 0
    mover_value = PIECE_VALUES[mover.piece_type]
    action_text = (
        f"Взятие на {chess.square_name(move.to_square)}"
        + (f": взята {PIECE_NAMES[captured_piece.piece_type]} (+{captured_value})" if captured_piece else "")
        if is_capture
        else f"Ход на {chess.square_name(move.to_square)}"
    )
    moving_side = "white" if board.turn == chess.WHITE else "black"
    before = analyze_position(board.fen())
    board.push(move)
    immediate_risk = _best_capture_gain(board, move.to_square, board.turn) if is_capture else 0
    if not is_capture:
        material_outlook = "NO_CAPTURE"
    elif immediate_risk >= mover_value:
        net = captured_value - mover_value
        material_outlook = "FAVORABLE" if net > 0 else "EQUAL" if net == 0 else "UNFAVORABLE"
    else:
        material_outlook = "GAIN"
    after = analyze_position(board.fen())
    events = [*_piece_events(before, after, move), *_motif_events(before, after)]
    priority = {"critical": 0, "warning": 1, "positive": 2, "info": 3}
    events.sort(key=lambda event: (priority.get(event.severity, 4), event.code, event.subjects))
    return AnalyzeMoveResponse(
        move=uci,
        san=san,
        action=action,
        action_text=action_text,
        mover_piece=chess.piece_name(mover.piece_type),
        mover_value=mover_value,
        captured_piece=chess.piece_name(captured_piece.piece_type) if captured_piece else None,
        captured_value=captured_value,
        immediate_risk=immediate_risk,
        material_outlook=material_outlook,
        before=before,
        after=after,
        events=events,
        changes=_group_changes(events, move, moving_side, before, after, action),
    )
