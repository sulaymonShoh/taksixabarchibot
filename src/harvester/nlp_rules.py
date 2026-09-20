"""
Pre-compiled NLP Rules and Vocabulary for Uzbek Taxi Message Parsing.
Derived directly from real-world intercity Telegram taxi groups.
"""
import re
from typing import Dict, List, Pattern

# ==================== UZBEK TRANSLITERATION ====================
CYRILLIC_TO_LATIN = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
    'ж': 'j', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'x', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sh', 'ъ': "'",
    'ы': 'i', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    'ў': "o'", 'қ': 'q', 'ғ': "g'", 'ҳ': 'h'
}

def transliterate_cyrillic_to_latin(text: str) -> str:
    """Fast character-by-character Cyrillic to Latin converter."""
    out = []
    text_lower = text.lower()
    i = 0
    n = len(text_lower)
    while i < n:
        c = text_lower[i]
        # Check 2-char combinations like ў, ғ, etc.
        if c in CYRILLIC_TO_LATIN:
            out.append(CYRILLIC_TO_LATIN[c])
        else:
            out.append(c)
        i += 1
    return "".join(out)

# ==================== NEGATIVE FILTER: DRIVER ADVERTISEMENTS ====================
# Any match here means 100% REJECT (it's a driver or spam, not an order).
DRIVER_AD_PHRASES = frozenset([
    "mashina bor", "moshina bor", "moshin bor", "mashin bor", "moshina tayyor", "mashina tayyor",
    "joy bor", "joybor", "salonda joy bor", "joyimiz bor", "joy qoldi",
    "konditsioner bor", "konditsionerli", "konditsaner", "kanditsaner",
    "dispecher", "dispetcher", "zakaz olaman", "zakaz olamiz",
    "yurishga tayyor", "yolga chiqamiz", "yo'lga chiqamiz", "yulga chiqamiz",
    "bosh mashina", "bo'sh mashina", "bosh moshina", "bo'sh moshina",
    "pustoy mashina", "pustoy moshina", "pustoy", "пустой",
    "odam ovolaman", "odam olaman", "pochta olaman", "yuk olaman", "pochta olamiz", "yuk olamiz",
    "olamiz", "bulsa olamiz", "bo'lsa olamiz", "bosa olamiz", "olaman",
    "ayol kishi bor", "ayol bor", "tom bagaj", "tom bagaj bor", "tomida bagaj bor",
    "yuraman", "ketaman", "kelent vaqtiga", "klient vaqtiga", "qarab yuramiz", "qarab ketamiz",
    "kredit", "nasiya", "lizing", "avtokredit", "haydovchiman", "taksisiman",
    "narxi kelishilgan", "arzon narxda olib ketaman", "arzon obketaman"
])

# Pre-compiled word-boundary regexes for driver ad phrases to prevent substring collisions (e.g. "joy bor" vs "joy bormi")
DRIVER_AD_PHRASE_REGEXES: List[Pattern] = [
    re.compile(r"\b" + re.escape(p) + r"\b", re.IGNORECASE) for p in DRIVER_AD_PHRASES
]

# Regex patterns matching driver car mentions (e.g. "Cobalt bor", "Gentra yuradi", "2 kishi kerak to'laman")
DRIVER_AD_REGEXES: List[Pattern] = [
    # Car model (including common typos: koblt, kobult, kobilt, etc.) + presence
    re.compile(r"\b(cobalt|kobalt|koblt|kobult|kobilt|gentra|jentra|nexia|neksia|lacetti|lasetti|damas|labo|monza|onix|spark|malibu|tracker|kaptiva|captiva)\b.*?\b(bor|tayyor|yuradi|yurmoqchi|chiqadi|kutmoqda|propan|prapan|metan|yangi)\b", re.IGNORECASE),
    # Driver looking for remaining passengers to fill seats (e.g. "1 kishi kerak tolaman", "2 ta kam", "2.ta kam", "3ta kam")
    re.compile(r"\b([1-4]|bitta|ikkita|bita)\s*(kishi|odam)\s*(kerak|kere|qoldi)\b", re.IGNORECASE),
    re.compile(r"\b([1-4]|bitta|ikkita|bita)[\s\.\-]*ta[\s\.\-]*kam\b", re.IGNORECASE),
    re.compile(r"\b([1-4]|bitta|ikkita|bita)\s*(odam|kishi)\s*kam\b", re.IGNORECASE),
    # Driver taking passengers/cargo: "odam pochtalar bo'lsa olamiz", "pochta olamiz", "pchta olamiz"
    re.compile(r"\b(odam|pochta|pchta|yuk)\w*\s*(?:bo'lsa|bolsa|bulsa|bosa)?\s*(olamiz|olaman)\b", re.IGNORECASE),
    # "Salonda X ta joy bor"
    re.compile(r"\b(joy|orindiq|o'rindiq)\s*(bor|qoldi)\b", re.IGNORECASE),
    # "Odam bormi" / "Kishi bormi" by driver soliciting groups
    re.compile(r"\b(odam|kishi|yo'lovchi|yolovchi)\s*(bormi|bormikin)\s*(olib|obketgani|yurishga)\b", re.IGNORECASE),
    # Phone numbers combined with car types
    re.compile(r"\b(cobalt|kobalt|koblt|kobult|gentra|nexia|damas)\b.*?\b\+?998\d{9}\b", re.IGNORECASE),
]

# ==================== POSITIVE FILTER: PASSENGER ORDER INTENT ====================
PASSENGER_ORDER_PHRASES = frozenset([
    "odam bor", "odambor", "kishi bor", "kishibor",
    "ketadiganlar bormi", "ketadigan bormi", "ketmoqchimiz", "ketamiz", "ketishim kerak", "ketishimiz kerak",
    "mashina kerak", "moshina kerak", "mashina kere", "moshina kere", "mashina bormi", "moshina bormi",
    "bitta joy bormi", "1 kishiga joy bormi", "2 kishiga joy bormi", "joy kerak",
    "yurishga odam bor", "hozir ketishga", "ertalabga mashina kerak", "kechga mashina kerak", "abedga mashina kerak"
])

PASSENGER_ORDER_REGEXES: List[Pattern] = [
    # "X kishi bor", "X ta odam bor", "bitta odam bor"
    re.compile(r"\b([1-8]|bitta|ikkita|uchta|to'rtta|torta|beshta)\s*(kishi|odam|kishilik|odamlik)\s*(bor|ketadi|yuradi)\b", re.IGNORECASE),
    # "Odam bor [destination]"
    re.compile(r"\b(odam|kishi)\s*bor\b", re.IGNORECASE),
    # "Mashina kerak [destination]"
    re.compile(r"\b(mashina|moshina|taksi)\s*(kerak|kere|bormi|topiladimi)\b", re.IGNORECASE),
    # "Bitta joy bormi"
    re.compile(r"\b(bitta|1\s*ta|bita)\s*(joy|kishilik)\s*(bormi|kerak|kere)\b", re.IGNORECASE),
]

# ==================== POSITIVE FILTER: CARGO / POCHTA INTENT ====================
CARGO_ORDER_PHRASES = frozenset([
    "pochta bor", "pochtabor", "pochta bor edi", "pochta bormi",
    "yuk bor", "yukbor", "dostavka bor", "posilka bor",
    "sumka berib yuborish kerak", "sumka bor", "hujjat bor", "qop bor", "korobka bor",
    "kichik yuk bor", "kichkina yuk bor"
])

CARGO_ORDER_REGEXES: List[Pattern] = [
    # "Pochta bor", "Pochta ketishi kerak"
    re.compile(r"\b(pochta|posilka|dokument|hujjat|sumka|qop|karobka|korobka)\s*(bor|bervorgani|berib yuborgani|ketishi kerak|yuborish kerak)\b", re.IGNORECASE),
    # "Yuk bor [destination]"
    re.compile(r"\b(yuk|kichik yuk|yukcha)\s*(bor|yuborishga|ketadi)\b", re.IGNORECASE),
]

# ==================== PASSENGER COUNT EXTRACTION ====================
COUNT_WORDS: Dict[str, int] = {
    "bitta": 1, "bita": 1, "1ta": 1, "1 ta": 1, "1": 1, "bir": 1, "битта": 1, "бита": 1, "бир": 1,
    "ikkita": 2, "ikita": 2, "2ta": 2, "2 ta": 2, "2": 2, "ikki": 2, "ekki": 2, "ekkita": 2,
    "икки": 2, "иккита": 2, "екки": 2, "еккита": 2,
    "uchta": 3, "3ta": 3, "3 ta": 3, "3": 3, "uch": 3, "уч": 3, "учта": 3,
    "torta": 4, "to'rtta": 4, "4ta": 4, "4 ta": 4, "4": 4, "to'rt": 4, "tort": 4, "турт": 4, "туртта": 4, "торт": 4, "тортта": 4,
    "beshta": 5, "5ta": 5, "5 ta": 5, "5": 5, "besh": 5, "беш": 5, "бешта": 5,
    "salon": 4, "butun salon": 4
}

COUNT_REGEX = re.compile(
    r"\b([1-6]|bitta|bita|ikkita|ikita|ekki|ekkita|ikki|uchta|uch|to'rtta|torta|tort|to'rt|beshta|besh|битта|бита|икки|иккита|екки|еккита|уч|учта|турт|туртта|торт|беш|бешта)\s*(?:ta\s*)?(?:kishi|odam|kishilik|joy)",
    re.IGNORECASE
)

# ==================== PHONE NUMBER EXTRACTION ====================
# Matches Uzbek phone numbers in all common formats:
# +998901234567, 90 123 45 67, (90) 123-45-67, 998901234567, etc.
PHONE_REGEX = re.compile(
    r"(?:(?:\+?998)[\s\-\.]?)?\(?([93875][0-9])\)?[\s\-\.]?([0-9]{3})[\s\-\.]?([0-9]{2})[\s\-\.]?([0-9]{2})\b"
)

# ==================== DIRECTIONAL MARKERS ====================
# Markers indicating origin / destination relationships
DIR_FROM_REGEX = re.compile(r"\b([a-zA-Z'\-]+)dan\b", re.IGNORECASE)
DIR_TO_REGEX = re.compile(r"\b([a-zA-Z'\-]+)(?:ga|qa|ka)\b", re.IGNORECASE)
ARROW_DELIMITER_REGEX = re.compile(r"\s*(?:->|-->|=>|➡️|—|-|dan)\s*", re.IGNORECASE)
