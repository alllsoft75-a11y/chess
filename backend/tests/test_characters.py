from pathlib import Path

import pytest

from app.characters import character_pack, character_packs, load_character_packs
from app.dialogue import generate_utterance, reset_character_dialogue
from app.models import MoveCandidate
from app.personalities import get_personality, list_personalities


def candidate(score: int, reasons: list[str]) -> MoveCandidate:
    return MoveCandidate(uci="e7e5", san="e5", score=score, reasons=reasons, plan="атаковать")


def test_character_packs_load_with_unique_line_ids() -> None:
    packs = character_packs()

    assert "sanguine" in packs
    pack = packs["sanguine"]
    ids = [line.id for pool in pack.dialogue.values() for line in pool]
    assert len(ids) == len(set(ids))
    for required in ("attack", "attack_strong", "thinking", "resign", "checkmate_given", "greeting"):
        assert required in pack.dialogue


def test_json_profile_overrides_builtin() -> None:
    profile = get_personality("sanguine")

    assert profile.name == "Атакующий сангвиник"
    assert profile.temperament == "сангвиник"
    assert profile.weights["initiative"] == 1.4
    assert profile.risk == 1.25


def test_builtin_count_unchanged_after_merge() -> None:
    personalities = list_personalities()

    assert len(personalities) == 10
    assert len({personality.id for personality in personalities}) == 10


def test_pack_utterance_for_strong_attack_uses_pack_pool() -> None:
    pack = character_pack("sanguine")
    reset_character_dialogue()
    personality = get_personality("sanguine")

    phrase, emotion = generate_utterance(personality, candidate(300, ["форсирующий мат"]), move_number=10)

    pool_texts = {line.text for line in pack.dialogue["attack_strong"]}
    assert phrase in pool_texts
    assert emotion == "азарт"


def test_mate_after_uses_checkmate_pool() -> None:
    pack = character_pack("sanguine")
    reset_character_dialogue()
    personality = get_personality("sanguine")

    phrase, emotion = generate_utterance(personality, candidate(9999, ["мат"]), move_number=30, mate_after=True)

    pool_texts = {line.text for line in pack.dialogue["checkmate_given"]}
    assert phrase in pool_texts
    assert emotion == "азарт"


def test_first_move_uses_greeting_pool() -> None:
    pack = character_pack("sanguine")
    reset_character_dialogue()
    personality = get_personality("sanguine")

    phrase, _ = generate_utterance(personality, candidate(20, ["развитие фигуры"]), move_number=1)

    pool_texts = {line.text for line in pack.dialogue["greeting"]}
    assert phrase in pool_texts


def test_resignation_uses_pack_resign_pool() -> None:
    pack = character_pack("sanguine")
    reset_character_dialogue()
    personality = get_personality("sanguine")

    phrase, emotion = generate_utterance(personality, None, True, "материальный дефицит")

    pool_texts = {line.text for line in pack.dialogue["resign"]}
    assert phrase in pool_texts
    assert emotion == "смирение"


def test_same_event_does_not_repeat_line() -> None:
    reset_character_dialogue()
    personality = get_personality("sanguine")
    move = candidate(-200, ["позиция тревожная"])

    first, _ = generate_utterance(personality, move, move_number=15)
    second, _ = generate_utterance(personality, move, move_number=15)

    assert first
    assert second
    assert first != second


def test_broken_character_file_raises(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text('{"id": "broken"}', encoding="utf-8")

    with pytest.raises(ValueError):
        load_character_packs(tmp_path)
