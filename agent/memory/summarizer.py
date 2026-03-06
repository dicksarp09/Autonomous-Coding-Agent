"""Summarization pipeline for retrieved failures using Groq client.

Performs compression and writes a RetrievalAudit to SQLite.
"""
from __future__ import annotations
from pydantic import BaseModel
from typing import List, Dict, Any
from ..groq_client import GroqClient
from ..config import DB_PATH
import sqlite3
from datetime import datetime
import time
import logging

logger = logging.getLogger(__name__)


class RetrievalAudit(BaseModel):
    retrieved_ids: List[str]
    similarity_scores: List[float]
    reason: str
    compression_ratio: float
    timestamp: datetime


def summarize_failures(items: List[Dict[str, Any]], reason: str = "automatic") -> Dict[str, Any]:
    # create a naive concatenated summary and call Groq summarizer (best-effort)
    if not items:
        return {"summary": "", "audit": None}

    input_text = "\n".join([f"id={i.get('id')} sig={i.get('signature')} fix={i.get('fix_strategy', '')}" for i in items])
    client = GroqClient()
    start = time.time()
    try:
        resp = client.generate("coding", input_text, max_tokens=256)
        latency = time.time() - start
        summary = resp.get("output") or str(resp)
    except Exception as e:
        logger.warning("Summarizer failed: %s", e)
        summary = ""
        latency = time.time() - start

    # compute compression ratio: input chars / summary chars
    in_sz = len(input_text)
    out_sz = len(summary)
    compression = (in_sz / out_sz) if out_sz > 0 else float("inf")

    audit = RetrievalAudit(
        retrieved_ids=[str(i.get("id")) for i in items],
        similarity_scores=[float(i.get("score", 1.0)) for i in items],
        reason=reason,
        compression_ratio=compression,
        timestamp=datetime.utcnow(),
    )

    # persist audit
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS retrieval_audit (id INTEGER PRIMARY KEY, retrieved_ids TEXT, similarity_scores TEXT, reason TEXT, compression_ratio REAL, timestamp TEXT)")
        cur.execute("INSERT INTO retrieval_audit (retrieved_ids, similarity_scores, reason, compression_ratio, timestamp) VALUES (?, ?, ?, ?, ?)", (','.join(audit.retrieved_ids), ','.join(map(str, audit.similarity_scores)), audit.reason, audit.compression_ratio, audit.timestamp.isoformat()))
        conn.commit()
    finally:
        conn.close()

    return {"summary": summary, "audit": audit.model_dump()}
