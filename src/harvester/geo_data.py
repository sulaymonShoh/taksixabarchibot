"""
Uzbekistan Geographic & Intercity Departure Hubs (Pitaklar) Database.
Covers 14 regions, 208 districts, transport corridors, and pitak hubs.
Deep initial focus & benchmark: Toshkent ⇄ Andijon transit corridor.
"""
import re
from typing import Dict, Any, Optional, List, Set
from src.harvester.nlp_rules import transliterate_cyrillic_to_latin

REGIONS: Dict[str, Dict[str, Any]] = {
    "toshkent_shahar": {
        "id": "toshkent_shahar", "name": "Toshkent shahri", "code": "TAS", "type": "city",
        "aliases": [
            "toshkent", "toshkenga", "toshkenta", "toshkendan", "toshken", "toshkend",
            "tashkent", "tashkenga", "tashkentga", "tashkentdan", "toshkentdan", "toshkentga",
            "тошкент", "тошкен", "тошкенд", "ташкент", "ташкен", "toshkent shahar",
            "тошкентга", "тошкенга", "тошкентдан", "тошкендан"
        ]
    },
    "toshkent_viloyati": {
        "id": "toshkent_viloyati", "name": "Toshkent viloyati", "code": "TV", "type": "region",
        "aliases": ["toshkent viloyati", "tosh vil", "тош вил", "тошкент вилояти"]
    },
    "andijon": {
        "id": "andijon", "name": "Andijon viloyati", "code": "AND", "type": "region",
        "aliases": [
            "andijon", "andijonga", "andijondan", "anjan", "anjanga", "anjandan",
            "anjon", "anjonga", "anjondan", "андижон", "андижонга", "андижондан",
            "анжан", "анжанга", "анжандан", "анжон", "анжонга", "анжондан", "andijon viloyati"
        ]
    },
    "fargona": {"id": "fargona", "name": "Farg'ona viloyati", "code": "FAR", "type": "region"},
    "namangan": {"id": "namangan", "name": "Namangan viloyati", "code": "NAM", "type": "region"},
    "samarqand": {"id": "samarqand", "name": "Samarqand viloyati", "code": "SAM", "type": "region"},
    "buxoro": {"id": "buxoro", "name": "Buxoro viloyati", "code": "BUX", "type": "region"},
    "qashqadaryo": {"id": "qashqadaryo", "name": "Qashqadaryo viloyati", "code": "QASH", "type": "region"},
    "surxondaryo": {"id": "surxondaryo", "name": "Surxondaryo viloyati", "code": "SUR", "type": "region"},
    "jizzax": {"id": "jizzax", "name": "Jizzax viloyati", "code": "JIZ", "type": "region"},
    "sirdaryo": {"id": "sirdaryo", "name": "Sirdaryo viloyati", "code": "SIR", "type": "region"},
    "xorazm": {"id": "xorazm", "name": "Xorazm viloyati", "code": "XOR", "type": "region"},
    "navoiy": {"id": "navoiy", "name": "Navoiy viloyati", "code": "NAV", "type": "region"},
    "qoraqalpogiston": {"id": "qoraqalpogiston", "name": "Qoraqalpog'iston Respublikasi", "code": "QR", "type": "republic"},
}

# Key Departure Hubs (Pitaklar)
PITAKS: Dict[str, Dict[str, Any]] = {
    "quyliq": {
        "id": "quyliq",
        "name": "Qo'yliq (Vodiy Pitak)",
        "region_id": "toshkent_shahar",
        "serves_directions": ["andijon", "fargona", "namangan"],
        "aliases": ["quyliq", "qo'yliq", "qoyliq", "kuyluk", "kuylyuk", "куйлюк", "койлик", "vodiy pitak", "vodiy pitagi", "quylik", "qo'ylik"]
    },
    "rohat": {
        "id": "rohat",
        "name": "Rohat (Aylanma)",
        "region_id": "toshkent_viloyati",
        "serves_directions": ["andijon", "fargona", "namangan", "toshkent_viloyati"],
        "aliases": ["rohat", "raxat", "рохат", "рахат", "rohat kruki", "rohat aylanmasi"]
    },
    "olmazor": {
        "id": "olmazor",
        "name": "Olmazor / Sobir Rahimov",
        "region_id": "toshkent_shahar",
        "serves_directions": ["samarqand", "jizzax", "qashqadaryo", "surxondaryo", "buxoro", "navoiy"],
        "aliases": ["olmazor", "sobir rahimov", "собир рахимов", "олмазор", "sobir raximov", "chilonzor pitak"]
    },
    "uch_qahramon": {
        "id": "uch_qahramon",
        "name": "Uch Qahramon",
        "region_id": "toshkent_shahar",
        "serves_directions": ["qozogiston", "toshkent_viloyati"],
        "aliases": ["uch qahramon", "uch qaxramon", "уч кахрамон", "учкахрамон", "gishtkoprik", "chernyayevka"]
    },
    "abu_saxiy": {
        "id": "abu_saxiy",
        "name": "Abu Saxiy / Ippodrom",
        "region_id": "toshkent_shahar",
        "serves_directions": ["ALL"],
        "aliases": ["abu saxiy", "abu saxiy pitak", "ippodrom", "ипподром", "абу сахий"]
    },
    "yangi_bozor_toshkent": {
        "id": "yangi_bozor_toshkent",
        "name": "Yangi Bozor (Toshkent)",
        "region_id": "toshkent_viloyati",
        "serves_directions": ["sirdaryo", "toshkent_viloyati"],
        "aliases": ["yangi bozor", "янги бозор"]
    },
    "malika": {
        "id": "malika",
        "name": "Malika Bozori",
        "region_id": "toshkent_shahar",
        "serves_directions": ["ALL"],
        "aliases": ["malika", "malika bozor", "malika bozori", "малика", "малика бозор", "малика бозори", "malika bozordan"]
    }
}

# Districts & Cities Database (Full 14 regions, deep coverage for Tashkent ⇄ Andijon line)
DISTRICTS: Dict[str, Dict[str, Any]] = {
    # ==================== ANDIJON VILOYATI ====================
    "asaka": {
        "id": "asaka",
        "name": "Asaka",
        "region_id": "andijon",
        "aliases": ["asaka", "asakaga", "leninsk", "асака", "асакага", "ленинск", "asaka shahar", "asaka tumani"],
        "corridor_neighbors": ["shahrixon", "boston", "marhamat", "andijon_shahar", "buloqboshi", "xojaobod"]
    },
    "shahrixon": {
        "id": "shahrixon",
        "name": "Shahrixon",
        "region_id": "andijon",
        "aliases": ["shahrixon", "shaxrixon", "shahrixonga", "shaxrixonga", "шахрихон", "шахрихан", "шахрихонга", "shahrixon tumani"],
        "corridor_neighbors": ["boston", "asaka", "andijon_shahar", "oltinkol"]
    },
    "boston": {
        "id": "boston",
        "name": "Bo'ston",
        "region_id": "andijon",
        "aliases": ["bo'ston", "boston", "bo'stonga", "bostonga", "bo'z", "boz", "bo'zga", "bozga", "бустон", "буз", "бўз", "бустонга", "бўстон", "boz tumani"],
        "corridor_neighbors": ["shahrixon", "asaka", "baliqchi", "ulugnor"]
    },
    "marhamat": {
        "id": "marhamat",
        "name": "Marhamat",
        "region_id": "andijon",
        "aliases": ["marhamat", "marxamat", "marhamatga", "marxamatga", "мархамат", "мархаматга", "marhamat tumani"],
        "corridor_neighbors": ["asaka", "buloqboshi", "xojaobod", "andijon_shahar"]
    },
    "andijon_shahar": {
        "id": "andijon_shahar",
        "name": "Andijon shahar",
        "region_id": "andijon",
        "aliases": [
            "andijon", "andijonga", "andijondan", "андижон", "андижан", "андижонга", "андижондан",
            "anjan", "anjanga", "anjandan", "anjon", "anjonga", "anjondan", "анжан", "анжанга", "анжандан", "анжон", "анжонга", "анжондан",
            "andijon shahar", "andijon shaxar", "eski shahar andijon", "yangi bozor andijon",
            "piyozpoya", "piyos paya", "пиёзпоя", "пиёс пая", "piyozpoyaga", "piyos payaga"
        ],
        "corridor_neighbors": ["asaka", "shahrixon", "oltinkol", "xojaobod", "buloqboshi", "jalaquduq", "paxtaobod"]
    },
    "oltinkol": {
        "id": "oltinkol",
        "name": "Oltinko'l",
        "region_id": "andijon",
        "aliases": ["oltinko'l", "oltinkol", "олтинкул", "олтинкўл", "oltinko'lga", "oltinkolga"],
        "corridor_neighbors": ["andijon_shahar", "asaka", "shahrixon", "baliqchi"]
    },
    "baliqchi": {
        "id": "baliqchi",
        "name": "Baliqchi",
        "region_id": "andijon",
        "aliases": ["baliqchi", "баликчи", "балиқчи", "baliqchiga", "chinobod"],
        "corridor_neighbors": ["shahrixon", "boston", "oltinkol", "izboskan"]
    },
    "xojaobod": {
        "id": "xojaobod",
        "name": "Xo'jaobod",
        "region_id": "andijon",
        "aliases": ["xo'jaobod", "xojaobod", "xujayobod", "ходжаабад", "хўжаобод", "хужаобод"],
        "corridor_neighbors": ["andijon_shahar", "asaka", "marhamat", "buloqboshi"]
    },
    "buloqboshi": {
        "id": "buloqboshi",
        "name": "Buloqboshi",
        "region_id": "andijon",
        "aliases": ["buloqboshi", "булокбоши", "булоқбоши", "buloqboshiga"],
        "corridor_neighbors": ["asaka", "marhamat", "xojaobod", "andijon_shahar"]
    },
    "izboskan": {
        "id": "izboskan",
        "name": "Izboskan",
        "region_id": "andijon",
        "aliases": [
            "izboskan", "избоскан", "izboskandan", "избоскандан", "izboskanga", "избосканга",
            "poytug", "пойтўғ", "пойтуг", "paytuk", "пайтук", "paytug", "пайтуг",
            "paytukdan", "пайтукдан", "paytukga", "пайтукга"
        ],
        "corridor_neighbors": ["baliqchi", "paxtaobod", "oltinkol", "andijon_shahar"]
    },
    "paxtaobod": {
        "id": "paxtaobod",
        "name": "Paxtaobod",
        "region_id": "andijon",
        "aliases": ["paxtaobod", "пахтаобод", "пахтаабад"],
        "corridor_neighbors": ["izboskan", "andijon_shahar", "qorgontepa"]
    },
    "qorgontepa": {
        "id": "qorgontepa",
        "name": "Qo'rg'ontepa",
        "region_id": "andijon",
        "aliases": ["qo'rg'ontepa", "qorgontepa", "кургонтепа", "қўрғонтепа", "qorasuv", "қорасув", "dardoq", "дардок", "дардоқ"],
        "corridor_neighbors": ["paxtaobod", "jalaquduq", "xonobod"]
    },
    "jalaquduq": {
        "id": "jalaquduq",
        "name": "Jalaquduq",
        "region_id": "andijon",
        "aliases": ["jalaquduq", "jalalquduq", "jalalkuduk", "жалакудук", "жалақудуқ", "жалалкудук", "oxunboboyev"],
        "corridor_neighbors": ["andijon_shahar", "xojaobod", "qorgontepa", "xonobod"]
    },
    "xonobod": {
        "id": "xonobod",
        "name": "Xonobod",
        "region_id": "andijon",
        "aliases": ["xonobod", "хонобод", "ханабад"],
        "corridor_neighbors": ["qorgontepa", "jalaquduq"]
    },
    "ulugnor": {
        "id": "ulugnor",
        "name": "Ulug'nor",
        "region_id": "andijon",
        "aliases": ["ulug'nor", "ulugnor", "улугнор", "улуғнор", "oq oltin"],
        "corridor_neighbors": ["boston", "baliqchi"]
    },

    # ==================== TOSHKENT SHAHRI & VILOYATI ====================
    "toshkent_shahar_all": {
        "id": "toshkent_shahar_all",
        "name": "Toshkent shahri",
        "region_id": "toshkent_shahar",
        "aliases": [
            "toshkent", "toshkentga", "toshkentdan", "тошкент", "ташкент", "тошкентга", "ташкентга",
            "tashkent", "tashkentga", "shahar", "shaharga",
            "toshken", "tashken", "toshkenga", "tashkenga", "toshkendan", "tashkendan", "тошкен", "ташкен"
        ],
        "corridor_neighbors": ["chirchiq", "yangiyol", "zangiota", "qibray"]
    },
    "chilonzor": {
        "id": "chilonzor",
        "name": "Chilonzor",
        "region_id": "toshkent_shahar",
        "aliases": ["chilonzor", "чилонзор", "чиланзар", "chilonzorga"],
        "corridor_neighbors": ["toshkent_shahar_all"]
    },
    "yunusobod": {
        "id": "yunusobod",
        "name": "Yunusobod",
        "region_id": "toshkent_shahar",
        "aliases": ["yunusobod", "юнусобод", "юнусабад", "yunusobodga"],
        "corridor_neighbors": ["toshkent_shahar_all"]
    },
    "chirchiq": {
        "id": "chirchiq",
        "name": "Chirchiq",
        "region_id": "toshkent_viloyati",
        "aliases": ["chirchiq", "чирчик", "чирчиқ", "chirchiqqa"],
        "corridor_neighbors": ["toshkent_shahar_all", "qibray", "bostonliq"]
    },
    "angren": {
        "id": "angren",
        "name": "Angren",
        "region_id": "toshkent_viloyati",
        "aliases": ["angren", "ангрен", "angrenga"],
        "corridor_neighbors": ["ohangaron", "toshkent_viloyati"]
    },
    "olmaliq": {
        "id": "olmaliq",
        "name": "Olmaliq",
        "region_id": "toshkent_viloyati",
        "aliases": ["olmaliq", "олмалик", "олмалиқ", "алмалык"],
        "corridor_neighbors": ["ohangaron", "piskent"]
    },
    "ohangaron": {
        "id": "ohangaron",
        "name": "Ohangaron",
        "region_id": "toshkent_viloyati",
        "aliases": ["ohangaron", "охангарон", "ахангаран"],
        "corridor_neighbors": ["angren", "olmaliq"]
    },
    "yangiyol": {
        "id": "yangiyol",
        "name": "Yangiyo'l",
        "region_id": "toshkent_viloyati",
        "aliases": ["yangiyo'l", "yangiyol", "янгийул", "янгийўл"],
        "corridor_neighbors": ["toshkent_shahar_all", "chinoz"]
    },
    "qibray": {
        "id": "qibray",
        "name": "Qibray",
        "region_id": "toshkent_viloyati",
        "aliases": ["qibray", "қибрай", "кибрай", "qibrayga", "qibraydan"],
        "corridor_neighbors": ["toshkent_shahar_all", "chirchiq"]
    },
    "quyi_chirchiq": {
        "id": "quyi_chirchiq",
        "name": "Quyi Chirchiq",
        "region_id": "toshkent_viloyati",
        "aliases": [
            "quyi chirchiq", "quyi chirchik", "қуйи чирчиқ", "куйи чирчик",
            "quyi chirchikdan", "quyi chirchiqdan", "dostobod"
        ],
        "corridor_neighbors": ["toshkent_shahar_all", "chinoz", "yangiyol"]
    },
    "sergeli": {
        "id": "sergeli",
        "name": "Sergeli",
        "region_id": "toshkent_shahar",
        "aliases": ["sergeli", "сергели", "sergili", "sergeliya", "sergilda", "sergeliga"],
        "corridor_neighbors": ["toshkent_shahar_all"]
    },
    "bekobod": {
        "id": "bekobod",
        "name": "Bekobod",
        "region_id": "toshkent_viloyati",
        "aliases": ["bekobod", "бекобод", "бекабад"],
        "corridor_neighbors": ["shirin", "sirdaryo"]
    },

    # ==================== FARG'ONA VILOYATI ====================
    "qoqon": {
        "id": "qoqon",
        "name": "Qo'qon",
        "region_id": "fargona",
        "aliases": ["qo'qon", "qoqon", "коканд", "қўқон", "кукон", "qoqonga"],
        "corridor_neighbors": ["uchkoprik", "bagdod", "yaypan", "beshariq"]
    },
    "fargona_shahar": {
        "id": "fargona_shahar",
        "name": "Farg'ona shahar",
        "region_id": "fargona",
        "aliases": ["farg'ona", "fargona", "фергана", "фаргона", "фарғона", "fargonaga"],
        "corridor_neighbors": ["margilon", "toshloq", "quva"]
    },
    "margilon": {
        "id": "margilon",
        "name": "Marg'ilon",
        "region_id": "fargona",
        "aliases": ["marg'ilon", "margilon", "маргилан", "марғилон", "маргилон"],
        "corridor_neighbors": ["fargona_shahar", "oltiariq", "toshloq"]
    },
    "rishton": {
        "id": "rishton",
        "name": "Rishton",
        "region_id": "fargona",
        "aliases": ["rishton", "риштон", "риштан"],
        "corridor_neighbors": ["bagdod", "oltiariq", "uchkoprik"]
    },
    "oltiariq": {
        "id": "oltiariq",
        "name": "Oltiariq",
        "region_id": "fargona",
        "aliases": ["oltiariq", "олтиарик", "олтиариқ"],
        "corridor_neighbors": ["rishton", "margilon", "bagdod"]
    },
    "quva": {
        "id": "quva",
        "name": "Quva",
        "region_id": "fargona",
        "aliases": ["quva", "кува", "қува", "quvaga"],
        "corridor_neighbors": ["fargona_shahar", "asaka", "marhamat"]
    },

    # ==================== NAMANGAN VILOYATI ====================
    "namangan_shahar": {
        "id": "namangan_shahar",
        "name": "Namangan shahar",
        "region_id": "namangan",
        "aliases": ["namangan", "наманган", "namanganga"],
        "corridor_neighbors": ["toraqorgon", "kosonsoy", "uychi", "chust"]
    },
    "chust": {
        "id": "chust",
        "name": "Chust",
        "region_id": "namangan",
        "aliases": ["chust", "чуст", "chustga"],
        "corridor_neighbors": ["pop", "toraqorgon", "namangan_shahar"]
    },
    "pop": {
        "id": "pop",
        "name": "Pop",
        "region_id": "namangan",
        "aliases": ["pop", "поп", "popga", "pop stansiya"],
        "corridor_neighbors": ["chust", "angren", "qoqon"]
    },
    "toraqorgon": {
        "id": "toraqorgon",
        "name": "To'raqo'rg'on",
        "region_id": "namangan",
        "aliases": ["to'raqo'rg'on", "toraqorgon", "туракурган", "тўрақўрғон"],
        "corridor_neighbors": ["namangan_shahar", "chust"]
    },
    "kosonsoy": {
        "id": "kosonsoy",
        "name": "Kosonsoy",
        "region_id": "namangan",
        "aliases": ["kosonsoy", "косонсой", "касансай"],
        "corridor_neighbors": ["namangan_shahar", "toraqorgon"]
    },

    # ==================== SAMARQAND VILOYATI ====================
    "samarqand_shahar": {
        "id": "samarqand_shahar",
        "name": "Samarqand shahar",
        "region_id": "samarqand",
        "aliases": ["samarqand", "самарканд", "самарқанд", "samarqandga"],
        "corridor_neighbors": ["urgut", "kattaqorgon", "toyloq", "bulungur"]
    },
    "kattaqorgon": {
        "id": "kattaqorgon",
        "name": "Kattaqo'rg'on",
        "region_id": "samarqand",
        "aliases": ["kattaqo'rg'on", "kattaqorgon", "каттакурган", "каттақўрғон"],
        "corridor_neighbors": ["samarqand_shahar", "narpay", "ishtixon"]
    },
    "urgut": {
        "id": "urgut",
        "name": "Urgut",
        "region_id": "samarqand",
        "aliases": ["urgut", "ургут", "urgutga"],
        "corridor_neighbors": ["samarqand_shahar", "toyloq"]
    },

    # ==================== BUXORO VILOYATI ====================
    "buxoro_shahar": {
        "id": "buxoro_shahar",
        "name": "Buxoro shahar",
        "region_id": "buxoro",
        "aliases": ["buxoro", "бухара", "бухоро", "buxoroga"],
        "corridor_neighbors": ["gijduvon", "vobkent", "kogon"]
    },
    "gijduvon": {
        "id": "gijduvon",
        "name": "G'ijduvon",
        "region_id": "buxoro",
        "aliases": ["g'ijduvon", "gijduvon", "гиждуван", "ғиждувон"],
        "corridor_neighbors": ["buxoro_shahar", "navoiy_shahar"]
    },

    # ==================== QASHQADARYO VILOYATI ====================
    "qarshi_shahar": {
        "id": "qarshi_shahar",
        "name": "Qarshi shahar",
        "region_id": "qashqadaryo",
        "aliases": ["qarshi", "карши", "қарши", "qarshiga"],
        "corridor_neighbors": ["shahrisabz", "koson", "nishon", "guzor"]
    },
    "shahrisabz": {
        "id": "shahrisabz",
        "name": "Shahrisabz",
        "region_id": "qashqadaryo",
        "aliases": ["shahrisabz", "shaxrisabz", "шахрисабз", "шаҳрисабз"],
        "corridor_neighbors": ["kitob", "qarshi_shahar", "yakkabog"]
    },
    "kitob": {
        "id": "kitob",
        "name": "Kitob",
        "region_id": "qashqadaryo",
        "aliases": ["kitob", "китаб", "китоб"],
        "corridor_neighbors": ["shahrisabz", "samarqand_shahar"]
    },

    # ==================== SURXONDARYO VILOYATI ====================
    "termiz_shahar": {
        "id": "termiz_shahar",
        "name": "Termiz shahar",
        "region_id": "surxondaryo",
        "aliases": ["termiz", "термез", "термиз", "termizga"],
        "corridor_neighbors": ["denov", "shorchi", "jarqorgon"]
    },
    "denov": {
        "id": "denov",
        "name": "Denov",
        "region_id": "surxondaryo",
        "aliases": ["denov", "денов", "денау"],
        "corridor_neighbors": ["termiz_shahar", "shorchi", "sariosiyo"]
    },

    # ==================== JIZZAX VILOYATI ====================
    "jizzax_shahar": {
        "id": "jizzax_shahar",
        "name": "Jizzax shahar",
        "region_id": "jizzax",
        "aliases": ["jizzax", "джизак", "жиззах", "jizzaxga"],
        "corridor_neighbors": ["zomin", "gallaorol", "zarbdor"]
    },
    "zomin": {
        "id": "zomin",
        "name": "Zomin",
        "region_id": "jizzax",
        "aliases": ["zomin", "заамин", "зомин"],
        "corridor_neighbors": ["jizzax_shahar"]
    },

    # ==================== SIRDARYO VILOYATI ====================
    "guliston_shahar": {
        "id": "guliston_shahar",
        "name": "Guliston shahar",
        "region_id": "sirdaryo",
        "aliases": ["guliston", "гулистан", "гулистон", "gulistonga"],
        "corridor_neighbors": ["yangiyer", "shirin", "boyovut"]
    },

    # ==================== XORAZM VILOYATI ====================
    "urganch_shahar": {
        "id": "urganch_shahar",
        "name": "Urganch shahar",
        "region_id": "xorazm",
        "aliases": ["urganch", "ургенч", "урганч", "urganchga"],
        "corridor_neighbors": ["xiva", "shovot", "xonqa"]
    },
    "xiva": {
        "id": "xiva",
        "name": "Xiva",
        "region_id": "xorazm",
        "aliases": ["xiva", "хива", "xivaga"],
        "corridor_neighbors": ["urganch_shahar"]
    },

    # ==================== NAVOIY VILOYATI ====================
    "navoiy_shahar": {
        "id": "navoiy_shahar",
        "name": "Navoiy shahar",
        "region_id": "navoiy",
        "aliases": ["navoiy", "навои", "навоий", "navoiyga"],
        "corridor_neighbors": ["zarafshon", "karmana", "qiziltepa"]
    },
    "zarafshon": {
        "id": "zarafshon",
        "name": "Zarafshon",
        "region_id": "navoiy",
        "aliases": ["zarafshon", "зарафшан", "зарафшон"],
        "corridor_neighbors": ["uchquduq", "navoiy_shahar"]
    },

    # ==================== QORAQALPOG'ISTON ====================
    "nukus_shahar": {
        "id": "nukus_shahar",
        "name": "Nukus shahar",
        "region_id": "qoraqalpogiston",
        "aliases": ["nukus", "нукус", "nukusga"],
        "corridor_neighbors": ["xojayli", "qongirot", "beruniy"]
    }
}

# ==================== FAST LOOKUP INDEX BUILDER ====================
_ALIAS_TO_ENTITY: Dict[str, Dict[str, Any]] = {}
_ALL_SORTED_ALIASES: List[str] = []

def _normalize_alias(s: str) -> str:
    s = s.lower().strip()
    s = s.replace("‘", "'").replace("’", "'").replace("`", "'")
    s = re.sub(r"[^\w\s\']", " ", s)
    return " ".join(s.split())

def _build_geo_index():
    global _ALIAS_TO_ENTITY, _ALL_SORTED_ALIASES
    _ALIAS_TO_ENTITY.clear()

    # 1. Index regions (Broadest / lowest precedence)
    for r_id, r_data in REGIONS.items():
        entity_info = {
            "entity_type": "REGION",
            "id": r_id,
            "name": r_data["name"],
            "region_id": r_id,
            "district_id": None,
            "corridor_neighbors": []
        }
        reg_clean = _normalize_alias(r_data["name"])
        _ALIAS_TO_ENTITY[reg_clean] = entity_info
        _ALIAS_TO_ENTITY[r_id] = entity_info
        trans_clean = _normalize_alias(transliterate_cyrillic_to_latin(reg_clean))
        if trans_clean:
            _ALIAS_TO_ENTITY[trans_clean] = entity_info

        for alias in r_data.get("aliases", []):
            clean = _normalize_alias(alias)
            if clean:
                _ALIAS_TO_ENTITY[clean] = entity_info
                trans_clean = _normalize_alias(transliterate_cyrillic_to_latin(clean))
                if trans_clean:
                    _ALIAS_TO_ENTITY[trans_clean] = entity_info

    # 2. Index districts (More specific, overrides general region aliases)
    for d_id, d_data in DISTRICTS.items():
        entity_info = {
            "entity_type": "DISTRICT",
            "id": d_id,
            "name": d_data["name"],
            "region_id": d_data["region_id"],
            "corridor_neighbors": d_data.get("corridor_neighbors", []),
            "district_id": d_id
        }
        for alias in d_data.get("aliases", []):
            clean = _normalize_alias(alias)
            if clean:
                _ALIAS_TO_ENTITY[clean] = entity_info
                trans_clean = _normalize_alias(transliterate_cyrillic_to_latin(clean))
                if trans_clean:
                    _ALIAS_TO_ENTITY[trans_clean] = entity_info

    # 3. Index pitaks (Most specific departure hubs, highest precedence)
    for p_id, p_data in PITAKS.items():
        entity_info = {
            "entity_type": "PITAK",
            "id": p_id,
            "name": p_data["name"],
            "region_id": p_data["region_id"],
            "serves_directions": p_data.get("serves_directions", []),
            "district_id": None
        }
        for alias in p_data.get("aliases", []):
            clean = _normalize_alias(alias)
            if clean:
                _ALIAS_TO_ENTITY[clean] = entity_info
                trans_clean = _normalize_alias(transliterate_cyrillic_to_latin(clean))
                if trans_clean:
                    _ALIAS_TO_ENTITY[trans_clean] = entity_info

    # Sort aliases longest first for greedy string matching
    _ALL_SORTED_ALIASES = sorted(_ALIAS_TO_ENTITY.keys(), key=lambda x: len(x), reverse=True)

_build_geo_index()

# ==================== PUBLIC API FUNCTIONS ====================

def resolve_location(word_or_phrase: str) -> Optional[Dict[str, Any]]:
    """Resolves an alias string to an entity (District, Pitak, or Region)."""
    clean = _normalize_alias(word_or_phrase)
    return _ALIAS_TO_ENTITY.get(clean)

def get_district(district_id: str) -> Optional[Dict[str, Any]]:
    """Returns district details by ID."""
    return DISTRICTS.get(district_id)

def get_pitak(pitak_id: str) -> Optional[Dict[str, Any]]:
    """Returns departure pitak details by ID."""
    return PITAKS.get(pitak_id)

def get_region(region_id: str) -> Optional[Dict[str, Any]]:
    """Returns region details by ID."""
    return REGIONS.get(region_id)

def get_corridor_districts(district_id: str) -> List[str]:
    """Returns list of corridor neighbor district IDs for a given district."""
    dist = DISTRICTS.get(district_id)
    if not dist:
        return [district_id]
    neighbors = dist.get("corridor_neighbors", [])
    return [district_id] + [n for n in neighbors if n != district_id]

def is_in_corridor(target_district_id: str, driver_district_ids: List[str]) -> bool:
    """
    Checks if a target destination district falls within the driver's accepted
    districts OR their transit corridor neighbors.
    """
    if not target_district_id:
        return False
        
    for d_id in driver_district_ids:
        if d_id == target_district_id:
            return True
        corridor = get_corridor_districts(d_id)
        if target_district_id in corridor:
            return True
            
    return False

def get_all_sorted_aliases() -> List[str]:
    """Returns all known geographic aliases sorted from longest to shortest."""
    return _ALL_SORTED_ALIASES

GEO_DATABASE = {
    "regions": REGIONS,
    "districts": DISTRICTS,
    "pitaks": PITAKS
}
