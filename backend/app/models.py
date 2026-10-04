from __future__ import annotations

from pydantic import BaseModel, Field


class GameHeaders(BaseModel):
    event: str | None = None
    site: str | None = None
    date: str | None = None
    white: str | None = None
    black: str | None = None
    white_elo: int | None = None
    black_elo: int | None = None
    result: str | None = None
    time_control: str | None = None
    initial_time_seconds: float | None = None
    increment_seconds: float | None = None
    opening: str | None = None


class TimelineNode(BaseModel):
    ply: int
    move_number: int
    side: str
    san: str | None = None
    uci: str | None = None
    fen: str
    clock_seconds: float | None = None
    elapsed_seconds: float | None = None
    elapsed_is_estimated: bool = False
    comment: str | None = None


class CaptureEvent(BaseModel):
    ply: int
    move_number: int
    side: str
    san: str
    uci: str
    from_square: str
    to_square: str
    attacker_piece: str
    captured_piece: str
    captured_value: int


class CaptureChain(BaseModel):
    start_ply: int
    end_ply: int
    events: list[CaptureEvent]
    white_gain: int
    black_gain: int
    balance: int
    kind: str
    headline: str
    message: str


class ParsedGame(BaseModel):
    headers: GameHeaders
    timeline: list[TimelineNode]
    capture_chains: list[CaptureChain] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ParsePgnRequest(BaseModel):
    pgn: str = Field(min_length=1)


class AnalyzePositionRequest(BaseModel):
    fen: str = Field(min_length=1)


class AnalyzeMoveRequest(BaseModel):
    fen: str = Field(min_length=1)
    move: str = Field(min_length=4, max_length=5)


class AnalyzeEpisodeRequest(BaseModel):
    fen: str = Field(min_length=1)
    first_move: str = Field(min_length=4, max_length=5)
    second_move: str = Field(min_length=4, max_length=5)


class PositionInfo(BaseModel):
    fen: str
    side_to_move: str
    is_check: bool
    is_checkmate: bool


class ActivityAssessment(BaseModel):
    state: str
    index: int
    legal_moves: list[str]
    safe_moves: list[str]
    captures: list[str]
    checks: list[str]
    supported_allies: list[str]
    central_influence: list[str]
    features: list[str]
    explanation: str


class PieceAssessment(BaseModel):
    square: str
    color: str
    piece: str
    state: str
    attackers: list[str]
    legal_attackers: list[str]
    defenders: list[str]
    safe_moves: list[str]
    pinned: bool
    exchange_loss: int
    explanation: str
    activity: ActivityAssessment


class SquareControl(BaseModel):
    square: str
    white_attackers: list[str]
    black_attackers: list[str]
    white_effective: list[str]
    black_effective: list[str]
    white_pawn_control: bool
    black_pawn_control: bool
    balance: int
    tension: int
    occupied_by: str | None
    explanation: str


class Motif(BaseModel):
    code: str
    kind: str
    side: str
    actor: str
    targets: list[str]
    line: list[str]
    blocker: str | None = None
    actor_piece: str | None = None
    actor_safe: bool | None = None
    target_values: dict[str, int] = Field(default_factory=dict)
    target_gains: dict[str, int] = Field(default_factory=dict)
    material_potential: int = 0
    confidence: float
    explanation: str


class PassedPawnAssessment(BaseModel):
    square: str
    side: str
    progress_rank: int
    moves_to_promotion: int
    dynamic_value: float
    promotion_square: str
    promotion_with_check: bool
    can_be_captured: bool
    can_be_blockaded: bool
    threat_level: str
    explanation: str


class PositionObservation(BaseModel):
    category: str
    severity: str
    title: str
    message: str
    subjects: list[str]


class SideSituation(BaseModel):
    side: str
    posture: str
    attack: str
    defense: str
    coordination: str
    king_safety: str
    evidence: list[str]


class SituationSummary(BaseModel):
    context: str
    headline: str
    white: SideSituation
    black: SideSituation
    focus_squares: list[str]
    narratives: list[str]


class AnalyzePositionResponse(BaseModel):
    position: PositionInfo
    pieces: list[PieceAssessment]
    squares: list[SquareControl]
    motifs: list[Motif]
    passed_pawns: list[PassedPawnAssessment]
    observations: list[PositionObservation]
    situation: SituationSummary


class TransitionEvent(BaseModel):
    code: str
    severity: str
    subjects: list[str]
    before: str | int | None = None
    after: str | int | None = None
    message: str


class SituationChange(BaseModel):
    category: str
    impact: str
    headline: str
    message: str
    subjects: list[str]
    evidence: list[str]


class AnalyzeMoveResponse(BaseModel):
    move: str
    san: str
    action: str
    action_text: str
    mover_piece: str
    mover_value: int
    captured_piece: str | None = None
    captured_value: int = 0
    immediate_risk: int = 0
    material_outlook: str
    before: AnalyzePositionResponse
    after: AnalyzePositionResponse
    events: list[TransitionEvent]
    changes: list[SituationChange]


class BatchAnalyzeRequest(BaseModel):
    pgns: list[str] = Field(min_length=1)
    player: str = Field(min_length=1)


class TimePressureContext(BaseModel):
    clock_before_seconds: float | None = None
    clock_before_is_observed: bool = False
    clock_after_seconds: float | None = None
    opponent_clock_seconds: float | None = None
    elapsed_seconds: float | None = None
    elapsed_is_estimated: bool = False
    net_clock_depletion_seconds: float | None = None
    low_clock_before: bool = False
    low_clock_after: bool = False
    practical_pressure_before: bool = False
    practical_pressure_after: bool = False
    large_time_deficit_before: bool = False
    sustained_pressure: bool = False
    long_think_depletion: bool = False
    under_pressure: bool = False
    recently_after_pressure: bool = False


class PlayerErrorSample(BaseModel):
    game_index: int
    ply: int
    san: str
    fen_before: str
    category: str
    headline: str
    message: str
    subjects: list[str]
    timing: TimePressureContext | None = None


class ErrorAggregate(BaseModel):
    category: str
    headline: str
    count: int
    share: float
    samples: list[PlayerErrorSample]


class StrengthAggregate(BaseModel):
    category: str
    headline: str
    count: int
    samples: list[PlayerErrorSample]


class LongPauseSample(BaseModel):
    game_index: int
    ply: int
    san: str
    elapsed_seconds: float
    fen_before: str
    context: str
    headline: str


class TimePressureAggregate(BaseModel):
    games_with_usable_clock: int
    moves_with_usable_clock: int
    low_clock_moves: int
    practical_pressure_moves: int
    sustained_pressure_moves: int
    large_time_deficit_moves: int
    long_think_depletions: int
    error_moves_with_usable_clock: int
    error_moves_under_pressure: int
    error_moves_during_long_think_depletion: int
    error_moves_recently_after_pressure: int
    error_moves_under_or_recent_pressure: int
    error_move_pressure_rate: float


class BatchPlayerReport(BaseModel):
    player: str
    games_total: int
    games_analyzed: int
    moves_analyzed: int
    errors_total: int
    clean_moves: int
    clean_move_rate: float
    clean_games: int
    aggregates: list[ErrorAggregate]
    strengths: list[StrengthAggregate]
    long_pauses: list[LongPauseSample]
    time_pressure: TimePressureAggregate
    warnings: list[str]


class CreateGameRequest(BaseModel):
    player_name: str = "Player"
    player_color: str = "white"
    personality_id: str = "universal"


class SavedGameMoveRequest(BaseModel):
    move: str = Field(min_length=4, max_length=5)


class SavedGameSummary(BaseModel):
    id: int
    created_at: str
    updated_at: str
    player_name: str
    player_color: str
    personality_id: str
    result: str
    status: str
    ply_count: int
    rules_version: str


class SavedGameResponse(BaseModel):
    id: int
    fen: str
    pgn: str
    result: str
    status: str
    rules_version: str
    personality_id: str = "universal"
    player_move: MoveCandidate | None = None
    program_move: MoveCandidate | None = None
    resignation_reason: str | None = None
    utterance: str | None = None
    emotion: str | None = None


class RuleProposalRequest(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    rule_json: dict


class RuleProposalResponse(BaseModel):
    id: int
    created_at: str
    status: str
    title: str
    description: str
    rule_json: dict
    baseline_version: str
    backtest_result: dict | None = None
    approved_version: str | None = None


class PersonalityProfile(BaseModel):
    id: str
    name: str
    temperament: str
    description: str
    rating: int = 500
    weights: dict[str, float]
    risk: float
    exchange_preference: float
    initiative: float
    caution: float
    avatars: dict[str, str] = Field(default_factory=dict)


class ExperienceEpisode(BaseModel):
    id: int
    personality_id: str
    motif: str
    context: str
    decision: str
    consequence: str
    material_delta: int
    created_at: str


class LearnedRule(BaseModel):
    id: int
    personality_id: str
    pattern: str
    response: str
    weight: float
    confidence: float
    confirmations: int
    contradictions: int
    status: str


class TournamentRequest(BaseModel):
    max_fullmoves: int = Field(default=20, ge=4, le=60)
    games_per_pair: int = Field(default=1, ge=1, le=2)
    personality_ids: list[str] | None = None


class TournamentGameResult(BaseModel):
    white_id: str
    black_id: str
    result: str
    termination: str
    fullmoves: int
    technical_score: int
    pgn: str
    white_rating_before: int | None = None
    black_rating_before: int | None = None
    white_rating_after: int | None = None
    black_rating_after: int | None = None


class TournamentReport(BaseModel):
    games: list[TournamentGameResult]
    standings: list[PersonalityProfile]


class TournamentSummary(BaseModel):
    id: int
    created_at: str
    rules_version: str
    max_fullmoves: int
    games_per_pair: int
    players: list[str]
    status: str
    error: str | None = None
    total_games: int
    played_games: int


class RatingEntry(BaseModel):
    personality_id: str
    name: str
    temperament: str
    rating: int
    games: int
    wins: int
    draws: int
    losses: int
    updated_at: str | None = None


class ProgramMoveRequest(BaseModel):
    fen: str = Field(min_length=1)


class MoveCandidate(BaseModel):
    uci: str
    san: str
    score: int
    reasons: list[str]
    plan: str = ""
    expected_reply: str | None = None
    continuation: str | None = None
    expected_reply_uci: str | None = None
    continuation_uci: str | None = None


class SearchMetrics(BaseModel):
    elapsed_ms: int = 0
    legal_moves: int = 0
    root_candidates: int = 0
    analyzed_branches: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


class ProgramMoveResponse(BaseModel):
    move: MoveCandidate | None
    alternatives: list[MoveCandidate]
    fen_after: str
    game_over: bool
    result: str | None = None
    resigned: bool = False
    resignation_reason: str | None = None
    utterance: str | None = None
    emotion: str | None = None
    metrics: SearchMetrics = Field(default_factory=SearchMetrics)


class GameTurnRequest(BaseModel):
    fen: str = Field(min_length=1)
    move: str = Field(min_length=4, max_length=5)


class GameTurnResponse(BaseModel):
    player_move: MoveCandidate
    program_move: MoveCandidate | None
    fen_after: str
    game_over: bool
    result: str | None = None


class EpisodeResponse(BaseModel):
    kind: str
    headline: str
    message: str
    first: AnalyzeMoveResponse
    second: AnalyzeMoveResponse
    first_side_net: int
    second_side_net: int
    subjects: list[str]
