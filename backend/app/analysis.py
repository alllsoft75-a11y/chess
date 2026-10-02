from functools import lru_cache

import chess

from .models import (
    ActivityAssessment,
    AnalyzePositionResponse,
    Motif,
    PassedPawnAssessment,
    PieceAssessment,
    PositionInfo,
    PositionObservation,
    SideSituation,
    SituationSummary,
    SquareControl,
)

PIECE_NAMES = {
    chess.PAWN: "пешка",
    chess.KNIGHT: "конь",
    chess.BISHOP: "слон",
    chess.ROOK: "ладья",
    chess.QUEEN: "ферзь",
    chess.KING: "король",
}
PIECE_GENDERS = {
    chess.PAWN: "feminine",
    chess.KNIGHT: "masculine",
    chess.BISHOP: "masculine",
    chess.ROOK: "feminine",
    chess.QUEEN: "masculine",
    chess.KING: "masculine",
}
STATE_PRIORITY = {"CRITICAL": 0, "EXPOSED": 1, "CONTESTED": 2, "WATCH": 3, "SAFE": 4}
PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}


def _square_names(squares: chess.SquareSet | list[chess.Square]) -> list[str]:
    return [chess.square_name(square) for square in sorted(squares)]


def _legal_attackers(board: chess.Board, color: chess.Color, target: chess.Square) -> list[chess.Square]:
    legal: list[chess.Square] = []
    for source in board.attackers(color, target):
        candidate = board.copy(stack=False)
        candidate.turn = color
        move = chess.Move(source, target)
        if candidate.is_legal(move):
            legal.append(source)
    return legal


def _best_capture_gain(board: chess.Board, target: chess.Square, attacker: chess.Color) -> int:
    occupant = board.piece_at(target)
    if occupant is None or occupant.color == attacker:
        return 0

    candidate = board.copy(stack=False)
    candidate.turn = attacker
    gains: list[int] = []
    for source in candidate.attackers(attacker, target):
        move = chess.Move(source, target)
        if not candidate.is_legal(move):
            continue
        after = candidate.copy(stack=False)
        after.push(move)
        captured_value = PIECE_VALUES[occupant.piece_type]
        opponent_reply = _best_capture_gain(after, target, not attacker)
        gains.append(captured_value - max(0, opponent_reply))
    return max([0, *gains])


def _is_tolerably_safe(after: chess.Board, target: chess.Square, color: chess.Color) -> bool:
    moved_piece = after.piece_at(target)
    if moved_piece is None or moved_piece.color != color:
        return False

    attackers = after.attackers(not color, target)
    if not attackers:
        return True

    defenders = after.attackers(color, target)
    if not defenders:
        return False

    cheapest_attacker = min(PIECE_VALUES[after.piece_type_at(square)] for square in attackers)
    return cheapest_attacker >= PIECE_VALUES[moved_piece.piece_type]


def _safe_moves(board: chess.Board, source: chess.Square, color: chess.Color) -> list[chess.Square]:
    candidate = board.copy(stack=False)
    candidate.turn = color
    destinations: set[chess.Square] = set()
    for move in candidate.generate_legal_moves(from_mask=chess.BB_SQUARES[source]):
        after = candidate.copy(stack=False)
        after.push(move)
        if _is_tolerably_safe(after, move.to_square, color):
            destinations.add(move.to_square)
    return sorted(destinations)


def _effective_controllers(board: chess.Board, color: chess.Color, target: chess.Square) -> list[chess.Square]:
    effective: list[chess.Square] = []
    for source in board.attackers(color, target):
        if not board.is_pinned(color, source) or target in board.pin(color, source):
            effective.append(source)
    return effective


def _square_control(board: chess.Board, square: chess.Square) -> SquareControl:
    white_attackers = list(board.attackers(chess.WHITE, square))
    black_attackers = list(board.attackers(chess.BLACK, square))
    white_effective = _effective_controllers(board, chess.WHITE, square)
    black_effective = _effective_controllers(board, chess.BLACK, square)
    white_pawn_control = any(board.piece_type_at(source) == chess.PAWN for source in white_attackers)
    black_pawn_control = any(board.piece_type_at(source) == chess.PAWN for source in black_attackers)
    balance = len(white_effective) - len(black_effective)
    tension = min(len(white_effective), len(black_effective))
    occupant = board.piece_at(square)
    occupied_by = None
    if occupant:
        occupied_by = f"{'white' if occupant.color == chess.WHITE else 'black'}_{chess.piece_name(occupant.piece_type)}"

    name = chess.square_name(square)
    explanation = (
        f"Поле {name}: белые контролируют {len(white_effective)}, "
        f"чёрные — {len(black_effective)}."
    )
    if tension:
        explanation += " Поле спорное: его контролируют обе стороны."
    elif balance > 0:
        explanation += " Перевес контроля у белых."
    elif balance < 0:
        explanation += " Перевес контроля у чёрных."
    else:
        explanation += " Эффективный контроль отсутствует или уравновешен."

    return SquareControl(
        square=name,
        white_attackers=_square_names(white_attackers),
        black_attackers=_square_names(black_attackers),
        white_effective=_square_names(white_effective),
        black_effective=_square_names(black_effective),
        white_pawn_control=white_pawn_control,
        black_pawn_control=black_pawn_control,
        balance=balance,
        tension=tension,
        occupied_by=occupied_by,
        explanation=explanation,
    )


def _form(piece_type: chess.PieceType, masculine: str, feminine: str) -> str:
    return feminine if PIECE_GENDERS[piece_type] == "feminine" else masculine


def _piece_moves(board: chess.Board, source: chess.Square, color: chess.Color) -> list[chess.Move]:
    candidate = board.copy(stack=False)
    candidate.turn = color
    return list(candidate.generate_legal_moves(from_mask=chess.BB_SQUARES[source]))


def _file_pawns(board: chess.Board, file_index: int, color: chess.Color | None = None) -> list[chess.Square]:
    squares = []
    for rank in range(8):
        square = chess.square(file_index, rank)
        piece = board.piece_at(square)
        if piece and piece.piece_type == chess.PAWN and (color is None or piece.color == color):
            squares.append(square)
    return squares


def _activity(board: chess.Board, square: chess.Square) -> ActivityAssessment:
    piece = board.piece_at(square)
    if piece is None:
        raise ValueError("На анализируемом поле нет фигуры")

    moves = _piece_moves(board, square, piece.color)
    safe_moves = _safe_moves(board, square, piece.color)
    captures = [move.to_square for move in moves if board.is_capture(move)]
    checks: list[chess.Square] = []
    for move in moves:
        after = board.copy(stack=False)
        after.turn = piece.color
        after.push(move)
        if after.is_check():
            checks.append(move.to_square)

    attacked = board.attacks(square)
    supported_allies = [
        target
        for target in attacked
        if board.color_at(target) == piece.color and target != square
    ]
    center = {chess.D4, chess.E4, chess.D5, chess.E5}
    central_influence = sorted(target for target in attacked if target in center)
    features: list[str] = []
    score = len(safe_moves) * 5 + len(captures) * 7 + len(checks) * 8
    score += len(supported_allies) * 3 + len(central_influence) * 4

    if board.is_pinned(piece.color, square):
        score -= 18
        features.append("связана и ограничена защитой короля")

    if piece.piece_type == chess.KNIGHT:
        if square in center:
            score += 18
            features.append("занимает центральное поле")
        elif chess.square_file(square) in {0, 7} or chess.square_rank(square) in {0, 7}:
            if supported_allies or captures or checks:
                features.append("находится на краю, но выполняет конкретную функцию")
            else:
                score -= 10
                features.append("находится на краю и имеет мало влияния")
    elif piece.piece_type == chess.BISHOP:
        same_color_pawns = sum(
            1
            for pawn_square in board.pieces(chess.PAWN, piece.color)
            if (chess.square_file(pawn_square) + chess.square_rank(pawn_square)) % 2
            == (chess.square_file(square) + chess.square_rank(square)) % 2
        )
        if len(attacked) >= 7:
            score += 10
            features.append("работает по длинной диагонали")
        if same_color_pawns >= 4 and len(safe_moves) <= 3:
            score -= 10
            features.append("ограничена своими пешками того же цвета")
    elif piece.piece_type == chess.ROOK:
        file_index = chess.square_file(square)
        all_pawns = _file_pawns(board, file_index)
        own_pawns = _file_pawns(board, file_index, piece.color)
        if not all_pawns:
            score += 18
            features.append("занимает открытую вертикаль")
        elif not own_pawns:
            score += 10
            features.append("занимает полуоткрытую вертикаль")
        if chess.square_rank(square) == (6 if piece.color == chess.WHITE else 1):
            score += 12
            features.append("проникла на предпоследнюю горизонталь")
    elif piece.piece_type == chess.QUEEN:
        if captures or checks:
            score += 10
            features.append("участвует в непосредственных угрозах")
        if len(safe_moves) <= 3:
            score -= 8
            features.append("имеет мало безопасных полей")
    elif piece.piece_type == chess.KING:
        score = 45 + len(safe_moves) * 4
        features.append("оценивается по доступным безопасным полям, а не по центральности")
    elif piece.piece_type == chess.PAWN:
        score = 35 + len(safe_moves) * 8 + len(captures) * 6
        if central_influence:
            score += 6
            features.append("контролирует центральное поле")

    index = max(0, min(100, score))
    if index >= 70:
        state = "ACTIVE"
    elif index >= 40:
        state = "NORMAL"
    elif index >= 20:
        state = "LIMITED"
    else:
        state = "PASSIVE"

    name = PIECE_NAMES[piece.piece_type].capitalize()
    explanation = (
        f"{name} на {chess.square_name(square)}: активность {state.lower()}, индекс {index}. "
        f"Легальных ходов {len(moves)}, безопасных {len(safe_moves)}, "
        f"взятий {len(captures)}, защищаемых фигур {len(supported_allies)}."
    )
    if features:
        explanation += " " + "; ".join(feature.capitalize() for feature in features) + "."

    return ActivityAssessment(
        state=state,
        index=index,
        legal_moves=_square_names([move.to_square for move in moves]),
        safe_moves=_square_names(safe_moves),
        captures=_square_names(captures),
        checks=_square_names(checks),
        supported_allies=_square_names(supported_allies),
        central_influence=_square_names(central_influence),
        features=features,
        explanation=explanation,
    )


def _line_between(source: chess.Square, target: chess.Square) -> list[chess.Square]:
    return list(chess.SquareSet(chess.between(source, target)))


def _forks(board: chess.Board) -> list[Motif]:
    motifs: list[Motif] = []
    for source in chess.SQUARES:
        piece = board.piece_at(source)
        if piece is None:
            continue
        targets = [
            target
            for target in board.attacks(source)
            if board.color_at(target) == (not piece.color)
        ]
        if len(targets) < 2:
            continue
        target_values = {
            chess.square_name(target): PIECE_VALUES[board.piece_type_at(target)]
            for target in targets
        }
        valuable_targets = [target for target in targets if target_values[chess.square_name(target)] >= 1]
        if len(valuable_targets) < 2:
            continue
        actor_attackers = list(board.attackers(not piece.color, source))
        actor_safe = not actor_attackers
        best_target_value = max(target_values.values())
        material_potential = best_target_value if actor_safe else best_target_value - PIECE_VALUES[piece.piece_type]
        fork_name = "коневая вилка" if piece.piece_type == chess.KNIGHT else "вилка"
        safety_text = "Атакующая фигура не находится под боем." if actor_safe else "Атакующая фигура находится под боем."
        motifs.append(
            Motif(
                code="FORK",
                kind="IMMEDIATE",
                side="white" if piece.color == chess.WHITE else "black",
                actor=chess.square_name(source),
                targets=_square_names(targets),
                line=[],
                actor_piece=chess.piece_name(piece.piece_type),
                actor_safe=actor_safe,
                target_values=target_values,
                material_potential=material_potential,
                confidence=0.95,
                explanation=(
                    f"{PIECE_NAMES[piece.piece_type].capitalize()} на {chess.square_name(source)} создаёт "
                    f"{fork_name}: одновременно атакует {', '.join(f'{name} (+{value})' for name, value in target_values.items())}. "
                    f"{safety_text} Потенциал материального выигрыша: {material_potential:+d}."
                ),
            )
        )
    return motifs


def _pins(board: chess.Board) -> list[Motif]:
    motifs: list[Motif] = []
    for color in (chess.WHITE, chess.BLACK):
        king = board.king(color)
        if king is None:
            continue
        for square in board.pieces(chess.KNIGHT, color) | board.pieces(chess.BISHOP, color) | board.pieces(chess.ROOK, color) | board.pieces(chess.QUEEN, color) | board.pieces(chess.PAWN, color):
            if not board.is_pinned(color, square):
                continue
            ray = board.pin(color, square)
            attackers = [
                source
                for source in board.attackers(not color, square)
                if source in ray
            ]
            if not attackers:
                continue
            actor = attackers[0]
            motifs.append(
                Motif(
                    code="PIN",
                    kind="IMMEDIATE",
                    side="white" if not color == chess.WHITE else "black",
                    actor=chess.square_name(actor),
                    targets=[chess.square_name(square), chess.square_name(king)],
                    line=_square_names([actor, *_line_between(actor, king), king]),
                    confidence=1.0,
                    explanation=(
                        f"Фигура на {chess.square_name(square)} связана с королём на "
                        f"{chess.square_name(king)} фигурой на {chess.square_name(actor)}."
                    ),
                )
            )
    return motifs


def _batteries(board: chess.Board) -> list[Motif]:
    motifs: list[Motif] = []
    for color in (chess.WHITE, chess.BLACK):
        queens = board.pieces(chess.QUEEN, color)
        sliders = board.pieces(chess.BISHOP, color) | board.pieces(chess.ROOK, color)
        for queen in queens:
            for slider in sliders:
                between = _line_between(queen, slider)
                same_diagonal = abs(chess.square_file(queen) - chess.square_file(slider)) == abs(chess.square_rank(queen) - chess.square_rank(slider))
                same_straight = chess.square_file(queen) == chess.square_file(slider) or chess.square_rank(queen) == chess.square_rank(slider)
                slider_piece = board.piece_at(slider)
                if slider_piece is None:
                    continue
                if slider_piece.piece_type == chess.BISHOP and not same_diagonal:
                    continue
                if slider_piece.piece_type == chess.ROOK and not same_straight:
                    continue
                blockers = [square for square in between if board.piece_at(square)]
                if len(blockers) > 1:
                    continue
                blocker = blockers[0] if blockers else None
                if blocker is None:
                    file_step = (chess.square_file(slider) > chess.square_file(queen)) - (chess.square_file(slider) < chess.square_file(queen))
                    rank_step = (chess.square_rank(slider) > chess.square_rank(queen)) - (chess.square_rank(slider) < chess.square_rank(queen))
                    next_file = chess.square_file(slider) + file_step
                    next_rank = chess.square_rank(slider) + rank_step
                    if 0 <= next_file < 8 and 0 <= next_rank < 8:
                        next_square = chess.square(next_file, next_rank)
                        if board.piece_at(next_square):
                            blocker = next_square
                kind = "PATTERN" if blocker else "IMMEDIATE"
                text = f"Батарея {PIECE_NAMES[slider_piece.piece_type]}–ферзь выстроена по линии"
                if blocker:
                    blocker_piece = board.piece_at(blocker)
                    text += (
                        f", но пока перекрыта {PIECE_NAMES[blocker_piece.piece_type]} на "
                        f"{chess.square_name(blocker)}"
                    )
                motifs.append(
                    Motif(
                        code="BATTERY",
                        kind=kind,
                        side="white" if color == chess.WHITE else "black",
                        actor=chess.square_name(slider),
                        targets=[chess.square_name(queen)],
                        line=_square_names([queen, *between, slider]),
                        blocker=chess.square_name(blocker) if blocker is not None else None,
                        confidence=0.9,
                        explanation=text + ".",
                    )
                )
    return motifs


def _only_defenders(board: chess.Board) -> list[Motif]:
    motifs: list[Motif] = []
    for target in chess.SQUARES:
        piece = board.piece_at(target)
        if piece is None or piece.piece_type == chess.KING:
            continue
        defenders = list(board.attackers(piece.color, target))
        attackers = list(board.attackers(not piece.color, target))
        if len(defenders) != 1 or not attackers:
            continue
        defender = defenders[0]
        motifs.append(
            Motif(
                code="ONLY_DEFENDER",
                kind="PATTERN",
                side="white" if piece.color == chess.WHITE else "black",
                actor=chess.square_name(defender),
                targets=[chess.square_name(target)],
                line=[chess.square_name(defender), chess.square_name(target)],
                confidence=0.85,
                explanation=(
                    f"Фигура на {chess.square_name(defender)} — единственный защитник "
                    f"фигуры на {chess.square_name(target)}."
                ),
            )
        )
    return motifs


def _trapped_queens(board: chess.Board) -> list[Motif]:
    motifs: list[Motif] = []
    for color in (chess.WHITE, chess.BLACK):
        for square in board.pieces(chess.QUEEN, color):
            attackers = _legal_attackers(board, not color, square)
            if not attackers:
                continue
            safe = _safe_moves(board, square, color)
            if safe:
                continue
            motifs.append(
                Motif(
                    code="TRAPPED_QUEEN",
                    kind="IMMEDIATE",
                    side="white" if not color == chess.WHITE else "black",
                    actor=chess.square_name(attackers[0]),
                    targets=[chess.square_name(square)],
                    line=[],
                    actor_piece=chess.piece_name(board.piece_type_at(attackers[0])),
                    actor_safe=True,
                    target_values={chess.square_name(square): 9},
                    material_potential=9,
                    confidence=0.95,
                    explanation=(
                        f"Ферзь на {chess.square_name(square)} атакован и не имеет безопасного отхода. "
                        "Перед потерей следует искать максимальную материальную компенсацию."
                    ),
                )
            )
    return motifs


def _passed_pawns(board: chess.Board) -> list[PassedPawnAssessment]:
    assessments: list[PassedPawnAssessment] = []
    for color in (chess.WHITE, chess.BLACK):
        enemy_pawns = board.pieces(chess.PAWN, not color)
        for square in board.pieces(chess.PAWN, color):
            file_index = chess.square_file(square)
            rank_index = chess.square_rank(square)
            blocking_files = {value for value in (file_index - 1, file_index, file_index + 1) if 0 <= value < 8}
            blocked_by_enemy_pawn = False
            for enemy in enemy_pawns:
                if chess.square_file(enemy) not in blocking_files:
                    continue
                enemy_rank = chess.square_rank(enemy)
                if (color == chess.WHITE and enemy_rank > rank_index) or (color == chess.BLACK and enemy_rank < rank_index):
                    blocked_by_enemy_pawn = True
                    break
            if blocked_by_enemy_pawn:
                continue

            progress_rank = rank_index + 1 if color == chess.WHITE else 8 - rank_index
            moves_to_promotion = 8 - progress_rank
            promotion_square = chess.square(file_index, 7 if color == chess.WHITE else 0)
            next_square = square + (8 if color == chess.WHITE else -8)
            can_be_blockaded = 0 <= next_square < 64 and board.piece_at(next_square) is not None
            can_be_captured = bool(board.attackers(not color, square))
            values = {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.5, 5: 2.5, 6: 4.5, 7: 8.0}
            dynamic_value = values.get(progress_rank, 1.0)

            test = board.copy(stack=False)
            promotion_with_check = False
            if moves_to_promotion == 1 and not can_be_blockaded:
                test.turn = color
                promotion_move = chess.Move(square, promotion_square, promotion=chess.QUEEN)
                if promotion_move in test.legal_moves:
                    test.push(promotion_move)
                    promotion_with_check = test.is_check()

            if moves_to_promotion == 1 and promotion_with_check:
                threat_level = "PROMOTION_WITH_CHECK"
                dynamic_value = 10.0
            elif moves_to_promotion == 1:
                threat_level = "FORCED_PROMOTION" if not can_be_captured and not can_be_blockaded else "PROMOTION_THREAT"
                dynamic_value = max(dynamic_value, 9.0 if not can_be_captured else 7.0)
            elif moves_to_promotion == 2:
                threat_level = "DANGEROUS_PASSER"
            else:
                threat_level = "ADVANCED_PASSER"

            assessments.append(
                PassedPawnAssessment(
                    square=chess.square_name(square),
                    side="white" if color == chess.WHITE else "black",
                    progress_rank=progress_rank,
                    moves_to_promotion=moves_to_promotion,
                    dynamic_value=dynamic_value,
                    promotion_square=chess.square_name(promotion_square),
                    promotion_with_check=promotion_with_check,
                    can_be_captured=can_be_captured,
                    can_be_blockaded=can_be_blockaded,
                    threat_level=threat_level,
                    explanation=(
                        f"Проходная пешка на {chess.square_name(square)}: до превращения ходов {moves_to_promotion}, "
                        f"динамическая ценность {dynamic_value:g}, уровень {threat_level}."
                    ),
                )
            )
    return assessments


def _motifs(board: chess.Board) -> list[Motif]:
    motifs = [*_forks(board), *_pins(board), *_batteries(board), *_only_defenders(board), *_trapped_queens(board)]
    unique: dict[tuple[str, str, tuple[str, ...]], Motif] = {}
    for motif in motifs:
        unique[(motif.code, motif.actor, tuple(motif.targets))] = motif
    return list(unique.values())


def _assessment(board: chess.Board, square: chess.Square) -> PieceAssessment:
    piece = board.piece_at(square)
    if piece is None:
        raise ValueError("На анализируемом поле нет фигуры")

    enemy = not piece.color
    geometric_attackers = board.attackers(enemy, square)
    legal_attackers = _legal_attackers(board, enemy, square) if piece.piece_type != chess.KING else []
    defenders = board.attackers(piece.color, square)
    safe_moves = _safe_moves(board, square, piece.color)
    pinned = board.is_pinned(piece.color, square)
    in_check = piece.piece_type == chess.KING and board.is_check() and board.turn == piece.color
    exchange_loss = _best_capture_gain(board, square, enemy)

    if in_check:
        state = "CRITICAL"
        explanation = f"Король на {chess.square_name(square)} находится под шахом. Требуется немедленный ответ."
    elif exchange_loss >= PIECE_VALUES[piece.piece_type] and (
        PIECE_VALUES[piece.piece_type] >= PIECE_VALUES[chess.KNIGHT] or not safe_moves
    ):
        state = "CRITICAL"
        explanation = (
            f"{PIECE_NAMES[piece.piece_type].capitalize()} на {chess.square_name(square)} теряется при "
            f"непосредственной серии взятий. Оценка чистой потери: {exchange_loss}. "
            f"Атакующих {len(legal_attackers)}, защитников {len(defenders)}."
        )
    elif legal_attackers and not defenders:
        state = "EXPOSED"
        attacked = _form(piece.piece_type, "атакован", "атакована")
        defended = _form(piece.piece_type, "защищён", "защищена")
        explanation = (
            f"{PIECE_NAMES[piece.piece_type].capitalize()} на {chess.square_name(square)} {attacked}, "
            f"но не {defended}. Безопасных отходов: {len(safe_moves)}."
        )
    elif legal_attackers:
        state = "CONTESTED"
        explanation = (
            f"{PIECE_NAMES[piece.piece_type].capitalize()} на {chess.square_name(square)} под боем: "
            f"атакующих {len(legal_attackers)}, защитников {len(defenders)}, "
            f"безопасных отходов {len(safe_moves)}."
        )
    elif geometric_attackers:
        state = "WATCH"
        explanation = (
            f"На {PIECE_NAMES[piece.piece_type]} на {chess.square_name(square)} направлена атака, "
            "но сейчас она не реализуется легальным взятием."
        )
    elif pinned:
        state = "WATCH"
        pinned_form = _form(piece.piece_type, "связан", "связана")
        pronoun = _form(piece.piece_type, "его", "её")
        explanation = (
            f"{PIECE_NAMES[piece.piece_type].capitalize()} на {chess.square_name(square)} {pinned_form}: "
            f"{pronoun} подвижность ограничена защитой короля."
        )
    else:
        state = "SAFE"
        explanation = (
            f"{PIECE_NAMES[piece.piece_type].capitalize()} на {chess.square_name(square)} "
            "не находится под непосредственным легальным взятием."
        )

    return PieceAssessment(
        square=chess.square_name(square),
        color="white" if piece.color == chess.WHITE else "black",
        piece=chess.piece_name(piece.piece_type),
        state=state,
        attackers=_square_names(geometric_attackers),
        legal_attackers=_square_names(legal_attackers),
        defenders=_square_names(defenders),
        safe_moves=_square_names(safe_moves),
        pinned=pinned,
        exchange_loss=exchange_loss,
        explanation=explanation,
        activity=_activity(board, square),
    )


def _side_situation(
    board: chess.Board,
    color: chess.Color,
    pieces: list[PieceAssessment],
    motifs: list[Motif],
) -> SideSituation:
    side = "white" if color == chess.WHITE else "black"
    own = [piece for piece in pieces if piece.color == side]
    own_motifs = [motif for motif in motifs if motif.side == side]
    critical = [piece for piece in own if piece.state == "CRITICAL"]
    exposed = [piece for piece in own if piece.state == "EXPOSED"]
    active = [piece for piece in own if piece.activity.state == "ACTIVE"]
    limited = [piece for piece in own if piece.activity.state in {"LIMITED", "PASSIVE"}]
    king_square = board.king(color)
    king_attackers = list(board.attackers(not color, king_square)) if king_square is not None else []
    immediate = [motif for motif in own_motifs if motif.kind == "IMMEDIATE"]
    coordination_motifs = [motif for motif in own_motifs if motif.code in {"BATTERY", "ONLY_DEFENDER"}]

    if critical:
        defense = "CRITICAL"
    elif exposed:
        defense = "FRAGILE"
    elif limited:
        defense = "CONSTRAINED"
    else:
        defense = "STABLE"

    if any(motif.code in {"FORK", "PIN"} for motif in immediate):
        attack = "TACTICAL"
    elif immediate:
        attack = "PRESSURE"
    elif active:
        attack = "DEVELOPING"
    else:
        attack = "QUIET"

    if len(coordination_motifs) >= 2:
        coordination = "CONNECTED"
    elif coordination_motifs:
        coordination = "FORMING"
    elif len(limited) > len(active):
        coordination = "FRAGMENTED"
    else:
        coordination = "NEUTRAL"

    if board.is_check() and board.turn == color:
        king_safety = "IN_CHECK"
    elif len(king_attackers) >= 2:
        king_safety = "EXPOSED"
    elif king_attackers:
        king_safety = "WATCH"
    else:
        king_safety = "STABLE"

    if defense in {"CRITICAL", "FRAGILE"}:
        posture = "DEFENDING"
    elif attack in {"TACTICAL", "PRESSURE"}:
        posture = "ATTACKING"
    elif len(active) >= 2 and len(limited) <= 1:
        posture = "ACTIVE"
    elif len(limited) >= 2:
        posture = "RESTRICTED"
    else:
        posture = "BALANCED"

    evidence: list[str] = []
    if critical:
        evidence.append("критические фигуры: " + ", ".join(piece.square for piece in critical))
    if exposed:
        evidence.append("незащищённые фигуры: " + ", ".join(piece.square for piece in exposed))
    if active:
        evidence.append("активные фигуры: " + ", ".join(piece.square for piece in active))
    if immediate:
        evidence.append("непосредственные мотивы: " + ", ".join(motif.code for motif in immediate))
    if king_attackers:
        evidence.append("давление на короля: " + ", ".join(_square_names(king_attackers)))

    return SideSituation(
        side=side,
        posture=posture,
        attack=attack,
        defense=defense,
        coordination=coordination,
        king_safety=king_safety,
        evidence=evidence,
    )


def _situation(board: chess.Board, pieces: list[PieceAssessment], motifs: list[Motif]) -> SituationSummary:
    white = _side_situation(board, chess.WHITE, pieces, motifs)
    black = _side_situation(board, chess.BLACK, pieces, motifs)
    critical = [piece for piece in pieces if piece.state == "CRITICAL"]
    immediate = [motif for motif in motifs if motif.kind == "IMMEDIATE"]

    if board.is_check():
        context = "FORCED_RESPONSE"
        headline = "Сторона хода находится под шахом: требуется немедленный ответ."
    elif critical:
        context = "TACTICAL_CRISIS"
        headline = "Позиция содержит непосредственную потерю материала или критическую угрозу."
    elif immediate:
        context = "TACTICAL_TENSION"
        headline = "В позиции действуют непосредственные тактические мотивы."
    elif white.posture == "ATTACKING" and black.posture == "DEFENDING":
        context = "WHITE_PRESSURE"
        headline = "Белые оказывают давление, чёрные решают защитные задачи."
    elif black.posture == "ATTACKING" and white.posture == "DEFENDING":
        context = "BLACK_PRESSURE"
        headline = "Чёрные оказывают давление, белые решают защитные задачи."
    else:
        context = "MANEUVERING"
        headline = "Позиция носит маневренный характер без немедленной форсированной развязки."

    focus = set()
    for piece in critical:
        focus.add(piece.square)
        focus.update(piece.legal_attackers)
        focus.update(piece.defenders)
    for motif in immediate:
        focus.add(motif.actor)
        focus.update(motif.targets)

    narratives = [headline]
    if white.evidence:
        narratives.append("Белые: " + "; ".join(white.evidence) + ".")
    if black.evidence:
        narratives.append("Чёрные: " + "; ".join(black.evidence) + ".")

    return SituationSummary(
        context=context,
        headline=headline,
        white=white,
        black=black,
        focus_squares=sorted(focus),
        narratives=narratives,
    )


def _position_key(fen: str) -> str:
    parts = fen.split()
    return " ".join(parts[:4])


@lru_cache(maxsize=50000)
def _analyze_position_cached(position_key: str) -> AnalyzePositionResponse:
    try:
        board = chess.Board(position_key + " 0 1")
    except ValueError as error:
        raise ValueError(f"Некорректный FEN: {error}") from error

    pieces = [_assessment(board, square) for square in chess.SQUARES if board.piece_at(square)]
    pieces.sort(key=lambda item: (STATE_PRIORITY[item.state], item.color, item.square))
    squares = [_square_control(board, square) for square in chess.SQUARES]
    motifs = _motifs(board)
    passed_pawns = _passed_pawns(board)
    observations = [
        PositionObservation(
            category="THREAT" if item.state in {"CRITICAL", "EXPOSED"} else "DEFENSE",
            severity="critical" if item.state == "CRITICAL" else "warning",
            title=f"{item.state}: {item.square}",
            message=item.explanation,
            subjects=[item.square, *item.legal_attackers, *item.defenders],
        )
        for item in pieces
        if item.state != "SAFE"
    ]

    observations.extend(
        PositionObservation(
            category="COORDINATION" if motif.code in {"BATTERY", "ONLY_DEFENDER"} else "OPPORTUNITY",
            severity="warning" if motif.kind == "IMMEDIATE" else "info",
            title=f"{motif.code} · {motif.kind}",
            message=motif.explanation,
            subjects=[motif.actor, *motif.targets, *([motif.blocker] if motif.blocker else [])],
        )
        for motif in motifs
    )

    return AnalyzePositionResponse(
        position=PositionInfo(
            fen=board.fen(),
            side_to_move="white" if board.turn == chess.WHITE else "black",
            is_check=board.is_check(),
            is_checkmate=board.is_checkmate(),
        ),
        pieces=pieces,
        squares=squares,
        motifs=motifs,
        passed_pawns=passed_pawns,
        observations=observations,
        situation=_situation(board, pieces, motifs),
    )


def analyze_position(fen: str) -> AnalyzePositionResponse:
    return _analyze_position_cached(_position_key(fen))


def analysis_cache_info():
    return _analyze_position_cached.cache_info()


def clear_analysis_cache() -> None:
    _analyze_position_cached.cache_clear()
