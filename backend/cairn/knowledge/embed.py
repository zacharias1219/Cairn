"""Text embeddings behind one interface.

The default ``HashingEmbedder`` is local and deterministic: signed feature
hashing over word unigrams and bigrams, sublinear term frequency, and L2
normalization into 384 dimensions. It needs no network and no model
weights, which keeps the stack to one service and one database, and it is
good enough for hybrid retrieval where Postgres full-text search carries
the exact-term signal. A hosted embedding model can replace it by
implementing ``embed``; the column width is the only contract.
"""

from __future__ import annotations

import hashlib
import math
import re

DIM = 384

_STOP = set(
    "a an the and or but if of to in on for with at by from is are was were be been being it its "
    "this that these those i you he she we they me my your our their do does did have has had "
    "can could would should will just so not no yes please thanks thank hi hello hey".split()
)
_WORD = re.compile(r"[a-z0-9]+")


def _stem(w: str) -> str:
    for suf in ("ing", "edly", "ed", "ies", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def tokens(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall((text or "").lower()) if w not in _STOP]


class HashingEmbedder:
    dim = DIM

    def embed(self, text: str) -> list[float]:
        toks = tokens(text)
        feats: dict[str, float] = {}
        for t in toks:
            feats[t] = feats.get(t, 0.0) + 1.0
        for a, b in zip(toks, toks[1:]):
            k = a + " " + b
            feats[k] = feats.get(k, 0.0) + 0.6
        v = [0.0] * DIM
        for f, tf in feats.items():
            h = hashlib.blake2b(f.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % DIM
            sign = 1.0 if h[4] & 1 else -1.0
            v[idx] += sign * (1.0 + math.log(tf))
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]


_default = HashingEmbedder()


def embed(text: str) -> list[float]:
    return _default.embed(text)
