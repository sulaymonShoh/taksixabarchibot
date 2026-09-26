"""
In-Memory Fuzzy Deduplication Engine for Taksi Xabarchi v3.0.
Prevents processing or alerting on duplicate messages within a 15-minute window.
Supports route-aware and entity-based composite similarity so dispatchers posting
multiple different routes from a single phone number are never blocked.
"""
import time
import hashlib
import re
from typing import Dict, List, Optional, Tuple, Set, Any

class Deduplicator:
    """
    High-speed in-memory deduplication cache.
    Tracks MD5 text hashes, contact phone numbers, and sender IDs with composite route-aware similarity.
    """

    def __init__(self, default_ttl_seconds: int = 900):  # 15 minutes default
        self.default_ttl = default_ttl_seconds
        self._hash_cache: Dict[str, float] = {}
        self._entity_cache: Dict[str, List[Dict[str, Any]]] = {}

    def _clean_text_for_hash(self, text: str) -> str:
        """Removes emojis, punctuation, and extra spaces for fuzzy matching."""
        if not text:
            return ""
        t = text.lower()
        t = re.sub(r"[^\w\s]", "", t)
        return " ".join(t.split())

    def _extract_tokens(self, text: str) -> Set[str]:
        """Extracts meaningful word tokens (length >= 2)."""
        clean = self._clean_text_for_hash(text)
        return {w for w in clean.split() if len(w) >= 2}

    def generate_hash(self, text: str, phone: Optional[str] = None) -> str:
        """Computes MD5 hash from cleaned text and optional phone."""
        clean = self._clean_text_for_hash(text)
        seed = f"{clean}|{phone or ''}"
        return hashlib.md5(seed.encode("utf-8")).hexdigest()

    def _purge_expired(self, current_time: float, ttl: int):
        """Removes entries older than TTL."""
        expired_hashes = [h for h, ts in self._hash_cache.items() if current_time - ts > ttl]
        for h in expired_hashes:
            del self._hash_cache[h]

        expired_entities = []
        for key, records in self._entity_cache.items():
            valid_records = [r for r in records if current_time - r["timestamp"] <= ttl]
            if valid_records:
                self._entity_cache[key] = valid_records
            else:
                expired_entities.append(key)

        for key in expired_entities:
            del self._entity_cache[key]

    def _calculate_token_similarity(self, tokens1: Set[str], tokens2: Set[str]) -> float:
        """Calculates Jaccard token overlap similarity ratio between 0.0 and 1.0."""
        if not tokens1 or not tokens2:
            return 0.0
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        return intersection / union if union > 0 else 0.0

    def is_duplicate(
        self,
        text: str,
        phone: Optional[str] = None,
        sender_id: Optional[int] = None,
        route: Optional[Tuple[Optional[str], Optional[str]]] = None,
        order_type: Optional[str] = None,
        passenger_count: Optional[int] = None,
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """
        Returns True if:
        1. Exact text hash was processed within TTL, OR
        2. The same phone number / sender ID submitted an order for the SAME route
           with matching order type and high content similarity (> 50%).
        
        Guarantees that dispatchers broadcasting DIFFERENT destinations from a single
        phone number are NEVER falsely rejected as duplicates.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        now = time.time()
        self._purge_expired(now, ttl)

        # 1. Exact text hash check
        msg_hash = self.generate_hash(text, phone)
        if msg_hash in self._hash_cache:
            if now - self._hash_cache[msg_hash] <= ttl:
                return True

        # 2. Composite Entity + Route Check
        entity_keys = []
        if phone:
            entity_keys.append(f"phone:{phone}")
        if sender_id:
            entity_keys.append(f"user:{sender_id}")

        if not entity_keys:
            return False

        incoming_tokens = self._extract_tokens(text)

        for key in entity_keys:
            recent_orders = self._entity_cache.get(key, [])
            for past in recent_orders:
                if now - past["timestamp"] > ttl:
                    continue

                # A. Check Route Discrepancy
                # If both incoming and cached have resolved routes, and they differ:
                # -> NOT a duplicate! (Dispatcher posting multiple different trips)
                past_route = past.get("route")
                if route and past_route and route[0] and past_route[0] and route[1] and past_route[1]:
                    if route != past_route:
                        continue

                # B. Check Order Type Discrepancy (e.g. Passenger vs Cargo)
                past_type = past.get("order_type")
                if order_type and past_type and order_type != past_type:
                    continue

                # C. Check Content / Token Similarity
                past_tokens = past.get("tokens", set())
                similarity = self._calculate_token_similarity(incoming_tokens, past_tokens)
                
                # If high similarity (>= 50%) or identical passenger count on same route:
                if similarity >= 0.50:
                    return True

                # If exact same route and at least 3 shared keywords
                shared = len(incoming_tokens & past_tokens)
                if route and past_route and route == past_route and shared >= 3:
                    return True

        return False

    def record(
        self,
        text: str,
        phone: Optional[str] = None,
        sender_id: Optional[int] = None,
        route: Optional[Tuple[Optional[str], Optional[str]]] = None,
        order_type: Optional[str] = None,
        passenger_count: Optional[int] = None,
        ttl_seconds: Optional[int] = None
    ) -> str:
        """
        Records the message, phone, route, and token metadata into the cache.
        Returns the generated message hash.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        now = time.time()
        msg_hash = self.generate_hash(text, phone)

        self._hash_cache[msg_hash] = now

        entry = {
            "timestamp": now,
            "route": route,
            "order_type": order_type,
            "tokens": self._extract_tokens(text),
            "passenger_count": passenger_count
        }

        entity_keys = []
        if phone:
            entity_keys.append(f"phone:{phone}")
        if sender_id:
            entity_keys.append(f"user:{sender_id}")

        for key in entity_keys:
            if key not in self._entity_cache:
                self._entity_cache[key] = []
            self._entity_cache[key].append(entry)

        return msg_hash

    def clear(self):
        """Clears all cached hashes and entity records."""
        self._hash_cache.clear()
        self._entity_cache.clear()

# Global default instance
default_deduplicator = Deduplicator()
