from app.dialogue import generate_utterance
from app.models import MoveCandidate
from app.personalities import get_personality


def candidate(score: int, reasons: list[str]) -> MoveCandidate:
    return MoveCandidate(uci="e7e5", san="e5", score=score, reasons=reasons, plan="атаковать")


def test_choleric_attacking_line_is_short_and_live() -> None:
    phrase, emotion = generate_utterance(get_personality("choleric"), candidate(260, ["форсирующий шах"]))

    assert phrase
    assert len(phrase) < 60
    assert emotion == "азарт"


def test_resignation_has_personal_phrase() -> None:
    phrase, emotion = generate_utterance(get_personality("sanguine"), None, True, "проиграно")

    assert phrase
    assert any(marker in phrase.lower() for marker in ("сда", "отступ", "слышали", "договориться"))
    assert emotion == "смирение"


def test_same_event_is_deterministic() -> None:
    personality = get_personality("phlegmatic")
    move = candidate(40, ["улучшение координации"])
    assert generate_utterance(personality, move) == generate_utterance(personality, move)
