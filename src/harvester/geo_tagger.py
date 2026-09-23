"""
Automatic Geographic Tagging & Context Detection Engine for Monitored Groups.
Analyzes group titles and usernames to infer region and district tags.
Used by Harvester to resolve missing locations in passenger orders.
"""
import re
from typing import Tuple, Optional, Dict, Any
from src.harvester.nlp_rules import transliterate_cyrillic_to_latin
from src.harvester.geo_data import DISTRICTS, REGIONS
from src.bot.translit import t

# District keyword mappings for high-precision local detection
ANDIJON_DISTRICT_KEYWORDS = {
    "asaka": ["asaka", "leninsk", "асака", "ленинск", "asaka pitak", "asaka taksi"],
    "shahrixon": ["shahrixon", "shaxrixon", "shahrixan", "шаҳрихон", "шахрихон", "shaxrixan"],
    "boston": ["boston", "bo'ston", "boz", "bo'z", "бўстон", "бўз", "боз", "boz pitak"],
    "marhamat": ["marhamat", "marxamat", "марҳамат", "мархамат"],
    "andijon_shahar": ["andijon shahar", "anjan shahar", "yangi shahar", "eski shahar", "klara setkin", "shashlik"],
    "oltinkol": ["oltinko'l", "oltinkol", "олтинкўл", "олтинкул"],
    "baliqchi": ["baliqchi", "балиқчи", "баликчи", "chinobod"],
    "paxtaobod": ["paxtaobod", "пахтаобод"],
    "buloqboshi": ["buloqboshi", "булоқбоши", "булокбоши"],
    "izboskan": ["izboskan", "poytug'", "poytug", "избоскан", "пойтуғ", "пойтуг"],
    "qorgontepa": ["qurg'ontepa", "qorgontepa", "қўрғонтепа", "кургонтепа", "qorasuv"],
    "jalolquduq": ["jalolquduq", "oxunboboyev", "oxunboboyif", "жалолқудуқ"],
    "xojaobod": ["xo'jaobod", "xojaobod", "хўжаобод", "хужаобод"],
    "ulugnor": ["ulug'nor", "ulugnor", "улуғнор", "улугнор"],
    "xonobod": ["xonobod", "хонобод"]
}

# Regional keyword mappings for province-level detection
REGIONAL_KEYWORDS = {
    "andijon": ["andijon", "anjan", "anjon", "андижон", "анжан", "анжон", "andijan", "vodiy"],
    "samarqand": ["samarqand", "samarkand", "самарқанд", "самарканд", "urgut", "kattaqo'rg'on", "kattaqorgon"],
    "fargona": ["farg'ona", "fargona", "fergana", "фарғона", "фергана", "qo'qon", "qoqon", "marg'ilon", "quva", "rishton", "oltiariq"],
    "namangan": ["namangan", "наманган", "chust", "pop", "kosonsoy", "uchqo'rg'on"],
    "buxoro": ["buxoro", "bukhara", "бухоро", "g'ijduvon", "gijduvon"],
    "qashqadaryo": ["qashqadaryo", "qarshi", "карши", "қашқадарё", "shaxrisabz", "shahrisabz", "kitob"],
    "surxondaryo": ["surxondaryo", "termiz", "термиз", "сурхондарё", "denov"],
    "xorazm": ["xorazm", "urganch", "урганч", "хоразм", "xiva"],
    "jizzax": ["jizzax", "жиззах", "zomin"],
    "sirdaryo": ["sirdaryo", "guliston", "гулистон", "гул", "сирдарё"],
    "navoiy": ["navoiy", "навоий", "zarafshon", "zarafshan"],
    "qoraqalpogiston": ["qoraqalpog'iston", "nukus", "нукус", "қорақалпоғистон"]
}

def detect_group_region(title: str, username: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """
    Analyzes group title and username to automatically extract:
    Returns (region_id, district_id).
    Example:
    - "Asaka Toshkent Vodiy Pitak" -> ("andijon", "asaka")
    - "Samarqand Toshkent Express" -> ("samarqand", None)
    - "Katta Yo'l 24/7" (ambiguous) -> ("andijon", None)
    """
    combined = f"{title or ''} {username or ''}".lower()
    norm_text = transliterate_cyrillic_to_latin(combined)

    # 1. High-precision check: Look for specific Andijon districts
    for dist_id, keywords in ANDIJON_DISTRICT_KEYWORDS.items():
        for kw in keywords:
            kw_norm = transliterate_cyrillic_to_latin(kw)
            pattern = r'\b' + re.escape(kw_norm) + r'\b'
            if re.search(pattern, norm_text) or kw_norm in norm_text:
                return ("andijon", dist_id)

    # 2. Check general regions
    for reg_id, keywords in REGIONAL_KEYWORDS.items():
        for kw in keywords:
            kw_norm = transliterate_cyrillic_to_latin(kw)
            pattern = r'\b' + re.escape(kw_norm) + r'\b'
            if re.search(pattern, norm_text) or kw_norm in norm_text:
                return (reg_id, None)

    # 3. Default fallback for intercity deployment
    return ("andijon", None)

def parse_tag_string(tag_str: Optional[str]) -> Tuple[str, Optional[str]]:
    """Parses a stored tag string (e.g. 'andijon:asaka' or 'samarqand') into (region, district)."""
    if not tag_str or tag_str.upper() == "ALL":
        return ("andijon", None)
    if ":" in tag_str:
        parts = tag_str.split(":", 1)
        return (parts[0].strip(), parts[1].strip())
    return (tag_str.strip(), None)

def format_tag_display(region_id: str, district_id: Optional[str] = None, script: str = "lat") -> str:
    """Formats human-readable display string for a region/district tag."""
    reg_obj = REGIONS.get(region_id)
    reg_name = reg_obj.get("name", region_id.capitalize()) if reg_obj else region_id.capitalize()

    if district_id and district_id in DISTRICTS:
        dist_name = DISTRICTS[district_id].get("name", district_id.capitalize())
        res = f"{reg_name.replace(' viloyati', '')} ({dist_name})"
    else:
        res = reg_name

    return t(res, script)
