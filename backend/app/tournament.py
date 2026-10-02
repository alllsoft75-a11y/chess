from __future__ import annotations

import chess
import chess.pgn

from .analysis import PIECE_VALUES, analyze_position
from .models import TournamentGameResult, TournamentReport
from .personalities import list_personalities
from .program import choose_program_move


def _material(board: chess.Board, color: chess.Color) -> int:
    return sum(len(board.pieces(piece_type, color)) * value for piece_type, value in PIECE_VALUES.items() if piece_type != chess.KING)


def _technical_score(board: chess.Board) -> int:
    material = _material(board, chess.WHITE) - _material(board, chess.BLACK)
    analysis = analyze_position(board.fen())
    activity = sum(piece.activity.index for piece in analysis.pieces if piece.color == "white") - sum(
        piece.activity.index for piece in analysis.pieces if piece.color == "black"
    )
    critical = sum(1 for piece in analysis.pieces if piece.color == "black" and piece.state == "CRITICAL") - sum(
        1 for piece in analysis.pieces if piece.color == "white" and piece.state == "CRITICAL"
    )
    return material * 20 + activity // 10 + critical * 15


def _technical_result(score: int) -> str:
    if score >= 45:
        return "1-0"
    if score <= -45:
        return "0-1"
    return "1/2-1/2"


def play_personality_game(white, black, max_fullmoves: int) -> TournamentGameResult:
    board = chess.Board()
    game = chess.pgn.Game()
    game.headers["Event"] = "Chess Vision personality tournament"
    game.headers["White"] = white.name
    game.headers["Black"] = black.name
    node = game
    termination = "move_limit"

    while not board.is_game_over() and board.fullmove_number <= max_fullmoves:
        personality = white if board.turn == chess.WHITE else black
        decision = choose_program_move(board.fen(), personality=personality)
        if decision.resigned:
            result = decision.result or ("0-1" if board.turn == chess.WHITE else "1-0")
            termination = "resignation"
            break
        if decision.move is None:
            result = board.result()
            termination = "rules"
            break
        move = chess.Move.from_uci(decision.move.uci)
        node = node.add_variation(move)
        node.comment = f"{personality.id}; plan={decision.move.plan}; " + "; ".join(decision.move.reasons)
        board.push(move)
    else:
        result = board.result() if board.is_game_over() else "*"

    score = _technical_score(board)
    if result == "*":
        result = _technical_result(score)
        termination = "technical"
    elif termination == "move_limit":
        termination = "rules"
    game.headers["Result"] = result
    game.headers["Termination"] = termination
    return TournamentGameResult(
        white_id=white.id,
        black_id=black.id,
        result=result,
        termination=termination,
        fullmoves=board.fullmove_number - (1 if board.turn == chess.WHITE else 0),
        technical_score=score,
        pgn=str(game),
    )


def run_round_robin(max_fullmoves: int = 20, games_per_pair: int = 1) -> TournamentReport:
    personalities = list_personalities()
    ratings = {personality.id: 500 for personality in personalities}
    games: list[TournamentGameResult] = []
    for first_index, first in enumerate(personalities):
        for second in personalities[first_index + 1 :]:
            pairings = [(first, second)]
            if games_per_pair == 2:
                pairings.append((second, first))
            for white, black in pairings:
                game = play_personality_game(white, black, max_fullmoves)
                games.append(game)
                if game.result == "1-0":
                    ratings[white.id] += 2
                    ratings[black.id] -= 3
                elif game.result == "0-1":
                    ratings[black.id] += 2
                    ratings[white.id] -= 3
                else:
                    ratings[white.id] += 1
                    ratings[black.id] += 1
    standings = [personality.model_copy(update={"rating": ratings[personality.id]}) for personality in personalities]
    standings.sort(key=lambda personality: (-personality.rating, personality.name))
    return TournamentReport(games=games, standings=standings)
