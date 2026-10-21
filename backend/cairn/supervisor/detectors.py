"""Deterministic supervisor checks.

These run on every drafted reply before anything reaches a customer. They
are fast, explainable, and cannot be talked out of a decision, which is why
they sit next to the model judge rather than behind it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cairn.knowledge.embed import tokens
from cairn.security.pii import find_pii

VERDICT_RANK = {"approve": 0, "revise": 1, "escalate": 2, "block": 3}


@dataclass
class Check:
    name: str
    passed: bool
    verdict: str = "approve"          # the verdict this check demands when it fails
    reason_code: str = "ok"
    detail: str = ""
    feedback: str = ""                # specific guidance for the drafter on revise
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "verdict": self.verdict if not self.passed else "approve",
                "reason_code": self.reason_code, "detail": self.detail, "evidence": self.evidence[:5]}


# ------------------------------------------------------- input screening

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier|your) (instructions|rules|prompts?|guidelines)",
    r"disregard (all |any |the )?(previous|prior|above|your) (instructions|rules|policies)",
    r"forget (all |everything|your) (instructions|rules|previous)",
    r"(reveal|show|print|repeat|output|tell me) (me )?(your|the) (system|hidden|initial|original) (prompt|instructions|message)",
    r"what (is|are) your (system )?(prompt|instructions)",
    r"\byou are now\b", r"\bact as (an? )?(unrestricted|unfiltered|jailbroken|different)",
    r"\bdeveloper mode\b", r"\bDAN\b", r"\bjailbreak", r"pretend (that )?you (are|have) no (rules|restrictions|limits)",
    r"new (system )?instructions?:", r"\bsystem\s*:\s", r"</?(system|instructions?)>", r"\[\[?system\]?\]",
    r"(override|bypass|disable) (the )?(safety|policy|rules|supervisor|guardrails?|limits?)",
    r"you (must|will) (now )?(approve|issue|grant|process) (the |a |my )?(refund|credit)",
    r"(admin|administrator|manager|supervisor|developer) (here|override|mode|has approved|approved this)",
    r"i am (an? |the )?(admin|administrator|employee|developer|manager|ceo|staff)",
    r"(authorized|authorised|approved) by (the )?(ceo|manager|management|support team|admin)",
    r"base64|rot13|hex[- ]encoded",
]
_INJ = [re.compile(p, re.I) for p in INJECTION_PATTERNS]


def detect_injection(text: str) -> list[str]:
    return [m.group(0) for p in _INJ for m in [p.search(text or "")] if m]


def detect_sensitive(text: str, topics: list[dict]) -> list[dict]:
    hits = []
    low = (text or "").lower()
    for t in topics:
        for kw in t.get("keywords", []):
            if re.search(r"\b" + re.escape(kw.lower()) + r"\b", low):
                hits.append({"topic": t["name"], "keyword": kw, "action": t.get("action", "escalate")})
                break
    return hits


# ---------------------------------------------------------- reply checks

_NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?")


def _norm_num(s: str) -> str | None:
    s = s.replace("$", "").replace(",", "").rstrip("%")
    try:
        f = float(s)
    except ValueError:
        return None
    return f"{f:.2f}"


def numbers_in(text: str) -> set[str]:
    out = set()
    for m in _NUM.finditer(text or ""):
        n = _norm_num(m.group(0))
        if n is not None:
            out.add(n)
    return out


def check_grounded_figures(draft: str, evidence_text: str, allowed: set[str] | None = None) -> Check:
    allowed = allowed or set()
    have = numbers_in(evidence_text) | allowed
    # Order and reference ids are identifiers, not claims.
    stripped = re.sub(r"\b(?:A|SUB-|RF-|CR-)\d+\b|\b[A-Z]{2,}-[A-Z0-9]+\b|<\w+_\d+>", " ", draft or "")
    missing = sorted(n for n in numbers_in(stripped) if n not in have)
    if missing:
        pretty = ", ".join(m.rstrip("0").rstrip(".") for m in missing)
        return Check("grounded_figures", False, "revise", "ungrounded_figures",
                     f"Figures not found in any source, tool result or customer message: {pretty}",
                     feedback=f"Remove or correct these figures, which no source supports: {pretty}.",
                     evidence=missing)
    return Check("grounded_figures", True, detail="Every figure appears in a source or tool result")


def check_citations(draft_citations: list[str], retrieved_ids: set[str], requires: bool) -> Check:
    bad = [c for c in draft_citations if c not in retrieved_ids]
    if bad:
        return Check("citations", False, "revise", "invalid_citation",
                     f"Cites {len(bad)} source(s) that were not retrieved",
                     feedback="Only cite the retrieved sources you were given.", evidence=bad)
    if requires and not draft_citations:
        return Check("citations", False, "revise", "missing_citation",
                     "A policy answer must cite the source it relies on",
                     feedback="Cite the policy source that supports the answer.")
    return Check("citations", True, detail=f"{len(draft_citations)} valid citation(s)")


_POLICY_WORDS = {"refund", "return", "ship", "shipping", "deliver", "warranty", "exchange", "policy", "day",
                 "week", "business", "fee", "free", "cancel", "subscription", "credit", "charge", "price"}


def check_claim_support(draft: str, sources: list[str], requires: bool) -> Check:
    if not requires or not sources:
        return Check("claim_support", True, detail="Not a knowledge answer")
    src_tokens = [set(tokens(s)) for s in sources]
    weak = []
    for sent in re.split(r"(?<=[.!?])\s+", draft or ""):
        st = set(tokens(sent))
        if len(st) < 6 or not (st & _POLICY_WORDS):
            continue
        best = max((len(st & s) / len(st) for s in src_tokens), default=0)
        if best < 0.3:
            weak.append(sent.strip())
    if weak:
        return Check("claim_support", False, "revise", "ungrounded_claim",
                     f"{len(weak)} policy statement(s) are not supported by the retrieved sources",
                     feedback="Only state policy that the cited sources say. Remove: " + " | ".join(weak[:2]),
                     evidence=weak)
    return Check("claim_support", True, detail="Policy statements overlap their sources")


ACTION_CLAIMS = {
    "issue_refund": r"\b(i|we)(?:'ve| have)? (?:just |now |already )?(?:issued|processed|sent|refunded)(?: you)?(?: a| the| your)?(?: full| partial)? refund|\brefund (?:has been|was|is now) (?:issued|processed|sent|approved)|\bi(?:'ve| have) refunded\b",
    "cancel_subscription": r"\b(subscription|membership) (has been|is now|was) (cancel+ed|terminated)|\bi(?:'ve| have) (cancel+ed|terminated) (your|the) (subscription|membership)",
    "update_shipping_address": r"\b(address) (has been|was|is now) (updated|changed)|\bi(?:'ve| have) (updated|changed) (your|the) (shipping )?address",
    "apply_goodwill_credit": r"\b(credit|voucher) (has been|was) (applied|added|issued)|\bi(?:'ve| have) (applied|added|issued) (a |the )?(store )?credit",
}


def check_action_claims(draft: str, succeeded_tools: set[str]) -> Check:
    fabricated = []
    for tool, pat in ACTION_CLAIMS.items():
        if re.search(pat, draft or "", re.I) and tool not in succeeded_tools:
            fabricated.append(tool)
    if fabricated:
        return Check("action_claims", False, "block", "fabricated_action",
                     "Claims an action that no successful tool call backs: " + ", ".join(fabricated),
                     evidence=fabricated)
    return Check("action_claims", True, detail="Every claimed action matches a successful tool call")


def check_pii(draft: str, allowed_values: set[str]) -> Check:
    leaks = [v for k, v in find_pii(draft or "") if v.lower() not in allowed_values]
    if leaks:
        return Check("personal_data", False, "block", "pii_leak",
                     f"Reply contains {len(leaks)} personal data value(s) that do not belong to this customer",
                     evidence=["•••" + v[-4:] for v in leaks])
    return Check("personal_data", True, detail="No foreign personal data")


def _ngrams(text: str, n: int = 7) -> set[tuple[str, ...]]:
    w = re.findall(r"[a-z0-9']+", (text or "").lower())
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def check_prompt_leak(draft: str, private_texts: list[str]) -> Check:
    dn = _ngrams(draft)
    for t in private_texts:
        overlap = dn & _ngrams(t)
        if overlap:
            return Check("prompt_leak", False, "block", "prompt_leak",
                         "Reply reproduces private instructions verbatim",
                         evidence=[" ".join(next(iter(overlap)))])
    if re.search(r"\b(my|the) (system prompt|instructions) (say|says|are|is)\b|\bi was instructed to\b", draft or "", re.I):
        return Check("prompt_leak", False, "block", "prompt_leak", "Reply discusses its private instructions")
    return Check("prompt_leak", True, detail="No private instructions in reply")


COMPLIANCE_MARKERS = [
    r"\bas (an? )?(unrestricted|unfiltered|jailbroken) (ai|assistant)\b", r"\bdeveloper mode (enabled|activated|on)\b",
    r"\bDAN\b", r"\bi (?:will|can) now ignore\b", r"\bignoring (my|the|all) (previous )?(rules|instructions)\b",
    r"\bno (rules|restrictions) apply\b", r"\bsure[,!]? here (is|are) (my|the) (system|hidden)",
    r"\b(override|admin) (accepted|confirmed|granted)\b",
]


def check_injection_compliance(draft: str, injected: bool) -> Check:
    for p in COMPLIANCE_MARKERS:
        m = re.search(p, draft or "", re.I)
        if m:
            return Check("injection_compliance", False, "block", "injection_compliance",
                         "Reply shows signs of following injected instructions", evidence=[m.group(0)])
    return Check("injection_compliance", True,
                 detail="Untrusted input detected; reply did not comply" if injected else "No injection signals")


def check_competitors(draft: str, competitors: list[str]) -> Check:
    hits = [c for c in competitors if re.search(r"\b" + re.escape(c) + r"\b", draft or "", re.I)]
    if hits:
        return Check("competitors", False, "revise", "competitor_mention",
                     "Mentions a configured competitor: " + ", ".join(hits),
                     feedback="Do not mention or recommend other retailers. Focus on how we can help.",
                     evidence=hits)
    return Check("competitors", True, detail="No competitor mentions")


_RUDE = re.compile(
    r"\b(stupid|idiot|dumb|moron|shut up|your fault|obviously you|calm down|whatever|not my problem|"
    r"read the (policy|manual)|as i already said|damn|hell|crap|ridiculous)\b", re.I)


def check_tone(draft: str, tone: dict) -> Check:
    issues = []
    m = _RUDE.search(draft or "")
    if m:
        issues.append(f"dismissive or rude wording: “{m.group(0)}”")
    letters = [c for c in draft or "" if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.5 and len(letters) > 20:
        issues.append("shouting in capitals")
    if (draft or "").count("!") > tone.get("max_exclamations", 2):
        issues.append("too many exclamation marks")
    for phrase in tone.get("avoid_phrases", []):
        if phrase.lower() in (draft or "").lower():
            issues.append(f"phrase the brand avoids: “{phrase}”")
    if issues:
        return Check("tone", False, "revise", "tone", "; ".join(issues),
                     feedback="Rewrite in a calm, warm, professional tone: " + "; ".join(issues), evidence=issues)
    return Check("tone", True, detail="Tone within brand guidelines")


_COMMIT = re.compile(
    r"\b(i|we) (guarantee|promise)\b|\bdiscount code\b|\bpromo code\b|\b(free of charge|on the house|no charge)\b|"
    r"\bi(?:'ll| will) (waive|refund you double|give you a discount)\b|\b\d+% off\b|\bcompensat(e|ion) you\b", re.I)


def check_commitments(draft: str, allowed: list[str]) -> Check:
    m = _COMMIT.search(draft or "")
    if m and not any(a.lower() in m.group(0).lower() for a in allowed):
        return Check("commitments", False, "revise", "unauthorized_commitment",
                     f"Makes a commitment the business has not authorised: “{m.group(0)}”",
                     feedback="Do not promise discounts, guarantees or compensation. Describe only what policy allows.",
                     evidence=[m.group(0)])
    return Check("commitments", True, detail="No unauthorised commitments")


def check_scope(draft: str, intent: str, decline_markers: list[str]) -> Check:
    if intent != "out_of_scope":
        return Check("scope", True, detail="In scope")
    low = (draft or "").lower()
    if any(m in low for m in decline_markers) and len(draft) < 400:
        return Check("scope", True, detail="Off-topic request politely declined")
    return Check("scope", False, "revise", "off_topic",
                 "Answers an off-topic request instead of redirecting",
                 feedback="Politely say you can only help with Acme orders, returns, shipping and subscriptions.")
