import hashlib
import random
import re
from dataclasses import dataclass, field

from .characters import CharacterLine, CharacterPack, character_pack
from .models import MoveCandidate, PersonalityProfile

LINES = {
    "sanguine": {
        "attack": ["Ну что, пошумим?", "О, вот тут уже интересно.", "Кажется, начинается веселье."],
        "think": ["Так… а если вот сюда?", "Секунду, тут есть идея.", "Хм. Сейчас что-нибудь придумаю."],
        "danger": ["Ой. Это я недосмотрел.", "Так, спокойно. Выберемся.", "Вот теперь немного тревожно."],
        "good": ["Ой, это ты зря.", "Вот это мне нравится.", "Поймал!"],
        "resign": ["Ладно, тут уже без фокусов.", "Ну всё, приехали.", "Хорошая партия. Сдаюсь."],
    },
    "choleric": {
        "attack": ["Иду вперёд. Разбирайся.", "Сейчас будет жарко.", "Ну-ка, выдержи это."],
        "think": ["Так, стоп. Где тут удар?", "Не мешай, я считаю.", "Сейчас продавлю."],
        "danger": ["Чёрт. Ладно, отвечу жёстко.", "Не радуйся раньше времени.", "Это ещё не конец."],
        "good": ["Ой, это ты зря.", "Вот и всё. Попался.", "Я же предупреждал."],
        "resign": ["Ладно. В этот раз твоя взяла.", "Всё, хватит мучить позицию.", "Сдаюсь. Запомню."],
    },
    "phlegmatic": {
        "attack": ["Без спешки. Давление уже есть.", "Понемногу тесним.", "Позиция сама подсказывает."],
        "think": ["Торопиться некуда.", "Сначала всё укрепим.", "Посмотрим, что здесь надёжнее."],
        "danger": ["Неприятно, но держится.", "Придётся аккуратно.", "Лишних движений не будет."],
        "good": ["Так надёжнее.", "Небольшой плюс тоже плюс.", "Вот теперь всё на месте."],
        "resign": ["Дальше сопротивление уже формальное.", "Пожалуй, достаточно.", "Сдаюсь. Позиция исчерпана."],
    },
    "melancholic": {
        "attack": ["Выглядит неплохо. Но проверю ещё раз.", "Есть шанс. Главное — не испортить.", "Кажется, здесь можно надавить."],
        "think": ["Так, стоп. Пересчитаю.", "А что я здесь не заметил?", "Не-не, сначала проверим угрозы."],
        "danger": ["Я так и знал, что где-то подвох.", "Вот теперь страшновато.", "План отменяется. Спасаемся."],
        "good": ["Фух. Сработало.", "Кажется, всё правильно.", "Ну хоть тут не ошибся."],
        "resign": ["Да, тут уже всё ясно.", "Продолжать — только расстраиваться.", "Сдаюсь. Надо будет разобрать."],
    },
}

GENERIC = {
    "attack": ["Ой, это ты зря.", "Кажется, у меня появилась идея.", "Так, теперь моя очередь давить."],
    "think": ["Так… а если вот сюда?", "Секунду, взвешу варианты.", "Не спешу. Смотрю ещё раз."],
    "danger": ["Так, стоп. План меняется.", "Неприятно. Ищу выход.", "Ферзя просто так не отдам."],
    "good": ["Вот теперь хорошо.", "Хитро. Но недостаточно.", "Это я беру."],
    "resign": ["Ну всё, приехали.", "Ладно, тут без вариантов.", "Сдаюсь. Хорошо сыграно."],
}

_EMOTIONS = {
    "resign": "смирение",
    "checkmate_given": "азарт",
    "opponent_mistake_major": "азарт",
    "attack_strong": "азарт",
    "attack": "напор",
    "own_mistake": "тревога",
    "under_attack": "тревога",
    "bad_position": "тревога",
    "thinking": "сосредоточенность",
}

_GATED_SITUATIONS = {"thinking", "attack", "quiet_position", "choosing_plan", "middlegame", "endgame"}

_STAGE_SITUATIONS = {"greeting": 1, "opening": 6}


@dataclass
class _DialogueState:
    counter: int = 0
    last_line_id: str | None = None
    last_used: dict[str, int] = field(default_factory=dict)


_STATE: dict[str, _DialogueState] = {}


def reset_character_dialogue(personality_id: str | None = None) -> None:
    if personality_id is None:
        _STATE.clear()
    else:
        _STATE.pop(personality_id, None)


def _pick(personality_id: str, category: str, seed: str) -> str:
    lines = LINES.get(personality_id, GENERIC).get(category, GENERIC[category])
    value = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)
    return lines[value % len(lines)]


def _within_stage(line: CharacterLine, move_number: int | None) -> bool:
    if move_number is None:
        return True
    if line.min_move is not None and move_number < line.min_move:
        return False
    if line.max_move is not None and move_number > line.max_move:
        return False
    return True


def _eligible_lines(
    pack: CharacterPack,
    situation: str,
    state: _DialogueState,
    move_number: int | None,
    apply_stage: bool = True,
) -> list[CharacterLine]:
    pool = pack.lines_for(situation)
    eligible: list[CharacterLine] = []
    for line in pool:
        if apply_stage and not _within_stage(line, move_number):
            continue
        used_at = state.last_used.get(line.id)
        if used_at is not None and state.counter - used_at < line.cooldown:
            continue
        eligible.append(line)
    if not eligible and apply_stage:
        return _eligible_lines(pack, situation, state, move_number, apply_stage=False)
    return eligible


def _weighted_choice(lines: list[CharacterLine], seed: str) -> CharacterLine:
    rng = random.Random(seed)
    total = sum(line.weight for line in lines)
    roll = rng.random() * total
    accumulated = 0.0
    for line in lines:
        accumulated += line.weight
        if roll <= accumulated:
            return line
    return lines[-1]


def _seed_hash(seed: str) -> int:
    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)


def _interjections(pack: CharacterPack) -> set[str]:
    voice = pack.persona.get("voice", {})
    return {str(word).rstrip("!").lower() for word in voice.get("interjections", [])}


def _maybe_prefix(pack: CharacterPack, text: str, seed: str) -> str:
    prefixes = pack.dialogue_policy.optional_prefixes
    if not prefixes:
        return text
    first_word = re.split(r"[\s,.!?…]+", text, maxsplit=1)[0].lower()
    if first_word in _interjections(pack):
        return text
    if _seed_hash(f"{seed}:prefix") % 100 >= 20:
        return text
    prefix = prefixes[_seed_hash(f"{seed}:prefix-choice") % len(prefixes)]
    head, tail = text[:1], text[1:]
    if head.isupper() and tail[:1].islower():
        text = f"{head.lower()}{tail}"
    return f"{prefix} {text}"


def _classify_pack_situation(
    personality: PersonalityProfile,
    move: MoveCandidate | None,
    resigned: bool,
    mate_after: bool,
    move_number: int | None,
) -> str:
    if resigned:
        return "resign"
    if mate_after:
        return "checkmate_given"
    if move is None:
        return "thinking"
    text = " ".join(move.reasons).lower()
    if "потер" in text or "критич" in text:
        return "own_mistake"
    if move.score < -150:
        return "under_attack"
    base = _base_situation(personality, move, text)
    if base in {"thinking", "attack"} and move_number is not None:
        for situation, limit in _STAGE_SITUATIONS.items():
            if move_number <= limit:
                return situation
    return base


def _base_situation(personality: PersonalityProfile, move: MoveCandidate, text: str) -> str:
    if "мат" in text:
        return "attack_strong"
    if move.score >= 600:
        return "opponent_mistake_major"
    if move.score >= 250:
        return "attack_strong"
    if "шах" in text or "атак" in text or personality.initiative > 1.2:
        return "attack"
    return "thinking"


def _fallback_situations(pack: CharacterPack, situation: str) -> list[str]:
    chain = [situation]
    neighbours = {
        "own_mistake": ["under_attack", "bad_position"],
        "under_attack": ["own_mistake", "bad_position"],
        "opponent_mistake_major": ["attack_strong"],
        "attack_strong": ["attack"],
        "attack": ["attack_strong"],
    }
    chain.extend(neighbours.get(situation, []))
    default = pack.dialogue_policy.default_situation
    if default not in chain:
        chain.append(default)
    return [item for item in chain if pack.has_situation(item)]


def _pack_utterance(
    personality: PersonalityProfile,
    pack: CharacterPack,
    move: MoveCandidate | None,
    resigned: bool,
    move_number: int | None,
    mate_after: bool,
) -> tuple[str, str]:
    situation = _classify_pack_situation(personality, move, resigned, mate_after, move_number)
    emotion = _EMOTIONS.get(situation, "сосредоточенность")
    policy = pack.dialogue_policy
    probabilities = policy.probability
    if situation in _GATED_SITUATIONS:
        probability = probabilities.get("ordinary_move", 0.25)
        seed_key = f"{personality.id}:{move.uci if move else 'none'}:{move.score if move else 0}:{situation}"
        if _seed_hash(f"{seed_key}:gate") % 1000 >= int(probability * 1000):
            return "", emotion
    state = _STATE.setdefault(personality.id, _DialogueState())
    state.counter += 1
    for candidate in _fallback_situations(pack, situation):
        eligible = _eligible_lines(pack, candidate, state, move_number)
        if not eligible:
            continue
        chosen = _weighted_choice(eligible, f"{personality.id}:{move.uci if move else 'none'}:{situation}:{state.counter}")
        state.last_line_id = chosen.id
        state.last_used[chosen.id] = state.counter
        text = _maybe_prefix(pack, chosen.text, f"{personality.id}:{chosen.id}:{state.counter}")
        return text, emotion
    return _pick(personality.id, "think" if not resigned else "resign", personality.id), emotion


def generate_utterance(
    personality: PersonalityProfile,
    move: MoveCandidate | None,
    resigned: bool = False,
    resignation_reason: str | None = None,
    *,
    move_number: int | None = None,
    mate_after: bool = False,
) -> tuple[str, str]:
    pack = character_pack(personality.id)
    if pack is not None:
        return _pack_utterance(personality, pack, move, resigned, move_number, mate_after)
    if resigned:
        return _pick(personality.id, "resign", resignation_reason or personality.id), "смирение"
    if move is None:
        return _pick(personality.id, "think", personality.id), "задумчивость"
    text = " ".join(move.reasons).lower()
    if "потер" in text or "критич" in text or move.score < 0:
        category, emotion = "danger", "тревога"
    elif "мат" in text or "форсирован" in text or "вилка" in text or move.score >= 250:
        category, emotion = "good", "азарт"
    elif "шах" in text or "атак" in text or personality.initiative > 1.2:
        category, emotion = "attack", "напор"
    else:
        category, emotion = "think", "сосредоточенность"
    seed = f"{personality.id}:{move.uci}:{move.score}:{category}"
    return _pick(personality.id, category, seed), emotion
