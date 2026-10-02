from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .analysis import analyze_position
from .batch import analyze_player_games
from .episode import analyze_episode
from .models import (
    AnalyzeEpisodeRequest,
    AnalyzeMoveRequest,
    AnalyzeMoveResponse,
    AnalyzePositionRequest,
    AnalyzePositionResponse,
    BatchAnalyzeRequest,
    BatchPlayerReport,
    EpisodeResponse,
    CreateGameRequest,
    GameTurnRequest,
    ExperienceEpisode,
    GameTurnResponse,
    LearnedRule,
    ParsePgnRequest,
    PersonalityProfile,
    ParsedGame,
    ProgramMoveRequest,
    ProgramMoveResponse,
    RuleProposalRequest,
    RuleProposalResponse,
    SavedGameMoveRequest,
    SavedGameResponse,
    SavedGameSummary,
    TournamentReport,
    TournamentRequest,
)
from .pgn import parse_pgn
from .personalities import list_personalities
from .program import choose_program_move, play_turn
from .storage import (
    approve_rule_proposal,
    backtest_rule_proposal,
    create_game,
    create_rule_proposal,
    get_game,
    init_db,
    learn_from_experience,
    list_games,
    list_learned_rules,
    list_rule_proposals,
    record_experience,
    play_saved_player_move,
    play_saved_program_move,
    play_saved_turn,
)
from .tournament import run_round_robin
from .transition import analyze_move

app = FastAPI(title="Chess Vision API", version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    init_db()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/positions/analyze", response_model=AnalyzePositionResponse)
def analyze(request: AnalyzePositionRequest) -> AnalyzePositionResponse:
    try:
        return analyze_position(request.fen)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/moves/analyze", response_model=AnalyzeMoveResponse)
def analyze_transition(request: AnalyzeMoveRequest) -> AnalyzeMoveResponse:
    try:
        return analyze_move(request.fen, request.move)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/episodes/analyze", response_model=EpisodeResponse)
def analyze_two_ply(request: AnalyzeEpisodeRequest) -> EpisodeResponse:
    try:
        return analyze_episode(request.fen, request.first_move, request.second_move)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/v1/personalities", response_model=list[PersonalityProfile])
def personalities() -> list[PersonalityProfile]:
    return list_personalities()


@app.get("/api/v1/personalities/{personality_id}/rules", response_model=list[LearnedRule])
def personality_rules(personality_id: str) -> list[LearnedRule]:
    return list_learned_rules(personality_id)


@app.post("/api/v1/personalities/{personality_id}/experiences", response_model=LearnedRule | None)
def personality_experience(personality_id: str, episode: ExperienceEpisode) -> LearnedRule | None:
    recorded = record_experience(
        personality_id, episode.motif, episode.context, episode.decision, episode.consequence, episode.material_delta
    )
    return learn_from_experience(recorded)


@app.post("/api/v1/tournaments/round-robin", response_model=TournamentReport)
def round_robin(request: TournamentRequest) -> TournamentReport:
    return run_round_robin(request.max_fullmoves, request.games_per_pair)


@app.post("/api/v1/saved-games", response_model=SavedGameResponse)
def start_saved_game(request: CreateGameRequest) -> SavedGameResponse:
    try:
        return create_game(request.player_name, request.player_color, request.personality_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/v1/saved-games", response_model=list[SavedGameSummary])
def saved_games() -> list[SavedGameSummary]:
    return list_games()


@app.get("/api/v1/saved-games/{game_id}", response_model=SavedGameResponse)
def saved_game(game_id: int) -> SavedGameResponse:
    try:
        return get_game(game_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/v1/saved-games/{game_id}/player-move", response_model=SavedGameResponse)
def saved_player_move(game_id: int, request: SavedGameMoveRequest) -> SavedGameResponse:
    try:
        return play_saved_player_move(game_id, request.move)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/saved-games/{game_id}/program-move", response_model=SavedGameResponse)
def saved_program_move(game_id: int) -> SavedGameResponse:
    try:
        return play_saved_program_move(game_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/saved-games/{game_id}/turn", response_model=SavedGameResponse)
def saved_turn(game_id: int, request: SavedGameMoveRequest) -> SavedGameResponse:
    try:
        return play_saved_turn(game_id, request.move)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/rule-proposals", response_model=RuleProposalResponse)
def propose_rule(request: RuleProposalRequest) -> RuleProposalResponse:
    return create_rule_proposal(request.title, request.description, request.rule_json)


@app.get("/api/v1/rule-proposals", response_model=list[RuleProposalResponse])
def rule_proposals() -> list[RuleProposalResponse]:
    return list_rule_proposals()


@app.post("/api/v1/rule-proposals/{proposal_id}/backtest", response_model=RuleProposalResponse)
def backtest_proposal(proposal_id: int) -> RuleProposalResponse:
    try:
        return backtest_rule_proposal(proposal_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/v1/rule-proposals/{proposal_id}/approve", response_model=RuleProposalResponse)
def approve_proposal(proposal_id: int) -> RuleProposalResponse:
    try:
        return approve_rule_proposal(proposal_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/play/program-move", response_model=ProgramMoveResponse)
def program_move(request: ProgramMoveRequest) -> ProgramMoveResponse:
    try:
        return choose_program_move(request.fen)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/play/turn", response_model=GameTurnResponse)
def game_turn(request: GameTurnRequest) -> GameTurnResponse:
    try:
        return play_turn(request.fen, request.move)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/batch/analyze", response_model=BatchPlayerReport)
def analyze_batch(request: BatchAnalyzeRequest) -> BatchPlayerReport:
    return analyze_player_games(request.pgns, request.player)


@app.post("/api/v1/games/parse", response_model=ParsedGame)
def parse_game(request: ParsePgnRequest) -> ParsedGame:
    try:
        return parse_pgn(request.pgn)
    except (ValueError, UnicodeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=422, detail=f"Не удалось разобрать PGN: {error}") from error
