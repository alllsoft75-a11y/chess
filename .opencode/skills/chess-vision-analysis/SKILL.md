---
name: chess-vision-analysis
description: Use when analyzing chess PGN files with Chess Vision, reviewing a player's mistakes or strengths, comparing periods, measuring long-term skill trends, or building a training cycle. Triggers on PGN, партия, разбор партии, ошибки, динамика навыка, прогресс игрока, профиль игрока, ChessVision, and Chess Vision. Use ONLY for player-game analysis, not for developing the chess application itself.
---

# Chess Vision player analysis

Analyze a corpus conservatively and reproducibly. Treat Chess Vision as an evidence-producing heuristic system, not an objective chess engine.

## Source priority

Resolve conflicts in this order:

1. `backend/app/*.py` and `backend/tests/*.py`
2. `Semantic.md`
3. `TechResearch.md`
4. verified analysis reports
5. `Discuss.MD` as historical context only

Read only the files needed for the request. Use `Semantic.md` for implemented semantics and `TechResearch.md` for longitudinal methodology.

## Scope and guarantees

- Analyze imported PGN files without Stockfish, UCI, centipawn scores, WDL, or accuracy percentages unless the user explicitly requests and provides another engine workflow.
- Do not call a move objectively best or assign a cognitive cause from board evidence alone.
- Separate observed facts, heuristic labels, hypotheses about causes, and training recommendations.
- Prefer `unknown` or `needs_review` over an unsupported diagnosis.
- Do not modify the repository, SQLite database, or reports unless explicitly asked.
- Prefer direct Python calls to `app.pgn.parse_pgn`, `app.batch.analyze_player_games`, and `app.transition.analyze_move`. Starting FastAPI initializes storage and is unnecessary for read-only analysis.

## Establish the corpus

Before analysis, determine:

- exact player name as written in PGN headers;
- PGN files or directories;
- requested period and whether all games, losses, or a subset are in scope;
- time controls, platform, and rating bands when available;
- whether the goal is a game review, baseline profile, period comparison, or training-cycle evaluation.

If a value is missing and materially changes the result, ask. Never infer the player from a filename.

For every input:

1. Decode UTF-8 and tolerate BOM.
2. Split multi-game PGN streams into separate games before calling current parsers.
3. Parse the game and verify the exact player appears in `White` or `Black`.
4. Record source filename, headers, color, date, result, time control, ratings, and warnings.
5. Report invalid, skipped, duplicate, and player-mismatch games.
6. Preserve FEN before every assessed move.

Do not treat missing clock annotations as time trouble. `[%emt]` is direct elapsed time; elapsed time inferred from `[%clk]` and increment is approximate.

## Run the implemented analysis

The current batch entry point is:

```python
from app.batch import analyze_player_games
report = analyze_player_games(pgns, player)
```

Each list element must contain one game. The current `game_index` is zero-based; user-facing output must use the source filename and a one-based display number.

Use `parse_pgn` to validate timelines and `analyze_move(fen_before, uci)` to inspect important events. Use episode analysis when a reply or recapture determines whether the initial label is valid.

Classify findings by review level:

### High-priority evidence

- `MATERIAL_BLUNDER`
- `IGNORED_MATE_THREAT`
- `ALLOWED_MATE_IN_ONE`

These are still heuristic findings, but should be reviewed first.

### Mandatory manual review

- `IGNORED_MATERIAL_THREAT`
- `DEFENSIVE_BREAKDOWN`

For each candidate check:

- whether the player was in check or had a forced response;
- checks, captures, and immediate counterplay;
- whether the exchange sequence is complete;
- tactical or positional compensation;
- whether the alleged defender could legally act;
- whether the conclusion depends on play beyond the implemented horizon.

Never turn `DEFENSIVE_BREAKDOWN` directly into a persistent player trait. Do not call a sacrifice a blunder solely from local material balance.

For every major event provide:

- source game and player color;
- move number, ply, SAN, and UCI when available;
- category and detector message;
- FEN before the move;
- concrete board evidence;
- review status: `confirmed`, `candidate`, `needs_review`, or `unknown`.

## Build a player profile

Aggregate only reviewed evidence. Show every rate as percentage plus numerator and denominator, for example `67% (20/30)`.

At minimum report:

- games supplied, parsed, matched, and analyzed;
- player moves analyzed;
- clean moves and clean games;
- reviewed error counts by category;
- recurring contexts and motifs;
- demonstrated strengths;
- clock findings only for games with usable timing data.

When data permits, stratify by:

- time control;
- color;
- phase of game;
- opening structure;
- attacking versus defending context;
- platform;
- opponent rating band.

Do not combine bullet, blitz, rapid, different platforms, or sharply different rating bands into one trend without showing separate strata.

## Measure long-term change

Use comparable chronological windows. Prefer:

1. equal periods with the same time control and platform;
2. adjacent equal-size game windows;
3. recent 200 games versus previous 200 when the corpus is large enough;
4. EWMA as a descriptive smooth trend.

Never claim improvement from raw counts when exposure changed. Compare rates with denominators and sample sizes. Treat small samples as uncertain; use Wilson intervals or bootstrap intervals when implementing statistical comparison.

Useful target metrics, only when their denominators can be measured honestly:

```text
blunder_free_rate = games without confirmed human blunder / relevant games
motif_seen_rate = recognized opportunities / detected opportunities
motif_conversion = successfully executed motifs / available motifs
threat_prevention = neutralized opponent threats / detected opponent threats
clean_win_rate = wins without confirmed major error / wins
time_loss_rate = losses on time / games with reliable clock data
```

Current Chess Vision does not fully implement all these denominators. Mark unavailable metrics as unavailable rather than estimating them from unrelated labels.

For motif development, keep separate:

- exposure;
- recognition;
- execution;
- prevention;
- repeatability;
- complexity.

A level such as 0–5 may be shown only as a derived display value accompanied by sample size and method.

## Convert findings into training

Infer no more than one or two stable patterns from a period. Select one bottleneck for a 2–4 week cycle and define:

- the evidence and contexts;
- baseline with numerator and denominator;
- a behavioral routine at the board;
- a measurable target for the next 10–20 comparable games;
- review date and success criterion.

Prefer actionable routines such as a threat scan or candidate-check sequence over broad advice such as “calculate better.”

## Validate arithmetic and claims

Recalculate summaries from primary game/event rows. Never trust manually written totals without checking:

- category counts sum to total events;
- clean plus non-clean moves does not exceed analyzed moves;
- per-window counts match the corpus;
- all percentages have correct denominators;
- comparisons use comparable strata;
- duplicate games do not inflate the trend.

Historical Markdown reports are evidence examples, not reusable datasets unless regenerated from the same corpus and rules version.

## Report format

Use this structure unless the user requests another format:

```markdown
# Анализ игрока <username>

## Выборка
- период:
- файлов передано:
- партий разобрано / найден игрок / проанализировано:
- ходов игрока:
- контроли и платформы:
- партии с достоверным временем:
- версия правил:

## Ключевые события
| Партия | Цвет | Ход | Категория | Статус | FEN до хода | Доказательство |

## Кандидаты на ручную проверку
...

## Устойчивые паттерны
1. ...
2. ...

## Сильные стороны
...

## Динамика по сопоставимым периодам
| Метрика | Ранний период | Поздний период | Изменение | Размер выборки | Уверенность |

## Один тренировочный цикл
- узкое место:
- baseline:
- процедура:
- target:
- горизонт:

## Ограничения
...
```

For a single-game request, omit longitudinal sections and explain the critical sequence using board evidence. Distinguish what Chess Vision detected during the game from deeper analysis performed afterward.

## Changes to analyzer code

If the request changes implementation rather than only analyzing games, follow existing conventions and run from `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_pgn.py tests\test_capture_chains.py tests\test_batch.py tests\test_transition.py
.\.venv\Scripts\python.exe -m ruff check app tests
```

Run the full relevant suite when practical. Backend type checking is not configured. If frontend files change, run from `frontend`:

```powershell
npm run test
npm run lint
npm run typecheck
npm run build
```

Do not run `start_frontend.bat` merely for validation because it may install dependencies.
