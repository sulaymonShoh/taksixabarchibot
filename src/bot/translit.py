"""
High-Performance HTML-Safe Uzbek Latin <-> Cyrillic Transliteration Engine.
Translates UI text, menus, buttons, and prompts while strictly preserving:
- HTML tags (e.g. <b>, <code>, <a href="...">)
- URLs and Deep Links (e.g. https://t.me/..., tg://user?id=...)
- Mentions (e.g. @username)
- Emojis, numbers, and symbols
"""
import re
from typing import Dict

# Multi-character mappings (Ordered by match priority)
LATIN_TO_CYRILLIC_PAIRS = [
    # 3-char / specific cases with apostrophes
    ("o'", "ў"), ("O'", "Ў"), ("o‘", "ў"), ("O‘", "Ў"), ("o’", "ў"), ("O’", "Ў"),
    ("g'", "ғ"), ("G'", "Ғ"), ("g‘", "ғ"), ("G‘", "Ғ"), ("g’", "ғ"), ("G’", "Ғ"),
    ("e'", "эъ"), ("E'", "Эъ"), ("e‘", "эъ"), ("E‘", "Эъ"), ("e’", "эъ"), ("E’", "Эъ"),
    # Double letter diphthongs
    ("sh", "ш"), ("Sh", "Ш"), ("SH", "Ш"),
    ("ch", "ч"), ("Ch", "Ч"), ("CH", "Ч"),
    ("yo", "ё"), ("Yo", "Ё"), ("YO", "Ё"),
    ("yu", "ю"), ("Yu", "Ю"), ("YU", "Ю"),
    ("ya", "я"), ("Ya", "Я"), ("YA", "Я"),
    ("ye", "е"), ("Ye", "Е"), ("YE", "Е"),
    ("ts", "ц"), ("Ts", "Ц"), ("TS", "Ц"),
]

SINGLE_LATIN_TO_CYRILLIC = {
    'a': 'а', 'A': 'А',
    'b': 'б', 'B': 'Б',
    'd': 'д', 'D': 'Д',
    'e': 'е', 'E': 'Е',
    'f': 'ф', 'F': 'Ф',
    'g': 'г', 'G': 'Г',
    'h': 'ҳ', 'H': 'Ҳ',
    'i': 'и', 'I': 'И',
    'j': 'ж', 'J': 'Ж',
    'k': 'к', 'K': 'К',
    'l': 'л', 'L': 'Л',
    'm': 'м', 'M': 'М',
    'n': 'н', 'N': 'Н',
    'o': 'о', 'O': 'О',
    'p': 'п', 'P': 'П',
    'q': 'қ', 'Q': 'Қ',
    'r': 'р', 'R': 'Р',
    's': 'с', 'S': 'С',
    't': 'т', 'T': 'Т',
    'u': 'у', 'U': 'У',
    'v': 'в', 'V': 'В',
    'x': 'х', 'X': 'Х',
    'y': 'й', 'Y': 'Й',
    'z': 'з', 'Z': 'З',
    "'": 'ъ', "’": 'ъ', "‘": 'ъ'
}

# Regex to identify HTML tags, URLs, @usernames, and code blocks that must NOT be transliterated
PROTECTED_PATTERN = re.compile(
    r'(@[a-zA-Z0-9_]+|<[^>]+>|https?://[^\s<>]+|tg://[^\s<>]+)'
)

def _transliterate_plain_text(text: str) -> str:
    """Translates a pure string of Latin Uzbek to Cyrillic."""
    result = text
    # 1. Multi-letter combinations
    for lat, cyr in LATIN_TO_CYRILLIC_PAIRS:
        result = result.replace(lat, cyr)
    # 2. Single characters
    out = []
    for ch in result:
        out.append(SINGLE_LATIN_TO_CYRILLIC.get(ch, ch))
    return "".join(out)

def latin_to_cyrillic(text: str) -> str:
    """
    Translates Latin Uzbek text to Cyrillic safely, preserving HTML tags,
    links, and formatting.
    """
    if not text:
        return text

    # Split into protected tokens (HTML tags, URLs) and plain text tokens
    parts = PROTECTED_PATTERN.split(text)
    translated_parts = []

    for part in parts:
        if not part:
            continue
        if part.startswith("<") and part.endswith(">"):
            # HTML tag, keep exact
            translated_parts.append(part)
        elif part.startswith("http://") or part.startswith("https://") or part.startswith("tg://"):
            # URL, keep exact
            translated_parts.append(part)
        elif part.startswith("@"):
            # Username mention, keep exact
            translated_parts.append(part)
        else:
            # Plain text chunk
            translated_parts.append(_transliterate_plain_text(part))

    return "".join(translated_parts)

def t(text: str, script: str = "lat") -> str:
    """
    Localizes text based on chosen script:
    - 'lat': returns text in Latin as is.
    - 'cyr': returns text transliterated to Cyrillic.
    """
    if script == "cyr":
        return latin_to_cyrillic(text)
    return text

to_cyrillic = latin_to_cyrillic
to_latin = lambda text: text

