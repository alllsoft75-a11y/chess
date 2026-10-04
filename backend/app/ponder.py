import sys
import threading
import time
from dataclasses import dataclass

import chess

from .contexts import ContextLedger
from .models import ProgramMoveResponse
from .personalities import PersonalityProfile
from .program import _prefilter_moves, choose_program_move, set_wide_search

PONDER_MOVES = 6
PONDER_BUDGET_SECONDS = 30.0


@dataclass
class PonderEntry:
    player_uci: str
    fen_after_player: str
    decision: ProgramMoveResponse


_ENTRIES: dict[int, list[PonderEntry]] = {}
_CANCELLED: set[int] = set()
_LOCK = threading.Lock()


def clear_game(game_id: int) -> None:
    with _LOCK:
        _ENTRIES.pop(game_id, None)
        _CANCELLED.discard(game_id)


def cancel_ponder(game_id: int) -> None:
    """Игрок походил — фоновому потоку пора останавливаться между вариантами."""
    with _LOCK:
        _CANCELLED.add(game_id)


def _cancelled(game_id: int) -> bool:
    with _LOCK:
        return game_id in _CANCELLED


def ponder_entries(game_id: int) -> list[PonderEntry]:
    with _LOCK:
        return list(_ENTRIES.get(game_id, []))


def take_pondered(game_id: int, player_uci: str, fen_after_player: str) -> PonderEntry | None:
    with _LOCK:
        entries = _ENTRIES.get(game_id, [])
        match = next(
            (entry for entry in entries if entry.player_uci == player_uci and entry.fen_after_player == fen_after_player),
            None,
        )
        if match is not None:
            _ENTRIES[game_id] = [entry for entry in entries if entry is not match]
        _CANCELLED.discard(game_id)
        return match


def _ponder_round(
    game_id: int,
    fen: str,
    expected_reply: str | None,
    continuation: str | None,
    personality: PersonalityProfile | None,
    learned_rules: list[dict] | None,
    ledger_snapshot: str,
    moves_limit: int = PONDER_MOVES,
    budget_seconds: float = PONDER_BUDGET_SECONDS,
) -> None:
    try:
        board = chess.Board(fen)
        predicted: list[chess.Move] = []
        if expected_reply:
            try:
                move = chess.Move.from_uci(expected_reply)
            except ValueError:
                move = None
            if move is not None and move in board.legal_moves:
                predicted.append(move)
        for candidate in _prefilter_moves(board, limit=5):
            if candidate not in predicted:
                predicted.append(candidate)
        predicted = predicted[:moves_limit]
        deadline = time.monotonic() + budget_seconds
        entries: list[PonderEntry] = []
        set_wide_search(True)
        try:
            for move in predicted:
                if _cancelled(game_id) or time.monotonic() > deadline:
                    break
                hypothetical = board.copy(stack=False)
                hypothetical.push(move)
                ledger = ContextLedger.loads(ledger_snapshot)
                ledger.update(hypothetical)
                decision = choose_program_move(
                    hypothetical.fen(),
                    continuation,
                    personality,
                    learned_rules,
                    contexts=ledger.export(),
                    quiet=True,
                )
                entries.append(PonderEntry(move.uci(), hypothetical.fen(), decision))
        finally:
            set_wide_search(False)
        with _LOCK:
            if game_id in _CANCELLED:
                _CANCELLED.discard(game_id)
                return
            _ENTRIES[game_id] = entries
    except Exception as error:  # pragma: no cover - защитный перехват фонового потока
        print(f"ponder failed for game {game_id}: {error}", file=sys.stderr)


def start_ponder(
    game_id: int,
    fen: str,
    expected_reply: str | None,
    continuation: str | None,
    personality: PersonalityProfile | None,
    learned_rules: list[dict] | None,
    ledger_snapshot: str,
) -> None:
    clear_game(game_id)
    thread = threading.Thread(
        target=_ponder_round,
        args=(game_id, fen, expected_reply, continuation, personality, learned_rules, ledger_snapshot),
        daemon=True,
        name=f"ponder-{game_id}",
    )
    thread.start()
