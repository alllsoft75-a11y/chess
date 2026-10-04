from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

CHARACTERS_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "characters"


class CharacterLine(BaseModel):
    id: str
    text: str
    weight: float = 1.0
    cooldown: int = 6
    min_move: int | None = None
    max_move: int | None = None


class DialoguePolicy(BaseModel):
    priority: list[str] = Field(default_factory=list)
    default_situation: str = "thinking"
    repeat_cooldown_moves: int = 6
    fallback: str = "silent"
    probability: dict[str, float] = Field(default_factory=dict)
    optional_prefixes: list[str] = Field(default_factory=list)


class CharacterPack(BaseModel):
    schema_version: int
    id: str
    name: str
    temperament: str
    description: str
    enabled: bool = True
    rating: int = 500
    gameplay: dict
    persona: dict = Field(default_factory=dict)
    avatars: dict[str, str] = Field(default_factory=dict)
    dialogue_policy: DialoguePolicy = Field(default_factory=DialoguePolicy)
    dialogue: dict[str, list[CharacterLine]]

    def lines_for(self, situation: str) -> list[CharacterLine]:
        return self.dialogue.get(situation, [])

    def has_situation(self, situation: str) -> bool:
        return situation in self.dialogue


def _validate_unique_line_ids(pack: CharacterPack, source: str) -> None:
    seen: set[str] = set()
    for pool in pack.dialogue.values():
        for line in pool:
            if line.id in seen:
                raise ValueError(f"Повтор идентификатора реплики {line.id} в {source}")
            seen.add(line.id)


def load_character_packs(directory: Path | None = None) -> dict[str, CharacterPack]:
    target = directory if directory is not None else CHARACTERS_DIRECTORY
    packs: dict[str, CharacterPack] = {}
    if not target.is_dir():
        return packs
    for file in sorted(target.glob("*.json")):
        if file.name.endswith(".schema.json"):
            continue
        try:
            pack = CharacterPack.model_validate_json(file.read_text(encoding="utf-8"))
        except ValidationError as error:
            raise ValueError(f"Персонаж из {file.name} не прошёл валидацию: {error}") from error
        _validate_unique_line_ids(pack, file.name)
        if pack.id in packs:
            raise ValueError(f"Дубликат персонажа {pack.id} в {file.name}")
        if not pack.enabled:
            continue
        packs[pack.id] = pack
    return packs


_PACKS: dict[str, CharacterPack] | None = None


def character_packs() -> dict[str, CharacterPack]:
    global _PACKS
    if _PACKS is None:
        _PACKS = load_character_packs()
    return _PACKS


def character_pack(personality_id: str) -> CharacterPack | None:
    return character_packs().get(personality_id)


def reset_character_packs() -> None:
    global _PACKS
    _PACKS = None
