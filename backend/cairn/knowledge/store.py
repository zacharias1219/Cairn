"""Knowledge sources, chunking and hybrid retrieval (F6)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from psycopg import AsyncConnection

from cairn.db.core import fetch_all, fetch_one, vec
from cairn.knowledge.embed import embed, tokens

MAX_CHUNK_CHARS = 700


def chunk(content: str) -> list[tuple[str | None, str]]:
    """Split on markdown headings, then pack paragraphs up to a size."""
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in content.splitlines():
        m = re.match(r"^#{1,4}\s+(.*)", line)
        if m:
            sections.append((m.group(1).strip(), []))
        else:
            sections[-1][1].append(line)
    out: list[tuple[str | None, str]] = []
    for heading, lines in sections:
        paras = [p.strip() for p in "\n".join(lines).split("\n\n") if p.strip()]
        buf = ""
        for p in paras:
            if buf and len(buf) + len(p) > MAX_CHUNK_CHARS:
                out.append((heading, buf))
                buf = p
            else:
                buf = f"{buf}\n\n{p}" if buf else p
        if buf:
            out.append((heading, buf))
    return out


async def upsert_source(
    conn: AsyncConnection, tenant_id: uuid.UUID, *, title: str, content: str, owner: str,
    kind: str = "policy", url: str | None = None, source_id: uuid.UUID | None = None,
    review_interval_days: int = 90, reviewed_at=None,
) -> dict:
    if source_id:
        row = await fetch_one(conn, """
            update knowledge_sources set title=%s, content=%s, owner=%s, kind=%s, url=%s,
              review_interval_days=%s, updated_at=now(), reviewed_at=coalesce(%s, now())
            where id=%s returning *""",
            (title, content, owner, kind, url, review_interval_days, reviewed_at, source_id))
        await conn.execute("delete from knowledge_chunks where source_id=%s", (source_id,))
    else:
        row = await fetch_one(conn, """
            insert into knowledge_sources (tenant_id, title, content, owner, kind, url,
              review_interval_days, reviewed_at)
            values (%s,%s,%s,%s,%s,%s,%s,coalesce(%s, now())) returning *""",
            (tenant_id, title, content, owner, kind, url, review_interval_days, reviewed_at))
    assert row is not None
    for i, (heading, text) in enumerate(chunk(content)):
        await conn.execute(
            "insert into knowledge_chunks (tenant_id, source_id, ord, heading, content, embedding) "
            "values (%s,%s,%s,%s,%s,%s::vector)",
            (tenant_id, row["id"], i, heading, text, vec(embed(f"{title} {heading or ''} {text}"))),
        )
    return row


@dataclass
class Hit:
    chunk_id: str
    source_id: str
    title: str
    heading: str | None
    content: str
    score: float
    stale: bool
    coverage: float = 0.0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


async def search(conn: AsyncConnection, query: str, k: int = 4) -> list[Hit]:
    """Keyword and vector search, fused by reciprocal rank, then reranked.

    The reranker is deterministic: fused rank plus query-term coverage of
    the chunk, which favours chunks that answer the question directly.
    """
    q = query.strip()
    if not q:
        return []
    qv = vec(embed(q))
    # OR the query terms so a chunk matching any of them is a keyword candidate.
    ts_query = " | ".join(sorted(set(tokens(q)))) or "cairnnomatch"
    rows = await fetch_all(conn, """
        with kw as (
          select id, row_number() over (order by ts_rank_cd(tsv, to_tsquery('english', %(tsq)s)) desc) as r
          from knowledge_chunks
          where tsv @@ to_tsquery('english', %(tsq)s)
          limit 20
        ),
        vs as (
          select id, row_number() over (order by embedding <=> %(qv)s::vector) as r
          from knowledge_chunks
          order by embedding <=> %(qv)s::vector
          limit 20
        ),
        fused as (
          select coalesce(kw.id, vs.id) as id,
                 coalesce(1.0/(60+kw.r), 0) + coalesce(1.0/(60+vs.r), 0) as rrf
          from kw full outer join vs on kw.id = vs.id
        )
        select c.id, c.source_id, s.title, c.heading, c.content, f.rrf,
               1 - (c.embedding <=> %(qv)s::vector) as cosine,
               (s.reviewed_at + make_interval(days => s.review_interval_days)) < now() as stale
        from fused f
        join knowledge_chunks c on c.id = f.id
        join knowledge_sources s on s.id = c.source_id
        order by f.rrf desc
        limit 12
    """, {"tsq": ts_query, "qv": qv})
    qt = set(tokens(q))
    hits = []
    for r in rows:
        body = set(tokens(r["content"]))
        head = set(tokens(r["heading"] or ""))
        title = set(tokens(r["title"]))
        coverage = len(qt & (body | head)) / max(1, len(qt))
        if coverage < 0.2 and float(r["cosine"]) < 0.35:
            continue  # neither the words nor the meaning match: not a source for this question
        score = (2.0 * coverage + 0.6 * len(qt & head) / max(1, len(qt)) + 0.2 * len(qt & title) / max(1, len(qt))
                 + 20 * float(r["rrf"]) + 0.5 * float(r["cosine"]))
        hits.append(Hit(str(r["id"]), str(r["source_id"]), r["title"], r["heading"], r["content"],
                        round(score, 4), bool(r["stale"]), round(coverage, 3)))
    hits.sort(key=lambda h: -h.score)
    return [h for h in hits[:k] if h.score > 0.25]
