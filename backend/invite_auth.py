"""Invitation-only demo identity; raw codes never enter platform storage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from collections import defaultdict


class InviteAuth:
    def __init__(self, code: str):
        if code and not 24 <= len(code) <= 256:
            raise RuntimeError("邀请码须为 24 至 256 个字符的随机码")
        self._code = code
        self.allowed = frozenset({self.digest(code)}) if code else frozenset()
        self._secret = code.encode("utf-8")
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    @staticmethod
    def digest(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    @staticmethod
    def owner(code_hash: str) -> str:
        return hashlib.sha256(f"myatom-invite-owner:{code_hash}".encode("ascii")).hexdigest()

    def authenticate(self, code: str, address: str) -> str | None:
        now = time.time()
        with self._lock:
            failures = [item for item in self._failures[address] if now - item < 900]
            self._failures[address] = failures
            if len(failures) >= 5:
                return None
        valid = bool(self._code) and hmac.compare_digest(code, self._code)
        if not valid:
            with self._lock:
                self._failures[address].append(now)
            return None
        with self._lock:
            self._failures.pop(address, None)
        return self.digest(self._code)

    def issue(self, code_hash: str) -> str:
        payload = json.dumps({"v": 1, "code": code_hash, "exp": int(time.time()) + 60 * 60 * 24 * 30},
                             separators=(",", ":")).encode("ascii")
        encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
        signature = hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"

    def verify(self, token: str | None) -> str | None:
        if not token or len(token) > 512 or "." not in token or not self.allowed:
            return None
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(self._secret, encoded.encode("ascii", errors="ignore"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        except (ValueError, UnicodeError):
            return None
        if not isinstance(payload, dict):
            return None
        code_hash = payload.get("code")
        if (payload.get("v") != 1 or not isinstance(payload.get("exp"), int)
                or payload["exp"] <= time.time() or not isinstance(code_hash, str)
                or code_hash not in self.allowed):
            return None
        return code_hash
