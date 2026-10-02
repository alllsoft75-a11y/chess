export type Side = 'white' | 'black' | 'initial'

export interface GameHeaders {
  event: string | null
  site: string | null
  date: string | null
  white: string | null
  black: string | null
  white_elo: number | null
  black_elo: number | null
  result: string | null
  time_control: string | null
  opening: string | null
}

export interface TimelineNode {
  ply: number
  move_number: number
  side: Side
  san: string | null
  uci: string | null
  fen: string
  clock_seconds: number | null
  elapsed_seconds: number | null
  elapsed_is_estimated: boolean
  comment: string | null
}

export interface CaptureEvent {
  ply: number
  move_number: number
  side: 'white' | 'black'
  san: string
  uci: string
  from_square: string
  to_square: string
  attacker_piece: string
  captured_piece: string
  captured_value: number
}

export interface CaptureChain {
  start_ply: number
  end_ply: number
  events: CaptureEvent[]
  white_gain: number
  black_gain: number
  balance: number
  kind: string
  headline: string
  message: string
}

export interface ParsedGame {
  headers: GameHeaders
  timeline: TimelineNode[]
  capture_chains: CaptureChain[]
  warnings: string[]
}

export type VulnerabilityState = 'SAFE' | 'WATCH' | 'CONTESTED' | 'EXPOSED' | 'CRITICAL' | 'UNKNOWN'

export interface ActivityAssessment {
  state: 'ACTIVE' | 'NORMAL' | 'LIMITED' | 'PASSIVE'
  index: number
  legal_moves: string[]
  safe_moves: string[]
  captures: string[]
  checks: string[]
  supported_allies: string[]
  central_influence: string[]
  features: string[]
  explanation: string
}

export interface PieceAssessment {
  square: string
  color: 'white' | 'black'
  piece: string
  state: VulnerabilityState
  attackers: string[]
  legal_attackers: string[]
  defenders: string[]
  safe_moves: string[]
  pinned: boolean
  exchange_loss: number
  explanation: string
  activity: ActivityAssessment
}

export interface SquareControl {
  square: string
  white_attackers: string[]
  black_attackers: string[]
  white_effective: string[]
  black_effective: string[]
  white_pawn_control: boolean
  black_pawn_control: boolean
  balance: number
  tension: number
  occupied_by: string | null
  explanation: string
}

export interface Motif {
  code: string
  kind: 'PATTERN' | 'IMMEDIATE'
  side: 'white' | 'black'
  actor: string
  targets: string[]
  line: string[]
  blocker: string | null
  actor_piece: string | null
  actor_safe: boolean | null
  target_values: Record<string, number>
  material_potential: number
  confidence: number
  explanation: string
}

export interface PositionObservation {
  category: string
  severity: string
  title: string
  message: string
  subjects: string[]
}

export interface SideSituation {
  side: 'white' | 'black'
  posture: string
  attack: string
  defense: string
  coordination: string
  king_safety: string
  evidence: string[]
}

export interface SituationSummary {
  context: string
  headline: string
  white: SideSituation
  black: SideSituation
  focus_squares: string[]
  narratives: string[]
}

export interface PositionAnalysis {
  position: {
    fen: string
    side_to_move: 'white' | 'black'
    is_check: boolean
    is_checkmate: boolean
  }
  pieces: PieceAssessment[]
  squares: SquareControl[]
  motifs: Motif[]
  observations: PositionObservation[]
  situation: SituationSummary
}

export interface TransitionEvent {
  code: string
  severity: 'critical' | 'warning' | 'positive' | 'info'
  subjects: string[]
  before: string | number | null
  after: string | number | null
  message: string
}

export interface SituationChange {
  category: string
  impact: 'negative' | 'positive' | 'context' | 'neutral'
  headline: string
  message: string
  subjects: string[]
  evidence: string[]
}

export interface MoveAnalysis {
  move: string
  san: string
  action: 'MOVE' | 'CAPTURE'
  action_text: string
  mover_piece: string
  mover_value: number
  captured_piece: string | null
  captured_value: number
  immediate_risk: number
  material_outlook: 'NO_CAPTURE' | 'GAIN' | 'FAVORABLE' | 'EQUAL' | 'UNFAVORABLE'
  before: PositionAnalysis
  after: PositionAnalysis
  events: TransitionEvent[]
  changes: SituationChange[]
}

export interface PersonalityProfile {
  id: string
  name: string
  temperament: string
  description: string
  rating: number
  weights: Record<string, number>
  risk: number
  exchange_preference: number
  initiative: number
  caution: number
}

export interface MoveCandidate {
  uci: string
  san: string
  score: number
  reasons: string[]
  plan: string
  expected_reply: string | null
  continuation: string | null
}

export interface EpisodeAnalysis {
  kind: string
  headline: string
  message: string
  first: MoveAnalysis
  second: MoveAnalysis
  first_side_net: number
  second_side_net: number
  subjects: string[]
}

export type PlaybackMode = 'fixed' | 'tempo'
