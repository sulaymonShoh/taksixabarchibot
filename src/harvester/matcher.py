"""
Driver Radar & Highway Corridor Matchmaker for Taksi Xabarchi v3.0.
Matches real-time incoming harvested passenger and cargo orders with active VIP drivers
based on their selected route directions, target districts, and transit corridors.
"""
import html
from typing import Dict, Any, List, Optional, Tuple
from src import database as db
from src.harvester.geo_data import is_in_corridor, get_corridor_districts, DISTRICTS, REGIONS, PITAKS
from src.logger import setup_logger

logger = setup_logger("harvester_matcher")

TOSHKENT_REGIONS = {"toshkent_shahar", "toshkent_viloyati"}
VODIY_REGIONS = {"andijon", "fargona", "namangan"}

class CorridorMatcher:
    """
    Sub-millisecond corridor matchmaker that pairs incoming harvested orders
    with drivers monitoring specific transport corridors and districts.
    """

    def determine_direction(self, order: Dict[str, Any]) -> str:
        """
        Determines the transit direction of an order:
        - 'toshkent_to_andijon'
        - 'andijon_to_toshkent'
        - 'unknown'
        """
        origin = order.get("origin") or {}
        dest = order.get("destination") or order.get("dest") or {}

        orig_region = origin.get("region_id") or order.get("origin_region")
        dest_region = dest.get("region_id") or order.get("dest_region")
        orig_dist = origin.get("district_id") or origin.get("id") or order.get("origin_district")
        dest_dist = dest.get("district_id") or dest.get("id") or order.get("dest_district")

        # 1. Check direct region IDs
        if orig_region in TOSHKENT_REGIONS and (dest_region == "andijon" or dest_dist in DISTRICTS and DISTRICTS[dest_dist].get("region_id") == "andijon"):
            return "toshkent_to_andijon"

        if (orig_region == "andijon" or orig_dist in DISTRICTS and DISTRICTS[orig_dist].get("region_id") == "andijon") and (dest_region in TOSHKENT_REGIONS or dest_dist in PITAKS):
            return "andijon_to_toshkent"

        # 2. Check pitaks (Qo'yliq, Rohat)
        if orig_dist in ["quyliq", "rohat"] and (dest_region == "andijon" or (dest_dist in DISTRICTS and DISTRICTS[dest_dist].get("region_id") == "andijon")):
            return "toshkent_to_andijon"

        if (orig_region == "andijon" or (orig_dist in DISTRICTS and DISTRICTS[orig_dist].get("region_id") == "andijon")) and dest_dist in ["quyliq", "rohat"]:
            return "andijon_to_toshkent"

        # 3. Unilateral cases (common in taxi chats: lone destination or lone origin)
        if not orig_region and dest_region == "andijon":
            return "toshkent_to_andijon"
        if orig_region == "andijon" and not dest_region:
            return "andijon_to_toshkent"

        # 4. Context fallback from source group region tag
        source_tag = order.get("source_region_tag", "")
        if "andijon" in source_tag:
            if not orig_region and (dest_region in TOSHKENT_REGIONS or dest_dist in PITAKS):
                return "andijon_to_toshkent"
            if not dest_region and (orig_region in TOSHKENT_REGIONS or orig_dist in PITAKS):
                return "toshkent_to_andijon"

        return "unknown"

    def get_relevant_district(self, order: Dict[str, Any], direction: str) -> Optional[str]:
        """
        Extracts the relevant Andijon corridor district for matching.
        - Toshkent -> Andijon: matching point is destination district
        - Andijon -> Toshkent: matching point is origin pickup district
        """
        origin = order.get("origin") or {}
        dest = order.get("destination") or order.get("dest") or {}

        orig_dist = origin.get("district_id") or origin.get("id") or order.get("origin_district")
        dest_dist = dest.get("district_id") or dest.get("id") or order.get("dest_district")

        if direction == "toshkent_to_andijon":
            if dest_dist and dest_dist in DISTRICTS:
                return dest_dist
            # Fallback to origin if dest is just region
            if orig_dist and orig_dist in DISTRICTS and DISTRICTS[orig_dist].get("region_id") == "andijon":
                return orig_dist

        elif direction == "andijon_to_toshkent":
            if orig_dist and orig_dist in DISTRICTS:
                return orig_dist
            if dest_dist and dest_dist in DISTRICTS and DISTRICTS[dest_dist].get("region_id") == "andijon":
                return dest_dist

        # If direction is unknown or bilateral, check either
        if dest_dist and dest_dist in DISTRICTS and DISTRICTS[dest_dist].get("region_id") == "andijon":
            return dest_dist
        if orig_dist and orig_dist in DISTRICTS and DISTRICTS[orig_dist].get("region_id") == "andijon":
            return orig_dist

        return None

    def match_driver(self, order: Dict[str, Any], driver_pref: Dict[str, Any], enforce_vip: bool = True) -> Optional[Dict[str, Any]]:
        """
        Evaluates whether an order matches a driver's radar settings.
        Returns match metadata dict if matched, or None if filtered out.
        """
        if not order or not driver_pref:
            return None

        # 1. Radar state check
        if not driver_pref.get("is_radar_active", True):
            return None

        # 2. VIP subscription check
        if enforce_vip and not driver_pref.get("is_vip", False):
            return None

        # 3. Order type check (Passenger vs Cargo)
        order_type = order.get("order_type", "PASSENGER")
        if order_type == "PASSENGER" and not driver_pref.get("allow_passenger", True):
            return None
        if order_type == "CARGO" and not driver_pref.get("allow_cargo", True):
            return None

        # 4. Route direction check
        order_dir = self.determine_direction(order)
        if order_dir == "unknown":
            return None

        driver_dir = driver_pref.get("direction", "both")
        if driver_dir != "both" and driver_dir != order_dir:
            return None

        # 5. District & Corridor Matching
        selected_districts = driver_pref.get("selected_districts", [])
        if not selected_districts:
            # Driver accepts all districts
            return {
                "driver_id": driver_pref["user_id"],
                "match_type": "ALL",
                "matched_district": None,
                "direction": order_dir,
                "sound_alerts": bool(driver_pref.get("sound_alerts", True))
            }

        target_district = self.get_relevant_district(order, order_dir)

        if not target_district:
            # Order might be regional (e.g. "Andijonga 2 kishi")
            dest = order.get("destination") or order.get("dest") or {}
            dest_reg = dest.get("region_id") or order.get("dest_region")
            orig = order.get("origin") or {}
            orig_reg = orig.get("region_id") or order.get("origin_region")

            if dest_reg == "andijon" or orig_reg == "andijon":
                return {
                    "driver_id": driver_pref["user_id"],
                    "match_type": "REGIONAL",
                    "matched_district": "andijon",
                    "direction": order_dir,
                    "sound_alerts": bool(driver_pref.get("sound_alerts", True))
                }
            return None

        # Exact district match
        if target_district in selected_districts:
            district_name = DISTRICTS.get(target_district, {}).get("name", target_district)
            return {
                "driver_id": driver_pref["user_id"],
                "match_type": "EXACT",
                "matched_district": target_district,
                "district_name": district_name,
                "direction": order_dir,
                "sound_alerts": bool(driver_pref.get("sound_alerts", True))
            }

        # Corridor neighbor match
        if is_in_corridor(target_district, selected_districts):
            via_district = None
            for d in selected_districts:
                if target_district in get_corridor_districts(d):
                    via_district = d
                    break
            district_name = DISTRICTS.get(target_district, {}).get("name", target_district)
            via_name = DISTRICTS.get(via_district, {}).get("name", via_district) if via_district else None
            return {
                "driver_id": driver_pref["user_id"],
                "match_type": "CORRIDOR",
                "matched_district": target_district,
                "district_name": district_name,
                "corridor_via": via_district,
                "corridor_via_name": via_name,
                "direction": order_dir,
                "sound_alerts": bool(driver_pref.get("sound_alerts", True))
            }

        return None

    async def match_order_to_drivers(
        self,
        order: Dict[str, Any],
        active_drivers: Optional[List[Dict[str, Any]]] = None,
        enforce_vip: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Matches an order across all active radar drivers.
        Returns a list of match metadata for all drivers who should receive this order.
        """
        if active_drivers is None:
            active_drivers = await db.get_active_radar_drivers()

        matched = []
        for driver in active_drivers:
            match_meta = self.match_driver(order, driver, enforce_vip=enforce_vip)
            if match_meta:
                matched.append(match_meta)

        return matched

    def format_notification(self, order: Dict[str, Any], match_meta: Optional[Dict[str, Any]] = None, script: str = "lat") -> str:
        """
        Formats a clean, minimal Telegram alert for the driver:
        Yo'lovchi (or Pochta)

        (original message)

        Lichka: @username or id
        Tel: +998... (if available)

        Asl xabarni ko'rish
        """
        order_type = order.get("order_type", "PASSENGER")
        if script == "cyr":
            header = "📦 Почта" if order_type == "CARGO" else "👤 Йўловчи"
            lichka_label = "Личка"
            tel_label = "Тел"
            asl_link_text = "Асл хабарни"
            korish_word = "кўриш"
            yozish_word = "Ёзиш"
        else:
            header = "📦 Pochta" if order_type == "CARGO" else "👤 Yo'lovchi"
            lichka_label = "Lichka"
            tel_label = "Tel"
            asl_link_text = "Asl xabarni"
            korish_word = "ko'rish"
            yozish_word = "Yozish"

        raw_text = html.escape(order.get("raw_text", "").strip())
        username = order.get("telegram_username")
        sender_id = order.get("sender_id")
        phone = order.get("phone_number")
        message_link = order.get("message_link")

        lines = [
            f"<b>{header}</b>",
            "",
            raw_text,
        ]

        contacts = []
        if username and not username.lstrip("@").isdigit():
            clean_user = username.replace("@", "").strip()
            contacts.append(f'{lichka_label}: <a href="https://t.me/{clean_user}">@{clean_user}</a>')
        elif sender_id:
            contacts.append(f'{lichka_label}: <a href="tg://user?id={sender_id}">{yozish_word}</a>')

        if phone:
            contacts.append(f"{tel_label}: {phone}")

        if contacts:
            lines.append("")
            lines.extend(contacts)

        if message_link:
            lines.append("")
            lines.append(f'{asl_link_text} <a href="{message_link}">{korish_word}</a>')

        return "\n".join(lines).strip()


# Singleton instance
default_matcher = CorridorMatcher()
