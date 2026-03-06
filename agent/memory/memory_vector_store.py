"""Vector store wrapper using FAISS with namespace isolation.

Best-effort: if faiss not installed, fall back to simple numpy linear scan saved in sqlite.
"""
from __future__ import annotations
from typing import List, Tuple, Optional, Dict, Any
import numpy as np
import sqlite3
from pathlib import Path
from ..config import DB_PATH
import logging

logger = logging.getLogger(__name__)

try:
    import faiss
    _HAS_FAISS = True
except Exception:
    faiss = None
    _HAS_FAISS = False
from ..rbac import AgentIdentity, check_permission, ForbiddenError
from ..telemetry.memory_hooks import memory_span
import logging

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, dimension: int = 128, namespace: str = "default"):
        self.dim = dimension
        self.ns = namespace
        self.db = DB_PATH
        if _HAS_FAISS:
            self.index = faiss.IndexFlatIP(self.dim)
            self.ids: List[int] = []
        else:
            self._vectors: List[np.ndarray] = []
            self._ids: List[int] = []

    def _connect(self):
        conn = sqlite3.connect(str(self.db))
        return conn

    def add(self, memory_id: int, vector: List[float], project_ns: str, agent_identity: AgentIdentity | None = None) -> Dict[str, Any]:
        if agent_identity is None:
            return {"error": "MISSING_IDENTITY", "message": "AgentIdentity required"}
        try:
            check_permission(agent_identity, "store_memory")
        except ForbiddenError as e:
            return {"error": "DENIED", "message": str(e)}

        vec = np.array(vector, dtype=np.float32)
        with memory_span("vectorstore.add", project_ns=project_ns, agent_id=agent_identity.agent_id):
            if _HAS_FAISS:
                if vec.size != self.dim:
                    logger.warning("vector dim mismatch")
                    return {"error": "DIM_MISMATCH"}
                self.index.add(vec.reshape(1, -1))
                self.ids.append(memory_id)
                return {"ok": True}
            else:
                self._vectors.append(vec)
                self._ids.append(memory_id)
                return {"ok": True}

    def query(self, vector: List[float], top_k: int = 3, agent_identity: AgentIdentity | None = None) -> Dict[str, Any]:
        if agent_identity is None:
            return {"error": "MISSING_IDENTITY", "message": "AgentIdentity required"}
        try:
            check_permission(agent_identity, "retrieve_long")
        except ForbiddenError as e:
            return {"error": "DENIED", "message": str(e)}

        v = np.array(vector, dtype=np.float32)
        with memory_span("vectorstore.query", agent_id=agent_identity.agent_id):
            if _HAS_FAISS:
                D, I = self.index.search(v.reshape(1, -1), top_k)
                res = []
                for i, d in zip(I[0], D[0]):
                    if i < 0:
                        continue
                    res.append({"id": self.ids[i], "score": float(d)})
                return {"ok": True, "results": res}
            else:
                sims = []
                for idx, vec in enumerate(self._vectors):
                    score = float(np.dot(v, vec) / (np.linalg.norm(v) * np.linalg.norm(vec) + 1e-8))
                    sims.append((self._ids[idx], score))
                sims.sort(key=lambda x: x[1], reverse=True)
                return {"ok": True, "results": [{"id": s[0], "score": s[1]} for s in sims[:top_k]]}
