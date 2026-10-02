from copy import deepcopy

from .characters import character_packs
from .models import PersonalityProfile

_BASE = {
    "material": 1.0,
    "activity": 1.0,
    "center": 1.0,
    "development": 1.0,
    "king_safety": 1.0,
    "tactics": 1.0,
    "plan_memory": 1.0,
}

_BUILTIN = [
    PersonalityProfile(id="sanguine", name="Инициатор", temperament="сангвиник", description="Инициативный оптимист, любит активную игру.", weights={**_BASE, "activity": 1.3, "initiative": 1.4, "tactics": 1.2}, risk=1.25, exchange_preference=0.8, initiative=1.35, caution=0.75),
    PersonalityProfile(id="choleric", name="Штурмовик", temperament="холерик", description="Резкий атакёр, форсирует события.", weights={**_BASE, "tactics": 1.45, "king_safety": 0.8}, risk=1.45, exchange_preference=0.65, initiative=1.5, caution=0.55),
    PersonalityProfile(id="phlegmatic", name="Позиционная крепость", temperament="флегматик", description="Спокойно укрепляет позицию и избегает риска.", weights={**_BASE, "king_safety": 1.4, "material": 1.2}, risk=0.55, exchange_preference=1.15, initiative=0.7, caution=1.45),
    PersonalityProfile(id="melancholic", name="Осторожный профилактик", temperament="меланхолик", description="Осторожен, заранее видит опасности.", weights={**_BASE, "king_safety": 1.3, "plan_memory": 1.35}, risk=0.45, exchange_preference=1.05, initiative=0.65, caution=1.55),
    PersonalityProfile(id="tactician", name="Охотник за комбинациями", temperament="аналитический", description="Ищет вилки, шахи и форсирующие линии.", weights={**_BASE, "tactics": 1.6, "activity": 1.15}, risk=1.05, exchange_preference=0.85, initiative=1.25, caution=0.9),
    PersonalityProfile(id="strategist", name="Архитектор позиции", temperament="аналитический", description="Развитие, центр и координация важнее немедленной выгоды.", weights={**_BASE, "center": 1.4, "development": 1.35, "activity": 1.2}, risk=0.8, exchange_preference=0.95, initiative=1.0, caution=1.1),
    PersonalityProfile(id="collector", name="Собиратель материала", temperament="прагматик", description="Собирает материал и любит выгодные размены.", weights={**_BASE, "material": 1.65, "tactics": 0.9}, risk=0.65, exchange_preference=1.35, initiative=0.75, caution=1.15),
    PersonalityProfile(id="gambiteer", name="Искатель инициативы", temperament="авантюрист", description="Готов отдавать материал ради темпа и атаки.", weights={**_BASE, "initiative": 1.6, "activity": 1.4, "material": 0.7}, risk=1.55, exchange_preference=0.45, initiative=1.6, caution=0.5),
    PersonalityProfile(id="defender", name="Контратакующий защитник", temperament="стойкий", description="Ценит устойчивость, контригру и безопасность.", weights={**_BASE, "king_safety": 1.55, "plan_memory": 1.2}, risk=0.6, exchange_preference=1.0, initiative=0.8, caution=1.5),
    PersonalityProfile(id="universal", name="Сбалансированный универсал", temperament="уравновешенный", description="Сбалансированный базовый стиль.", weights=deepcopy(_BASE), risk=0.9, exchange_preference=1.0, initiative=1.0, caution=1.0),
]


def _pack_profile(pack) -> PersonalityProfile:
    gameplay = pack.gameplay
    return PersonalityProfile(
        id=pack.id,
        name=pack.name,
        temperament=pack.temperament,
        description=pack.description,
        rating=pack.rating,
        weights=deepcopy(gameplay.get("weights", _BASE)),
        risk=float(gameplay.get("risk", 1.0)),
        exchange_preference=float(gameplay.get("exchange_preference", 1.0)),
        initiative=float(gameplay.get("initiative", 1.0)),
        caution=float(gameplay.get("caution", 1.0)),
    )


def _merged_personalities() -> list[PersonalityProfile]:
    profiles: dict[str, PersonalityProfile] = {profile.id: profile for profile in _BUILTIN}
    appended: list[PersonalityProfile] = []
    for pack in character_packs().values():
        profile = _pack_profile(pack)
        if pack.id in profiles:
            profiles[pack.id] = profile
        else:
            appended.append(profile)
    return [*profiles.values(), *appended]


PERSONALITIES = _merged_personalities()


def get_personality(personality_id: str) -> PersonalityProfile:
    for personality in PERSONALITIES:
        if personality.id == personality_id:
            return personality.model_copy(deep=True)
    raise ValueError(f"Персонаж {personality_id} не найден")


def list_personalities() -> list[PersonalityProfile]:
    return [personality.model_copy(deep=True) for personality in PERSONALITIES]
