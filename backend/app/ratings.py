from datetime import UTC, datetime

from .personalities import get_personality
from .storage import connection

DEFAULT_RATING = 500.0
K_FACTOR_ESTABLISHED = 16.0
K_FACTOR_NEW = 32.0
NEW_PLAYER_GAMES = 15


def _seed_rating(personality_id: str) -> float:
    try:
        return float(get_personality(personality_id).rating)
    except ValueError:
        return DEFAULT_RATING


def _ensure_row(personality_id: str) -> dict:
    with connection() as db:
        row = db.execute(
            "SELECT * FROM character_ratings WHERE personality_id = ?", (personality_id,)
        ).fetchone()
        if row is None:
            db.execute(
                "INSERT INTO character_ratings(personality_id, rating, updated_at) VALUES(?, ?, ?)",
                (personality_id, _seed_rating(personality_id), datetime.now(UTC).isoformat()),
            )
            row = db.execute(
                "SELECT * FROM character_ratings WHERE personality_id = ?", (personality_id,)
            ).fetchone()
    return dict(row)


def get_rating(personality_id: str) -> int:
    return int(round(_ensure_row(personality_id)["rating"]))


def list_ratings() -> list[dict]:
    rows: list[dict] = []
    with connection() as db:
        stored = {
            row["personality_id"]: dict(row)
            for row in db.execute("SELECT * FROM character_ratings ORDER BY rating DESC").fetchall()
        }
    from .personalities import list_personalities

    for profile in list_personalities():
        if profile.id in stored:
            row = stored[profile.id]
        else:
            row = {
                "personality_id": profile.id,
                "rating": float(profile.rating),
                "games": 0,
                "wins": 0,
                "draws": 0,
                "losses": 0,
                "updated_at": None,
            }
        row["name"] = profile.name
        row["temperament"] = profile.temperament
        rows.append(row)
    rows.sort(key=lambda item: (-float(item["rating"]), str(item["name"])))
    return rows


def _expected_score(white_rating: float, black_rating: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((black_rating - white_rating) / 400.0))


def _k_factor(games: int) -> float:
    return K_FACTOR_NEW if games < NEW_PLAYER_GAMES else K_FACTOR_ESTABLISHED


def apply_game_result(white_id: str, black_id: str, result: str) -> dict:
    """Обновляет Elo после партии и возвращает рейтинг до/после для обоих."""
    white = _ensure_row(white_id)
    black = _ensure_row(black_id)
    actual_white = {"1-0": 1.0, "0-1": 0.0}.get(result, 0.5)
    actual_black = 1.0 - actual_white

    white_delta = _k_factor(white["games"]) * (actual_white - _expected_score(white["rating"], black["rating"]))
    black_delta = _k_factor(black["games"]) * (actual_black - _expected_score(black["rating"], white["rating"]))
    white_after = white["rating"] + white_delta
    black_after = black["rating"] + black_delta
    white_wins = 1 if result == "1-0" else 0
    black_wins = 1 if result == "0-1" else 0
    draws = 1 if result == "1/2-1/2" else 0
    now = datetime.now(UTC).isoformat()
    with connection() as db:
        db.execute(
            "UPDATE character_ratings SET rating = ?, games = games + 1, wins = wins + ?, draws = draws + ?, "
            "losses = losses + ?, updated_at = ? WHERE personality_id = ?",
            (white_after, white_wins, draws, 1 - white_wins - draws, now, white_id),
        )
        db.execute(
            "UPDATE character_ratings SET rating = ?, games = games + 1, wins = wins + ?, draws = draws + ?, "
            "losses = losses + ?, updated_at = ? WHERE personality_id = ?",
            (black_after, black_wins, draws, 1 - black_wins - draws, now, black_id),
        )
    return {
        "white_before": white["rating"],
        "black_before": black["rating"],
        "white_after": white_after,
        "black_after": black_after,
    }
