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

    assert profile.name == "Джек Воробей"
    assert profile.temperament == "сангвиник"
    assert profile.weights["initiative"] == 1.4
    assert profile.risk == 1.25


def test_collector_character_pack_has_pechkin_voice() -> None:
    pack = character_pack("collector")
    profile = get_personality("collector")

    assert pack is not None
    assert profile.name == "Почтальон Печкин"
    assert profile.weights["material"] == 1.65
    assert "material_gain" in pack.dialogue
    assert "exchange_refused" in pack.dialogue
    assert all(line.id.startswith("collector_") for pool in pack.dialogue.values() for line in pool)


def test_collector_material_capture_uses_material_pool() -> None:
    pack = character_pack("collector")
    reset_character_dialogue()
    personality = get_personality("collector")
    move = MoveCandidate(
        uci="d8d4",
        san="Qxd4",
        score=180,
        reasons=["взятие материала +3"],
        plan="сохранить материальный перевес",
    )

    phrase, emotion = generate_utterance(personality, move, move_number=15)

    assert phrase in {line.text for line in pack.dialogue["material_gain"]}
    assert emotion == "удовлетворение"


def test_phlegmatic_character_pack_has_fogg_voice() -> None:
    pack = character_pack("phlegmatic")
    profile = get_personality("phlegmatic")

    assert pack is not None
    assert profile.name == "Филеас Фогг"
    assert profile.weights["king_safety"] == 1.4
    assert "attack_preparation" in pack.dialogue
    assert any("Паспарту" in line.text for pool in pack.dialogue.values() for line in pool)
    assert all(line.id.startswith("phlegmatic_") for pool in pack.dialogue.values() for line in pool)


def test_phlegmatic_under_attack_uses_aphorism_pool() -> None:
    pack = character_pack("phlegmatic")
    reset_character_dialogue()
    personality = get_personality("phlegmatic")
    move = MoveCandidate(
        uci="e8f8",
        san="Kf8",
        score=-220,
        reasons=["позиция требует защиты"],
        plan="отразить атаку",
    )

    phrase, emotion = generate_utterance(personality, move, move_number=18)

    assert phrase in {line.text for line in pack.dialogue["under_attack"]}
    assert emotion == "тревога"


def test_gambiteer_character_pack_has_mcqueen_voice() -> None:
    pack = character_pack("gambiteer")
    profile = get_personality("gambiteer")

    assert pack is not None
    assert profile.name == "Молния МакКуин"
    assert profile.initiative == 1.6
    assert profile.risk == 1.55
    texts = [line.text for pool in pack.dialogue.values() for line in pool]
    assert any("Скорость. Я — Скорость" in text for text in texts)
    assert any("чау" in text.lower() for text in texts)
    assert any("Поверни направо" in text for text in texts)
    assert all(line.id.startswith("gambiteer_") for pool in pack.dialogue.values() for line in pool)


def test_gambiteer_strong_attack_uses_mcqueen_pool() -> None:
    pack = character_pack("gambiteer")
    reset_character_dialogue()
    personality = get_personality("gambiteer")
    move = MoveCandidate(
        uci="h4h7",
        san="Qh7+",
        score=320,
        reasons=["форсирующий шах", "создана атака"],
        plan="удержать инициативу",
    )

    phrase, emotion = generate_utterance(personality, move, move_number=15)

    assert phrase in {line.text for line in pack.dialogue["attack_strong"]}
    assert emotion == "азарт"


def test_universal_character_pack_has_hermione_voice() -> None:
    pack = character_pack("universal")
    profile = get_personality("universal")

    assert pack is not None
    assert profile.name == "Гермиона"
    assert profile.initiative == 1.0
    assert profile.caution == 1.0
    texts = [line.text for pool in pack.dialogue.values() for line in pool]
    assert any("ЛевиОса" in text for text in texts)
    assert any("Надеюсь, вы собой довольны" in text for text in texts)
    assert any("Превосходно замечено" in text for text in texts)
    assert any(text == "Мальчики!" for text in texts)
    assert all(line.id.startswith("universal_") for pool in pack.dialogue.values() for line in pool)


def test_strategist_character_pack_has_doc_hudson_voice() -> None:
    pack = character_pack("strategist")
    profile = get_personality("strategist")

    assert pack is not None
    assert profile.name == "Док Хадсон"
    assert profile.weights["center"] == 1.4
    assert profile.weights["development"] == 1.35
    texts = [line.text for pool in pack.dialogue.values() for line in pool]
    assert any("Дело закрыто" in text for text in texts)
    assert any("Поверни направо" in text for text in texts)
    assert any("Они бросили меня" in text for text in texts)
    assert any("капот на тарелке" in text for text in texts)
    assert all(line.id.startswith("strategist_") for pool in pack.dialogue.values() for line in pool)


def test_defender_character_pack_has_puss_in_boots_voice() -> None:
    pack = character_pack("defender")
    profile = get_personality("defender")

    assert pack is not None
    assert profile.name == "Кот в сапогах"
    assert profile.weights["king_safety"] == 1.55
    assert profile.caution == 1.5
    texts = [line.text for pool in pack.dialogue.values() for line in pool]
    assert any("Бойся меня" in text for text in texts)
    assert any("Кота в сапогах" in text for text in texts)
    assert any("Маркиза Карабаса" in text for text in texts)
    assert any("понедельники" in text for text in texts)
    assert all(line.id.startswith("defender_") for pool in pack.dialogue.values() for line in pool)


def test_defender_counterattack_uses_attack_pool() -> None:
    pack = character_pack("defender")
    reset_character_dialogue()
    personality = get_personality("defender")
    move = MoveCandidate(
        uci="e7e1",
        san="Re1+",
        score=300,
        reasons=["форсирующий шах", "контратака"],
        plan="нанести ответный удар",
    )

    phrase, emotion = generate_utterance(personality, move, move_number=20)

    assert phrase in {line.text for line in pack.dialogue["attack_strong"]}
    assert emotion == "азарт"


def test_choleric_character_pack_has_vrungel_voice() -> None:
    pack = character_pack("choleric")
    profile = get_personality("choleric")

    assert pack is not None
    assert profile.name == "Капитан Врунгель"
    assert profile.weights["tactics"] == 1.45
    assert profile.initiative == 1.5
    texts = [line.text for pool in pack.dialogue.values() for line in pool]
    assert any("Как вы яхту назовёте" in text for text in texts)
    assert any("непоправимый скандал" in text for text in texts)
    assert any("дело — табак" in text for text in texts)
    assert any("Каждая селёдка" in text for text in texts)
    assert all(line.id.startswith("choleric_") for pool in pack.dialogue.values() for line in pool)


def test_melancholic_character_pack_has_livesey_voice() -> None:
    pack = character_pack("melancholic")
    profile = get_personality("melancholic")

    assert pack is not None
    assert profile.name == "Доктор Ливси"
    assert profile.weights["king_safety"] == 1.3
    assert profile.caution == 1.55
    texts = [line.text for pool in pack.dialogue.values() for line in pool]
    assert any("Я доктор Ливси" in text for text in texts)
    assert any("ром» и слово «смерть" in text for text in texts)
    assert any("спасём этот никчёмный кусок жизни" in text for text in texts)
    assert any("селезёночка" in text for text in texts)
    assert all(line.id.startswith("melancholic_") for pool in pack.dialogue.values() for line in pool)


def test_melancholic_bad_position_uses_rescue_pool() -> None:
    pack = character_pack("melancholic")
    reset_character_dialogue()
    personality = get_personality("melancholic")
    move = MoveCandidate(
        uci="e8f8",
        san="Kf8",
        score=-300,
        reasons=["позиция критическая", "требуется защита"],
        plan="спасти позицию",
    )

    phrase, emotion = generate_utterance(personality, move, move_number=20)

    assert phrase in {line.text for line in pack.dialogue["own_mistake"]}
    assert emotion == "тревога"


def test_tactician_character_pack_has_sherlock_voice() -> None:
    pack = character_pack("tactician")
    profile = get_personality("tactician")

    assert pack is not None
    assert profile.name == "Шерлок Холмс"
    assert profile.weights["tactics"] == 1.6
    assert profile.initiative == 1.25
    texts = [line.text for pool in pack.dialogue.values() for line in pool]
    assert any("элементарно, ватсон" in text.lower() for text in texts)
    assert any("Курить вредно" in text for text in texts)
    assert any("Нет ничего важнее мелочей" in text for text in texts)
    assert any("Браво, доктор" in text for text in texts)
    assert all(line.id.startswith("tactician_") for pool in pack.dialogue.values() for line in pool)


def test_all_profiles_expose_replaceable_avatar_paths() -> None:
    personalities = list_personalities()

    for personality in personalities:
        assert personality.avatars["default"] == f"/avatars/{personality.id}/default.webp"
        assert personality.avatars["thinking"] == f"/avatars/{personality.id}/thinking.webp"
        assert personality.avatars["attack"] == f"/avatars/{personality.id}/attack.webp"
        assert personality.avatars["danger"] == f"/avatars/{personality.id}/danger.webp"
        assert personality.avatars["happy"] == f"/avatars/{personality.id}/happy.webp"
        assert personality.avatars["sad"] == f"/avatars/{personality.id}/sad.webp"


def test_builtin_count_unchanged_after_merge() -> None:
    personalities = list_personalities()

    assert len(personalities) == 10
    assert len({personality.id for personality in personalities}) == 10


def test_jack_sparrow_pack_has_signature_voice() -> None:
    pack = character_pack("sanguine")

    texts = [line.text for pool in pack.dialogue.values() for line in pool]
    assert any("Но вы обо мне слышали" in text for text in texts)
    assert any("Смекаешь" in text for text in texts)
    assert any("это политика" in text.lower() for text in texts)
    assert any("ром" in text.lower() for text in texts)


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
