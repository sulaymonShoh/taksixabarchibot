"""
In-Memory Fuzzy Deduplication Engine for Taksi Xabarchi v3.0.
Prevents processing or alerting on duplicate messages within a 15-minute window.
"""
import time
import hashlib
import re
from typing import Dict, Optional

class Deduplicator:
    """
    High-speed in-memory deduplication cache.
    Tracks MD5 text hashes and sender phone numbers with TTL expiration.
    """

    def __init__(self, default_ttl_seconds: int = 900): # 15 minutes default
        self.default_ttl = default_ttl_seconds
        self._hash_cache: Dict[str, float] = {}
        self._phone_cache: Dict[str, float] = {}

    def _clean_text_for_hash(self, text: str) -> str:
        """Removes emojis, punctuation, and extra spaces for fuzzy matching."""
        if not text:
            return ""
        # Lowercase and strip punctuation
        t = text.lower()
        t = re.sub(r"[^\w\s]", "", t)
        return " ".join(t.split())

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

        expired_phones = [p for p, ts in self._phone_cache.items() if current_time - ts > ttl]
        for p in expired_phones:
            del self._phone_cache[p]

    def is_duplicate(self, text: str, phone: Optional[str] = None, ttl_seconds: Optional[int] = None) -> bool:
        """
        Returns True if the exact text or the same phone number
        has been processed within the TTL window.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        now = time.time()
        self._purge_expired(now, ttl)

        # 1. Check phone deduplication if available
        if phone and phone in self._phone_cache:
            if now - self._phone_cache[phone] <= ttl:
                return True

        # 2. Check text hash deduplication
        msg_hash = self.generate_hash(text, phone)
        if msg_hash in self._hash_cache:
            if now - self._hash_cache[msg_hash] <= ttl:
                return True

        return False

    def record(self, text: str, phone: Optional[str] = None, ttl_seconds: Optional[int] = None) -> str:
        """
        Records the message and phone number into the cache.
        Returns the generated message hash.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        now = time.time()
        msg_hash = self.generate_hash(text, phone)

        self._hash_cache[msg_hash] = now
        if phone:
            self._phone_cache[phone] = now

        return msg_hash

    def clear(self):
        """Clears all cached hashes and phones."""
        self._hash_cache.clear()
        self._phone_cache.clear()

# Global default instance
default_deduplicator = Deduplicator()
