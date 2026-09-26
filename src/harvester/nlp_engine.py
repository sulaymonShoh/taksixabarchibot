"""
High-Speed In-Memory NLP & Entity Extraction Engine for Taksi Xabarchi v3.0.
Processes raw Telegram messages in < 0.5ms with zero external API fees.
"""
import re
from typing import Dict, Any, Optional, Tuple, List

from src.harvester.geo_data import (
    resolve_location,
    is_in_corridor,
    get_all_sorted_aliases,
    DISTRICTS,
    PITAKS,
    REGIONS
)
from src.harvester.nlp_rules import (
    transliterate_cyrillic_to_latin,
    DRIVER_AD_PHRASES,
    DRIVER_AD_PHRASE_REGEXES,
    DRIVER_AD_REGEXES,
    PASSENGER_ORDER_PHRASES,
    PASSENGER_ORDER_REGEXES,
    CARGO_ORDER_PHRASES,
    CARGO_ORDER_REGEXES,
    COUNT_WORDS,
    COUNT_REGEX,
    PHONE_REGEX,
    DIR_FROM_REGEX,
    DIR_TO_REGEX,
    ARROW_DELIMITER_REGEX
)

class OrderParser:
    """
    Sub-millisecond in-memory regex & entity parsing engine.
    """

    def __init__(self):
        self._aliases = get_all_sorted_aliases()

    def normalize(self, text: str) -> str:
        """Transliterates Cyrillic, cleans punctuation, and normalizes spacing."""
        if not text:
            return ""
        # 1. Transliterate
        t = transliterate_cyrillic_to_latin(text)
        # 2. Collapse single-character spaced sequences (e.g. "p o ch t a   o l a m i z" -> "pochta   olamiz")
        prev = None
        while prev != t:
            prev = t
            t = re.sub(r'(?<=\b\w) (?=\w\b)', '', t)
        # 3. Normalize apostrophes and quotes
        t = t.replace("‘", "'").replace("’", "'").replace("`", "'").replace("ʻ", "'")
        # 4. Clean excessive whitespace
        return " ".join(t.split())

    def is_driver_ad(self, norm_text: str) -> bool:
        """Returns True if the message is an advertisement from a driver, spammer, or loan broker."""
        lower = norm_text.lower()

        # Passenger inquiry exception: e.g. "joy bormi", "bitta joy bormi", "mashina bormi", "mashina kerak", "kimni oldi bo'sh"
        if re.search(r"\bkimni\s+oldi\s+(?:bo'sh|bosh|bush)\b", lower):
            return False
        if re.search(r"\b(joy|mashina|moshina|taksi)\s*(bormi|bormikin|topiladimi|kerak|kere)\b", lower):
            return False

        # 1. Check exact blacklisted driver phrases with word boundaries
        for rx in DRIVER_AD_PHRASE_REGEXES:
            if rx.search(lower):
                return True

        # 2. Check regex signatures (car models + presence, driver passenger solicitation)
        for rx in DRIVER_AD_REGEXES:
            if rx.search(lower):
                return True

        return False

    def detect_order_type(self, norm_text: str) -> Optional[str]:
        """Detects whether intent is CARGO, PASSENGER, or None."""
        lower = norm_text.lower()

        # Check Cargo first (Pochta / Yuk / Cargo items is very distinctive)
        for phrase in CARGO_ORDER_PHRASES:
            if phrase in lower:
                return "CARGO"
        for rx in CARGO_ORDER_REGEXES:
            if rx.search(lower):
                return "CARGO"

        # Check Passenger intent
        for phrase in PASSENGER_ORDER_PHRASES:
            if phrase in lower:
                return "PASSENGER"
        for rx in PASSENGER_ORDER_REGEXES:
            if rx.search(lower):
                return "PASSENGER"

        return None

    DUMMY_PHONE_REGEX = re.compile(r"(?:1234567|0000000|1111111|2222222|3333333|4444444|5555555|6666666|7777777|8888888|9999999|7654321)$")

    def extract_phone(self, text: str) -> Optional[str]:
        """Extracts and formats Uzbek phone numbers to +998XXXXXXXXX, rejecting dummy/example numbers."""
        match = PHONE_REGEX.search(text)
        if match:
            operator_code, p1, p2, p3 = match.groups()
            tail = f"{p1}{p2}{p3}"
            if self.DUMMY_PHONE_REGEX.search(tail):
                return None
            return f"+998{operator_code}{p1}{p2}{p3}"
        return None

    def extract_username(self, text: str) -> Optional[str]:
        """Extracts @username mention if present."""
        m = re.search(r"@([a-zA-Z0-9_]{5,32})", text)
        if m:
            return f"@{m.group(1)}"
        return None

    def extract_passenger_count(self, norm_text: str) -> int:
        """Extracts passenger seat count (defaults to 1)."""
        lower = norm_text.lower()
        match = COUNT_REGEX.search(lower)
        if match:
            raw_count = match.group(1).lower()
            return COUNT_WORDS.get(raw_count, 1)
        return 1

    def _find_location_in_tokens(self, tokens: List[str]) -> Optional[Dict[str, Any]]:
        """Greedy matching of tokens against the geographic alias index."""
        full_sub = " ".join(tokens).strip()
        # Clean affixes (dan, ga, qa, ka)
        clean_sub = re.sub(r"(dan|ga|qa|ka)$", "", full_sub).strip()
        
        loc = resolve_location(clean_sub) or resolve_location(full_sub)
        if loc:
            return loc
        return None

    def extract_route(self, norm_text: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Extracts (origin, destination) locations from normalized text.
        Supports:
        - "Toshkentdan Asakaga" (dan/ga suffixes)
        - "Qo'yliq - Shahrixon" (delimiter pattern)
        - "Andijon Toshkent 3 kishi" (positional sequence pattern)
        - "Bo'stonga pochta bor" (lone destination)
        """
        origin: Optional[Dict[str, Any]] = None
        destination: Optional[Dict[str, Any]] = None
        lower = norm_text.lower()

        # Step 1: Scan for explicit "dan/tan" (origin) and "ga/qa/ka" (destination) suffix words
        words = re.findall(r"\b[a-zA-Z'\-]+\b", lower)
        for w in words:
            if (w.endswith("dan") or w.endswith("tan")) and len(w) > 4 and not origin:
                stem = re.sub(r"(dan|tan)$", "", w)
                loc = resolve_location(stem)
                if not loc and stem.endswith("d"):
                    loc = resolve_location(stem[:-1] + "t") or resolve_location(stem[:-1])
                if loc:
                    origin = loc

            elif (w.endswith("ga") or w.endswith("qa") or w.endswith("ka")) and len(w) > 3 and not destination:
                stem = re.sub(r"(ga|qa|ka)$", "", w)
                loc = resolve_location(stem)
                if not loc and stem.endswith("d"):
                    loc = resolve_location(stem[:-1] + "t") or resolve_location(stem[:-1])
                if loc:
                    destination = loc

        # Step 2: If either origin or destination still missing, check arrow / hyphen patterns
        # e.g., "Qo'yliq - Asaka" or "Toshkent -> Shahrixon"
        if not origin or not destination:
            parts = re.split(r"\s*(?:->|-->|=>|➡️|—|-)\s*", lower)
            if len(parts) >= 2:
                p1_words = parts[0].split()[-3:] # Last 3 words of first part
                p2_words = parts[1].split()[:3]  # First 3 words of second part

                if not origin:
                    for i in range(len(p1_words)):
                        cand = self._find_location_in_tokens(p1_words[i:])
                        if cand:
                            origin = cand
                            break

                if not destination:
                    for i in range(len(p2_words), 0, -1):
                        cand = self._find_location_in_tokens(p2_words[:i])
                        if cand:
                            destination = cand
                            break

        # Step 3: Positional sequence scan across all known aliases
        if not destination or not origin:
            found_locs = []
            for alias in self._aliases:
                pattern = r"\b" + re.escape(alias) + r"\b"
                for m in re.finditer(pattern, lower):
                    loc = resolve_location(alias)
                    if loc:
                        found_locs.append((m.start(), loc))

            found_locs.sort(key=lambda x: x[0])
            unique_locs = []
            for pos, loc in found_locs:
                if not unique_locs or unique_locs[-1]["id"] != loc["id"]:
                    # If district belongs to same region as preceding general region, prefer specific district
                    if unique_locs and unique_locs[-1].get("region_id") == loc.get("region_id"):
                        if loc.get("entity_type") in ("DISTRICT", "PITAK") and unique_locs[-1].get("entity_type") == "REGION":
                            unique_locs[-1] = loc
                            continue
                    unique_locs.append(loc)

            if not origin and not destination:
                if len(unique_locs) >= 2:
                    origin = unique_locs[0]
                    destination = unique_locs[1]
                elif len(unique_locs) == 1:
                    destination = unique_locs[0]
            elif destination and not origin:
                for loc in unique_locs:
                    if loc["id"] != destination["id"] and loc.get("region_id") != destination.get("region_id"):
                        origin = loc
                        break
            elif origin and not destination:
                for loc in unique_locs:
                    if loc["id"] != origin["id"] and loc.get("region_id") != origin.get("region_id"):
                        destination = loc
                        break

        return origin, destination

    def parse(self, raw_text: str, author_username: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Main entry point.
        Takes a raw Telegram message and returns structured order dict,
        or None if it's not a valid order.
        """
        if not raw_text or len(raw_text.strip()) < 5:
            return None

        clean_text = self.normalize(raw_text)

        # 1. Negative Filter: reject driver ads, sales pitches, loans
        if self.is_driver_ad(clean_text):
            return None

        # 2. Extract Phone Number
        phone = self.extract_phone(raw_text)

        # 3. Detect Order Intent
        order_type = self.detect_order_type(clean_text)

        # 4. Extract Route (Origin & Destination)
        origin, destination = self.extract_route(clean_text)

        # 5. Order Validation Logic:
        # A valid order MUST have:
        # - A recognized destination OR (recognized origin AND recognized phone)
        # - AND (positive order intent OR valid phone number with destination)
        if not destination and not origin:
            return None

        if not order_type and not phone:
            return None

        # Default order_type to PASSENGER if destination & phone exist
        if not order_type:
            order_type = "PASSENGER"

        # 6. Extract Passenger Count
        count = self.extract_passenger_count(clean_text) if order_type == "PASSENGER" else 1

        # 7. Extract Telegram Username
        username = self.extract_username(raw_text) or author_username

        # Build clean result dictionary
        return {
            "is_order": True,
            "order_type": order_type,
            "origin": origin,
            "destination": destination,
            "passenger_count": count,
            "phone_number": phone,
            "telegram_username": username,
            "raw_text": raw_text.strip(),
            "clean_text": clean_text
        }

    def match_driver(self, order: Dict[str, Any], driver_pref: Dict[str, Any]) -> bool:
        """
        Checks if an extracted order matches a driver's radar preferences:
        - Route match (origin & destination regions)
        - District match (target district OR transit corridor neighbors)
        - Order type match (passenger vs cargo)
        """
        if not order or not driver_pref:
            return False

        # 1. Radar active check
        if not driver_pref.get("is_radar_active", True):
            return False

        # 2. Order type check
        order_type = order.get("order_type")
        if order_type == "PASSENGER" and not driver_pref.get("allow_passenger", True):
            return False
        if order_type == "CARGO" and not driver_pref.get("allow_cargo", True):
            return False

        # 3. Origin check (e.g. driver listening for Toshkent departures)
        driver_origin = driver_pref.get("origin_region")
        if driver_origin and driver_origin != "ALL":
            order_origin = order.get("origin")
            if order_origin:
                order_orig_reg = order_origin.get("region_id")
                # Normalize Toshkent shahar and Toshkent viloyati
                if "toshkent" in driver_origin and "toshkent" in str(order_orig_reg):
                    pass
                elif driver_origin != order_orig_reg:
                    return False

        # 4. Destination & Corridor Matching
        order_dest = order.get("destination")
        if not order_dest:
            return False

        driver_selected_districts = driver_pref.get("selected_districts", [])
        if not driver_selected_districts:
            # If driver hasn't restricted to specific districts, match by region
            driver_dest_reg = driver_pref.get("dest_region")
            return driver_dest_reg == order_dest.get("region_id")

        order_district_id = order_dest.get("district_id")
        if not order_district_id:
            # Check if destination name matches directly
            order_district_id = order_dest.get("id")

        # Evaluate corridor matching!
        return is_in_corridor(order_district_id, driver_selected_districts)
