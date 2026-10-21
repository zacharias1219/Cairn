"""Personal-data detection and masking.

Traces are masked by default (F10). Text is also masked before it reaches a
model whenever the step does not need the real value; where a tool needs the
real value, a reversible token is swapped back in at the tool boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)")
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", EMAIL),
    ("CARD", CARD),
    ("SSN", SSN),
    ("IBAN", IBAN),
    ("PHONE", PHONE),
]


def _luhn(digits: str) -> bool:
    d = [int(c) for c in digits if c.isdigit()]
    if len(d) < 13:
        return False
    total = 0
    for i, n in enumerate(reversed(d)):
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def find_pii(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for kind, pat in PATTERNS:
        for m in pat.finditer(text or ""):
            value = m.group(0)
            if kind == "CARD" and not _luhn(value):
                continue
            found.append((kind, value))
    return found


def mask_text(text: str) -> str:
    if not text:
        return text
    out = EMAIL.sub(lambda m: _mask_email(m.group(0)), text)
    out = CARD.sub(lambda m: "[CARD]" if _luhn(m.group(0)) else m.group(0), out)
    out = SSN.sub("[SSN]", out)
    out = IBAN.sub("[IBAN]", out)
    out = PHONE.sub(lambda m: "[PHONE •••" + re.sub(r"\D", "", m.group(0))[-2:] + "]", out)
    return out


def _mask_email(e: str) -> str:
    local, _, domain = e.partition("@")
    return f"{local[:1]}•••@{domain}"


def mask_obj(obj):
    """Mask every string inside a JSON-like value."""
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, list):
        return [mask_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: mask_obj(v) for k, v in obj.items()}
    return obj


@dataclass
class Tokenizer:
    """Reversible tokens for personal data sent to a model.

    ``protect`` replaces values with stable tokens such as ``<EMAIL_1>``;
    ``reveal`` swaps them back at the tool boundary.
    """

    forward: dict[str, str] = field(default_factory=dict)
    backward: dict[str, str] = field(default_factory=dict)

    def protect(self, text: str) -> str:
        for kind, value in find_pii(text):
            if value not in self.forward:
                token = f"<{kind}_{sum(1 for t in self.backward if t.startswith('<' + kind)) + 1}>"
                self.forward[value] = token
                self.backward[token] = value
            text = text.replace(value, self.forward[value])
        return text

    def reveal(self, value):
        if isinstance(value, str):
            for token, original in self.backward.items():
                value = value.replace(token, original)
            return value
        if isinstance(value, list):
            return [self.reveal(v) for v in value]
        if isinstance(value, dict):
            return {k: self.reveal(v) for k, v in value.items()}
        return value

    def to_state(self) -> dict:
        return {"backward": self.backward}

    @classmethod
    def from_state(cls, data: dict | None) -> "Tokenizer":
        t = cls()
        for token, original in (data or {}).get("backward", {}).items():
            t.backward[token] = original
            t.forward[original] = token
        return t
