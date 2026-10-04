import json
from dataclasses import asdict, dataclass, field

import chess

from .analysis import PIECE_VALUES, _best_capture_gain, analyze_position

NAME_VALUES = {"pawn": 1, "knight": 3, "bishop": 3, "rook": 5, "queen": 9, "king": 100}

KIND_FORK = "fork_opportunity"
KIND_EXCHANGE = "pending_exchange"
KIND_LATENT = "latent_attack"


@dataclass
class PositionContext:
    kind: str
    motif: str
    actor: str
    target_square: str | None
    target_value: int
    note: str
    suggested_uci: str | None = None
    related: list[str] = field(default_factory=list)
    ttl_plies: int = 10
    created_ply: int = 0
    last_confirmed_ply: int = 0
    status: str = "active"

    @classmethod
    def from_dict(cls, payload: dict) -> "PositionContext":
        return cls(**{key: value for key, value in payload.items() if key in cls.__dataclass_fields__})


def _detect_fork_opportunities(board: chess.Board, color: chess.Color) -> list[dict]:
    found: list[dict] = []
    best_by_landing: dict[chess.Square, dict] = {}
    for move in board.legal_moves:
        piece = board.piece_at(move.from_square)
        if piece is None or piece.color != color or piece.piece_type != chess.KNIGHT:
            continue
        after = board.copy(stack=False)
        after.push(move)
        landing = move.to_square
        targets: dict[str, int] = {}
        royal = False
        for hit in after.attacks(landing):
            if after.color_at(hit) != (not color):
                continue
            piece_type = after.piece_type_at(hit)
            if piece_type == chess.KING:
                royal = True
                continue
            gain = _best_capture_gain(after, hit, color)
            if gain >= 1:
                targets[chess.square_name(hit)] = gain
        if not ((royal and targets) or len(targets) >= 2):
            continue
        best = max(targets.values(), default=0)
        if best < 1:
            continue
        threat = _best_capture_gain(after, landing, not color)
        if threat > 0 and best - threat < 3:
            continue
        note = (
            f"коневая вилка {board.san(move)}: выгодные цели "
            + ", ".join(f"{name}(+{gain} чистыми)" for name, gain in sorted(targets.items()))
            + (" + шах королю" if royal else "")
        )
        record = {
            "kind": KIND_FORK,
            "motif": "FORK",
            "actor": chess.square_name(move.from_square),
            "target_square": chess.square_name(landing),
            "target_value": best,
            "note": note,
            "suggested_uci": move.uci(),
            "related": sorted(targets),
            "ttl_plies": 8,
        }
        current = best_by_landing.get(landing)
        if current is None or record["target_value"] > current["target_value"]:
            best_by_landing[landing] = record
    found.extend(best_by_landing.values())
    return found


def _detect_pending_exchanges(board: chess.Board, color: chess.Color, analysis) -> list[dict]:
    side = "white" if color == chess.WHITE else "black"
    out: list[dict] = []
    for piece in analysis.pieces:
        if piece.color == side or piece.piece in {"king", "pawn"}:
            continue
        if piece.state not in {"CONTESTED", "EXPOSED"}:
            continue
        square = chess.parse_square(piece.square)
        value = NAME_VALUES[piece.piece]
        attackers = list(board.attackers(color, square))
        if not attackers:
            continue
        cheapest = min(attackers, key=lambda s: PIECE_VALUES[board.piece_type_at(s)])
        attacker_value = PIECE_VALUES[board.piece_type_at(cheapest)]
        if value - attacker_value < -1:
            continue
        out.append({
            "kind": KIND_EXCHANGE,
            "motif": "EXCHANGE",
            "actor": chess.square_name(cheapest),
            "target_square": piece.square,
            "target_value": value,
            "note": f"назревает размен: {chess.piece_name(board.piece_type_at(cheapest))} на {chess.square_name(cheapest)} против {piece.piece} {piece.square}",
            "suggested_uci": None,
            "related": [piece.square],
            "ttl_plies": 6,
        })
    out.sort(key=lambda item: -item["target_value"])
    return out[:3]


def _detect_latent_attacks(board: chess.Board, color: chess.Color, analysis, busy_targets: set[str]) -> list[dict]:
    side = "white" if color == chess.WHITE else "black"
    out: list[dict] = []
    for piece in analysis.pieces:
        if piece.color == side or piece.piece == "king" or piece.square in busy_targets:
            continue
        square = chess.parse_square(piece.square)
        if _best_capture_gain(board, square, color) > 0:
            continue
        attackers = list(board.attackers(color, square))
        if not attackers:
            continue
        cheapest = min(attackers, key=lambda s: PIECE_VALUES[board.piece_type_at(s)])
        attacker_value = PIECE_VALUES[board.piece_type_at(cheapest)]
        value = NAME_VALUES[piece.piece]
        if attacker_value > value + 6:
            continue
        out.append({
            "kind": KIND_LATENT,
            "motif": "PRESSURE",
            "actor": chess.square_name(cheapest),
            "target_square": piece.square,
            "target_value": value,
            "note": f"цель {piece.piece} на {piece.square} атакована, но пока защищена; атака держится",
            "suggested_uci": None,
            "related": [],
            "ttl_plies": 10,
        })
    out.sort(key=lambda item: -item["target_value"])
    return out[:3]


def detect_contexts(board: chess.Board) -> list[dict]:
    color = board.turn
    analysis = analyze_position(board.fen())
    forks = _detect_fork_opportunities(board, color)
    exchanges = _detect_pending_exchanges(board, color, analysis)
    busy = {record["target_square"] for record in exchanges}
    latent = _detect_latent_attacks(board, color, analysis, busy)
    return [*forks, *exchanges, *latent]


def _plausible(board: chess.Board, context: PositionContext) -> bool:
    color = board.turn
    actor = board.piece_at(chess.parse_square(context.actor)) if context.actor else None
    target = board.piece_at(chess.parse_square(context.target_square)) if context.target_square else None
    if context.kind == KIND_FORK:
        return actor is not None and actor.color == color and actor.piece_type == chess.KNIGHT
    if context.kind == KIND_EXCHANGE:
        return actor is not None and actor.color == color and target is not None and target.color != color
    return actor is not None and actor.color == color and (target is None or target.color != color)


class ContextLedger:
    """Параллельные контексты позиции, живущие между полуходами."""

    def __init__(self, contexts: list[PositionContext] | None = None) -> None:
        self.contexts: list[PositionContext] = contexts or []

    @classmethod
    def loads(cls, payload: str | None) -> "ContextLedger":
        if not payload:
            return cls()
        try:
            raw = json.loads(payload)
        except ValueError:
            return cls()
        return cls([PositionContext.from_dict(item) for item in raw if isinstance(item, dict)])

    def dumps(self) -> str:
        return json.dumps([asdict(item) for item in self.contexts], ensure_ascii=False)

    def active(self) -> list[PositionContext]:
        return [item for item in self.contexts if item.status == "active"]

    def export(self) -> list[dict]:
        return [asdict(item) for item in self.active()]

    def update(self, board: chess.Board) -> None:
        ply = board.ply()
        side = "white" if board.turn == chess.WHITE else "black"
        detected = detect_contexts(board)
        fork_motives = {
            motif.actor
            for motif in analyze_position(board.fen()).motifs
            if motif.code == "FORK" and motif.side == side
        }
        for context in self.contexts:
            if context.status != "active":
                continue
            if context.target_square in fork_motives and context.kind == KIND_FORK:
                context.status = "realized"
                continue
            match = next(
                (
                    record
                    for record in detected
                    if record["kind"] == context.kind
                    and record["actor"] == context.actor
                    and record["target_square"] == context.target_square
                ),
                None,
            )
            if match is not None:
                context.last_confirmed_ply = ply
                context.suggested_uci = match["suggested_uci"]
                context.note = match["note"]
                context.target_value = max(context.target_value, match["target_value"])
                detected.remove(match)
                continue
            if not _plausible(board, context):
                context.status = "cancelled"
        for context in self.contexts:
            if context.status == "active" and ply - context.last_confirmed_ply > context.ttl_plies:
                context.status = "expired"
        for record in detected:
            self.contexts.append(
                PositionContext.from_dict({**record, "created_ply": ply, "last_confirmed_ply": ply})
            )
        self.contexts = [item for item in self.contexts if item.status == "active" or ply - item.last_confirmed_ply < 60]
