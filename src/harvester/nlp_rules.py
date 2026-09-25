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
    "konditsioner bor", "konditsionerli", "konditsaner", "kanditsaner", "kondisioner", "kandisoner",
    "dispecher", "dispetcher", "zakaz olaman", "zakaz olamiz", "buyurtma olamiz", "buyurtma olaman",
    "yurishga tayyor", "yolga chiqamiz", "yo'lga chiqamiz", "yulga chiqamiz",
    "bosh mashina", "bo'sh mashina", "bosh moshina", "bo'sh moshina",
    "pustoy mashina", "pustoy moshina", "pustoy", "пустой",
    "odam ovolaman", "odam olaman", "pochta olaman", "yuk olaman", "pochta olamiz", "yuk olamiz",
    "olamiz", "bulsa olamiz", "bo'lsa olamiz", "bosa olamiz", "olaman",
    "bolsa olmiz", "bo'lsa olmiz", "bosa olmiz", "bulsa olmiz", "olmiz", "ovomiz", "ovolamiz", "olvolamiz", "obketamiz", "olibketamiz",
    "ayol kishi bor", "ayol bor", "ayollar bor", "ayolar bor", "ayollarbor", "ayolarbor", "aellar bor", "aelar bor",
    "tom bagaj", "tom bagaj bor", "tom bagaji bor", "tombagaj", "tombagaj bor", "tombagajbor", "tombagaji bor", "tomida bagaj bor", "tomda bagaj",
    "yuraman", "ketaman", "kelent vaqtiga", "klient vaqtiga", "kilient vaqtiga", "kilient vaktiga",
    "klient vaktiga", "kelent vaktiga", "kliyent vaqtiga", "kilyent vaqtiga",
    "vaqtiga yuramiz", "vaktiga yuramiz", "vaqtiga chiqamiz", "vaktiga chiqamiz",
    "srochni yuramiz", "srochno yuramiz", "tezkor yuramiz", "qarab yuramiz", "qarab ketamiz",
    "benzin", "benzinda", "propan", "propanda", "metan", "metanda", "bez metan", "bez gaz",
    "pochta xizmati", "pochta xizmati bor", "puchta xizmati", "puchta xizmati bor",
    "dostavka xizmati", "dostavka xizmati bor", "taksi xizmati", "taxi xizmati",
    "biznes klass", "biznes klas", "bisnes klass", "bisnes klas", "lyuks", "komfort",
    "wi fi bor", "wifi bor", "kilik bor", "klik bor", "click bor", "payme bor",
    "odam kam", "kishi kam", "joy kam", "yo'lovchi kam", "yolovchi kam", "kam odam", "kam kishi",
    "kamdamiz", "kamdamz", "kamdamiza", "kamimiz", "kamimiz bor",
    "oldi bosh", "oldi bo'sh", "oldi bush", "oldida joy bor", "oldi mesta bosh", "oldi mesta bo'sh", "mesta bosh", "mesta bo'sh", "mesta pustoy",
    "xarkatamiz", "xarakattamiz", "xarakaddamz", "xarakatdamiz", "harakatdamiz", "xarakatamiz", "harakatamiz", "xarkatdamiz", "xarkatamz",
    "olib ketamiz", "ob ketamiz", "olib ketaman", "ob ketaman", "olib ketamz", "ob ketamz",
    "ael kishi bor", "ael bor",
    "pokiza salon", "toza salon",
    "etkazib berish xizmati", "yetkazib berish xizmati",
    "chegirmalar bor", "nomozxon", "namozxon",
    "zaril pochta", "moshina prapan", "mashina propan",
    "kandisoner", "kondisoner", "kanditsoner", "kanditsioner",
    "kredit", "nasiya", "lizing", "avtokredit", "haydovchiman", "taksisiman",
    "narxi kelishilgan", "arzon narxda olib ketaman", "arzon obketaman"
])

# Common car models pattern for regexes
CAR_MODELS_PATTERN = (
    r"(?:cobalt|kobalt|kobolt|cobolt|koblt|kobult|kobilt|kubilt|kubalt|sobalt|"
    r"gentra|jentra|jentr|gentr|jantr|gantr|"
    r"nexia|neksia|neksiya|nexiya|neksya|nexya|neksi|nexi|"
    r"lacetti|lasetti|laceti|laseti|"
    r"damas|damaz|labo|"
    r"monza|onix|oniks|spark|"
    r"matiz|matis|tico|tiko|"
    r"malibu|tracker|traktor|kaptiva|captiva|"
    r"kia|k5|hyundai|sonata|byd|chazor|epica|epika)"
)

# Pre-compiled word-boundary regexes for driver ad phrases to prevent substring collisions (e.g. "joy bor" vs "joy bormi")
DRIVER_AD_PHRASE_REGEXES: List[Pattern] = [
    re.compile(r"\b" + re.escape(p) + r"\b", re.IGNORECASE) for p in DRIVER_AD_PHRASES
]

# Regex patterns matching driver car mentions (e.g. "Cobalt bor", "Gentra yuradi", "2 kishi kerak to'laman")
DRIVER_AD_REGEXES: List[Pattern] = [
    # Car model with preceding adjective (yangi, toza, mashina, avto, m) or model alone
    re.compile(r"\b(?:yangi|toza|mashina|moshina|mashinasi|moshinasi|avto|avtomobil|avtomobili|m)\s*[:\-—]?\s*(?:model\s+)?" + CAR_MODELS_PATTERN + r"\b", re.IGNORECASE),
    # Car model followed by manufacturing year (e.g. "Kubilt 2026", "Cobalt 2024")
    re.compile(CAR_MODELS_PATTERN + r"\s+(?:20[12]\d)\b", re.IGNORECASE),
    # Car model + presence / fuel / condition
    re.compile(CAR_MODELS_PATTERN + r"\b.*?\b(?:bor|tayyor|yuradi|yurmoqchi|chiqadi|kutmoqda|propan|prapan|metan|benzin|yangi|lyuks|komfort)\b", re.IGNORECASE),
    # Driver looking for remaining passengers to fill seats (e.g. "4 ta odam kam", "2 ta kam", "1 ta kamdamiz", "4 ta kamdamz")
    re.compile(r"\b(?:[1-4]|bitta|ikkita|uchta|to'rtta|torta|bita)?\s*(?:ta\s*)?(?:odam|kishi|yo'lovchi|yolovchi|joy)?\s*kam(?:da)?(?:miz|mz|miza)?\b", re.IGNORECASE),
    re.compile(r"\b([1-4]|bitta|ikkita|uchta|to'rtta|torta|bita)[\s\.\-]*ta[\s\.\-]*kam(?:da)?(?:miz|mz|miza)?\b", re.IGNORECASE),
    re.compile(r"\bkam\s*(?:odam|kishi|yo'lovchi|yolovchi|joy)\b", re.IGNORECASE),
    # Departure schedule pitches (e.g. "klient vaqtiga yuramiz", "vaqtiga qarab yuramiz")
    re.compile(r"\b(?:klient|kelent|kilient|kliyent|kilyent|mijoz)\s*(?:vaqtiga|vaktiga|vaxtiga|vahtiga)\b", re.IGNORECASE),
    re.compile(r"\b(?:vaqtiga|vaktiga|vaxtiga|vahtiga)\s*(?:qarab\s*)?(?:yu+ramiz|yu+ramz|chiqamiz|yuriladi|ketamiz)\b", re.IGNORECASE),
    re.compile(r"\b(?:yulga|yolga|yo'lga)\s*(?:chikamiz|chiqamiz|chikamz|chiqamz)\b", re.IGNORECASE),
    re.compile(r"\b(?:srochni|srochno|sirushni|siroshni|sirochni|tezkor)\s*(?:yu+ramiz|yu+ramz|chikamiz|chiqamiz|ketamiz|yuriladi)\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}[:\.]\d{2}(?:\s*(?:dan|-|—|\.\.\.)?\s*\d{1,2}[:\.]\d{2})?\s*(?:da|ga|lar|larga|atrofida)?\s*(?:yu+ramiz|yu+ramz|yu+riladi|chiqamiz|chikamiz|chiqiladi|ketamiz|yurvommiz|yurvotmiz|yurvotti)\b", re.IGNORECASE),
    # Fuel types explicitly advertised (passengers never list fuel types)
    re.compile(r"\b(?:benzin|benzinda|propan|propanda|metan|metanda|bez\s*metan|bez\s*gaz)\b", re.IGNORECASE),
    # Service offerings (pochta xizmati bor, biznes klass)
    re.compile(r"\b(?:pochta|puchta|dostavka|taksi|taxi)\s*xizmat(?:i|lari)?\b", re.IGNORECASE),
    re.compile(r"\b(?:bisnes|biznes)\s*klass?\b", re.IGNORECASE),
    re.compile(r"\b(?:har|xar)\s*kuni\s*xizmat\b", re.IGNORECASE),
    # Driver on the move / departure pitches (harakatdamiz, xarakatamiz, harkatdamiz)
    re.compile(r"\b[hx]ar[a]?ka[td]{1,2}(?:a|da|ta)?(?:miz|mz|miza)\b", re.IGNORECASE),
    # Driver taking passengers/cargo: "odam pochtalar bo'lsa olamiz", "pochta olamz", "pchta olamiz", "pochta bolsa olmiz", "odam pochta bolsa olib ketamiz"
    re.compile(r"\b(?:odam|kishi|yo'lovchi|yolovchi|pochta|pchta|puchta|yuk)\w*(?:\s+(?:odam|kishi|yo'lovchi|yolovchi|pochta|pchta|puchta|yuk)\w*)*\s*(?:bo'lsa|bolsa|bulsa|bosa|ham|xam)?\s*(?:olamiz|olmiz|olamz|olamiza|olvolamiz|olvolamz|ovolamiz|ovomiz|olaman|olman|ovolaman|olvolaman|obketaman|olibketaman|obketamiz|olibketamiz|obketamz|(?:olib|ob)\s*ket(?:am|m)?(?:iz|z|an)|(?:olib|ob)\s*chiq(?:am|m)?(?:iz|z|an))\b", re.IGNORECASE),
    re.compile(r"\b(?:bo'lsa|bolsa|bulsa|bosa)\s*(?:olib|ob)\s*ket(?:am|m)?(?:iz|z|an)\b", re.IGNORECASE),
    re.compile(r"\b(?:olib|ob)\s*ketamiz\b", re.IGNORECASE),
    # Driver front seat vacant (excluding passenger asking "kimni oldi bo'sh")
    re.compile(r"(?<!kimni\s)\b(?:oldi|aldi)\s*(?:mesta|mesto|o'rindiq|orindiq|joy|sidenya|sedad)?\s*(?:bo'sh|bosh|bush|pustoy)\b", re.IGNORECASE),
    re.compile(r"\b(?:mesta|mesto|o'rindiq|orindiq|sidenya)\s*(?:bo'sh|bosh|bush|pustoy)\b", re.IGNORECASE),
    # Roof luggage rack
    re.compile(r"\b(?:tombagaj\w*|tom\s*(?:ida|da)?\s*bagaj\w*)\b", re.IGNORECASE),
    # Female passengers presence
    re.compile(r"\b(?:ayol|ayollar|ayolar|ael|aellar|aelar)\w*\s*(?:kishi\s*)?bor\b", re.IGNORECASE),
    # "Salonda X ta joy bor"
    re.compile(r"\b(joy|orindiq|o'rindiq)\s*(bor|qoldi)\b", re.IGNORECASE),
    # "Odam bormi" / "Kishi bormi" by driver soliciting groups
    re.compile(r"\b(odam|kishi|yo'lovchi|yolovchi)\s*(bormi|bormikin)\s*(olib|obketgani|yurishga)\b", re.IGNORECASE),
    # Phone numbers combined with car types
    re.compile(CAR_MODELS_PATTERN + r"\b.*?(?:\+?998\d{9}|\b9\d{8}\b)", re.IGNORECASE),
    # Air conditioning / Connectivity driver emojis
    re.compile(r"(?:[❄️❄]{2,}|[🛜📶]{2,})"),
    # Commercial lodging / hotel / hostel / room rental advertisements:
    re.compile(
        r"\b(?:(?:yangi|arzon|lyuks)?\s*(?:mexmonxona|mehmonxona|hostel|xostel)|gostinitsa|yotoqxona)\b.*?\b(?:xona\w*|kishi\s*boshiga|sum|so\'m|kunlik|kruglosutochn\w*|\d+\s*ming)\b"
        r"|\b(?:obshiy\s*xona\w*|aloxida\s*xona\w*|alohida\s*xona\w*|kunlik\s*(?:kvartira|ijara|arenda))\b",
        re.IGNORECASE
    ),
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
    re.compile(r"\b(pochta|posilka|dokument|hujjat|pasport|sumka|qop|karobka|korobka)\s*(bor|bervorgani|berib yuborgani|ketishi kerak|yuborish kerak|opketish kere|olib ketish kerak)\b", re.IGNORECASE),
    # "Yuk bor [destination]"
    re.compile(r"\b(yuk|kichik yuk|yukcha)\s*(bor|yuborishga|ketadi)\b", re.IGNORECASE),
    # Cargo appliances / items: "kir moshina bor", "kirmoshinabor", "muzlatgich bor", "televizor beraman"
    re.compile(r"\b(?:kir\s*moshina|kirmoshina|kir\s*mashina|kirmashina|muzlatgich|xolodilnik|televizor|gaz\s*plita|gilam|velosiped|motor)\w*.*?\b(?:bor|beraman|yuboraman|bervorgani|berib\s*yuborgani|opketish|olib\s*ketish|berish\s*kerak)\b", re.IGNORECASE),
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
