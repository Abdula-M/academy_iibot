"""
Маппинг фотографий к темам и специальностям.

Анализирует ВОПРОС пользователя (не ответ ИИ) по ключевым словам
и возвращает путь к единственной наиболее релевантной фотографии.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Базовая директория с фотографиями ─────────────────────────
_PHOTOS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "photos"

# ── Допустимые расширения файлов ──────────────────────────────
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True, slots=True)
class PhotoRule:
    """Правило привязки фотографии к ключевым словам.

    Attributes:
        filename: Имя файла фотографии (без пути, лежит в data/photos/).
        keywords: Набор ключевых фраз (в нижнем регистре).
                  Совпадение — когда ЛЮБАЯ из фраз найдена в вопросе.
    """

    filename: str
    keywords: tuple[str, ...]


# ── Правила для специальностей (11 штук) ──────────────────────
_SPECIALTY_RULES: tuple[PhotoRule, ...] = (
    PhotoRule(
        filename="lechebnoe_delo",
        keywords=("лечебн", "фельдшер", "31.02.01"),
    ),
    PhotoRule(
        filename="akusherskoe_delo",
        keywords=("акушер", "31.02.02"),
    ),
    PhotoRule(
        filename="laboratornaya_diagnostika",
        keywords=("лабораторн", "31.02.03"),
    ),
    PhotoRule(
        filename="meditsinskaya_optika",
        keywords=("оптик", "оптометрист", "31.02.04"),
    ),
    PhotoRule(
        filename="stomatologiya_ortopedicheskaya",
        keywords=("ортопедическ", "зубн", "31.02.05"),
    ),
    PhotoRule(
        filename="stomatologiya_profilakticheskaya",
        keywords=("профилактическ", "гигиенист", "31.02.06"),
    ),
    PhotoRule(
        filename="stomatologicheskoe_delo",
        keywords=("стоматологическ", "31.02.07"),
    ),
    PhotoRule(
        filename="meditsinskiy_administrator",
        keywords=("администратор", "31.01.01"),
    ),
    PhotoRule(
        filename="mediko_profilakticheskoe_delo",
        keywords=("медико-профилактическ", "санитарн", "32.02.01"),
    ),
    PhotoRule(
        filename="farmatsiya",
        keywords=("фармац", "33.02.01"),
    ),
    PhotoRule(
        filename="sestrinskoe_delo",
        keywords=("сестринск", "медсестр", "медбрат", "34.02.01"),
    ),
)

# ── Правила для тематических фото (7 штук) ────────────────────
_TOPIC_RULES: tuple[PhotoRule, ...] = (
    PhotoRule(
        filename="specialnosti",
        keywords=(
            "специальност", "направлени", "изуча",
        ),
    ),
    PhotoRule(
        filename="grafik_raboty",
        keywords=(
            "график", "расписани", "режим",
        ),
    ),
    PhotoRule(
        filename="praktika",
        keywords=(
            "практик", "стажировк", "трудоустройств",
        ),
    ),
    PhotoRule(
        filename="oplata",
        keywords=(
            "оплат", "плат", "маткапитал", "материнск",
            "кредит", "рассрочк", "стоимост",
        ),
    ),
    PhotoRule(
        filename="sroki_podachi",
        keywords=(
            "срок", "подач", "набор", "кампани",
        ),
    ),
    PhotoRule(
        filename="preimuschestva",
        keywords=(
            "преимуществ", "плюс",
        ),
    ),
    PhotoRule(
        filename="dokumenty",
        keywords=(
            "документ", "принест",
        ),
    ),
)

# ── Объединённый список всех правил ───────────────────────────
_ALL_RULES: tuple[PhotoRule, ...] = _SPECIALTY_RULES + _TOPIC_RULES


def _resolve_photo_path(filename: str) -> Path | None:
    """Найти файл фотографии с учётом разных расширений.

    Returns:
        Путь к файлу или None, если файл не найден.
    """
    for ext in _ALLOWED_EXTENSIONS:
        candidate = _PHOTOS_DIR / f"{filename}{ext}"
        if candidate.is_file():
            return candidate
    return None


def find_photo_for_query(
    user_query: str,
    sent_photos: set[str],
) -> Path | None:
    """Найти ОДНУ фотографию, соответствующую вопросу пользователя.

    Анализирует именно вопрос пользователя (не ответ ИИ).
    Возвращает фото только если оно ещё не отправлялось в этом диалоге.

    Args:
        user_query: Текст вопроса пользователя.
        sent_photos: Множество имён файлов уже отправленных фотографий.

    Returns:
        Путь к фотографии или None.
    """
    if not user_query:
        return None

    query_lower = user_query.lower()

    for rule in _ALL_RULES:
        # Пропускаем уже отправленные фото
        if rule.filename in sent_photos:
            continue

        # Проверяем наличие ключевой фразы в вопросе (по целым словам)
        import re
        matched = False
        for kw in rule.keywords:
            # Используем префиксный поиск слова. Мы ищем начало слова (граница слова),
            # затем корень kw, а после него могут идти любые буквы русского алфавита (окончания).
            # Это позволяет "оптик" находить "оптика", "оптику", но не позволяет "кредит" срабатывать в "аккредитация".
            if re.search(rf"(?:^|[^а-яёa-z]){re.escape(kw)}[а-яёa-z]*", query_lower):
                matched = True
                break
        
        if not matched:
            continue

        # Проверяем существование файла
        photo_path = _resolve_photo_path(rule.filename)
        if photo_path is None:
            logger.debug(
                "Фото '%s' не найдено в %s, правило пропущено.",
                rule.filename,
                _PHOTOS_DIR,
            )
            continue

        logger.info("Найдено фото '%s' для запроса: '%s'", rule.filename, user_query[:50])
        return photo_path

    return None
