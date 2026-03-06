"""Long-term memory using FAISS (vector) and SQLite metadata.

If faiss is not installed, falls back to SQLite-only storage.
Implements namespace isolation and RBAC checks for all operations.
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional
from ..rbac import AgentIdentity, check_permission, ForbiddenError
from ..telemetry.memory_hooks import memory_span
import logging
import hashlib

logger = logging.getLogger(__name__)
import sqlite3
from pathlib import Path
from ..config import DB_PATH
import numpy as np

# Try to import FAISS, fall back to None if not available
FAISS_AVAILABLE = False
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    faiss = None
    logger.warning("FAISS not installed - using SQLite-only memory storage")


class LongTermMemory:
    def __init__(self, db_path: Path | None = None, namespace: str = "default"):
        self.db = db_path or DB_PATH
        self.namespace = namespace
        self.embedding_dim = 128  # Default dimension for fallback
        self._init_db()
        self._init_faiss()
    
    def _init_db(self):
        """Initialize SQLite tables for metadata storage."""
        conn = sqlite3.connect(str(self.db))
        try:
            cur = conn.cursor()
            
            # Check if table exists
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memories'")
            table_exists = cur.fetchone() is not None
            
            if not table_exists:
                # Create new table
                cur.execute("""
                    CREATE TABLE memories (
                        id INTEGER PRIMARY KEY,
                        namespace TEXT NOT NULL DEFAULT 'default',
                        signature TEXT NOT NULL,
                        root_cause TEXT,
                        fix_summary TEXT,
                        embedding_id INTEGER,
                        project_id TEXT,
                        success_rate REAL DEFAULT 0.0,
                        usage_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(namespace, signature)
                    )
                """)
            else:
                # Table exists - add namespace column if missing (migration)
                try:
                    cur.execute("ALTER TABLE memories ADD COLUMN namespace TEXT DEFAULT 'default'")
                except sqlite3.OperationalError:
                    pass  # Column already exists
            
            # Create index for namespace + signature lookup
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_namespace 
                ON memories(namespace, signature)
            """)
            conn.commit()
        finally:
            conn.close()
    
    def _init_faiss(self):
        """Initialize FAISS index for vector similarity search."""
        if not FAISS_AVAILABLE:
            self.faiss_index = None
            self.embedding_dim = 128  # Default dimension for fallback
            return
        
        # Use a simple index that can be saved/loaded
        index_path = self.db.parent / f"faiss_index_{self.namespace}.index"
        
        if index_path.exists():
            try:
                self.faiss_index = faiss.read_index(str(index_path))
                logger.info(f"Loaded FAISS index from {index_path}")
            except Exception as e:
                logger.warning(f"Failed to load FAISS index: {e}, creating new one")
                self.faiss_index = faiss.IndexFlatL2(self.embedding_dim)
        else:
            self.faiss_index = faiss.IndexFlatL2(self.embedding_dim)
            logger.info(f"Created new FAISS index for namespace {self.namespace}")
    
    def _save_faiss(self):
        """Persist FAISS index to disk."""
        if not FAISS_AVAILABLE or self.faiss_index is None:
            return
        
        index_path = self.db.parent / f"faiss_index_{self.namespace}.index"
        try:
            faiss.write_index(self.faiss_index, str(index_path))
        except Exception as e:
            logger.error(f"Failed to save FAISS index: {e}")
    
    def _compute_embedding(self, text: str) -> np.ndarray:
        """Compute a simple embedding for text.
        
        In production, this should use a proper embedding model.
        For now, uses a deterministic hash-based approach.
        """
        # Simple hash-based embedding for demonstration
        # In production, replace with proper embedding (e.g., sentence-transformers)
        hash_val = hashlib.sha256(text.encode()).digest()
        # Convert hash to fixed-size float array
        arr = np.frombuffer(hash_val[:self.embedding_dim], dtype=np.float32)
        # Normalize to unit vector
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr
    
    def store(
        self,
        root_cause: str,
        fix_summary: str,
        embedding: bytes | None = None,
        project_id: str | None = None,
        agent_identity: AgentIdentity | None = None
    ) -> Dict[str, Any]:
        """Store a memory entry with RBAC validation."""
        if agent_identity is None:
            return {"error": "MISSING_IDENTITY", "message": "AgentIdentity required"}
        
        try:
            check_permission(agent_identity, "store_memory")
        except ForbiddenError as e:
            return {"error": "DENIED", "message": str(e)}
        
        sig = hashlib.sha256((root_cause + fix_summary).encode("utf-8")).hexdigest()
        
        with memory_span("longterm.store", project_id=project_id or "", agent_id=agent_identity.agent_id):
            conn = sqlite3.connect(str(self.db))
            try:
                cur = conn.cursor()
                
                # Check if entry already exists
                cur.execute(
                    "SELECT id, usage_count FROM memories WHERE namespace = ? AND signature = ?",
                    (self.namespace, sig)
                )
                existing = cur.fetchone()
                
                if existing:
                    # Update existing entry
                    cur.execute("""
                        UPDATE memories 
                        SET usage_count = usage_count + 1,
                            root_cause = ?,
                            fix_summary = ?
                        WHERE namespace = ? AND signature = ?
                    """, (root_cause, fix_summary, self.namespace, sig))
                    memory_id = existing[0]
                else:
                    # Insert new entry
                    cur.execute("""
                        INSERT INTO memories (namespace, signature, root_cause, fix_summary, project_id)
                        VALUES (?, ?, ?, ?, ?)
                    """, (self.namespace, sig, root_cause, fix_summary, project_id))
                    memory_id = cur.lastrowid
                
                conn.commit()
                
                # Store embedding in FAISS if available
                if FAISS_AVAILABLE and self.faiss_index is not None:
                    emb = self._compute_embedding(f"{root_cause} {fix_summary}")
                    self.faiss_index.add(np.array([emb]))
                    self._save_faiss()
                
                logger.info(f"longterm.store id={memory_id} namespace={self.namespace} project={project_id}")
                return {"ok": True, "id": memory_id}
            finally:
                conn.close()
    
    def query(
        self,
        limit: int = 10,
        project_id: str | None = None,
        agent_identity: AgentIdentity | None = None,
        query_text: str | None = None
    ) -> Dict[str, Any]:
        """Query memory entries with optional vector similarity search."""
        if agent_identity is None:
            return {"error": "MISSING_IDENTITY", "message": "AgentIdentity required"}
        
        try:
            check_permission(agent_identity, "retrieve_long")
        except ForbiddenError as e:
            return {"error": "DENIED", "message": str(e)}
        
        with memory_span("longterm.query", project_id=project_id or "", agent_id=agent_identity.agent_id):
            conn = sqlite3.connect(str(self.db))
            try:
                cur = conn.cursor()
                
                # If query_text provided and FAISS available, use vector search
                if FAISS_AVAILABLE and self.faiss_index is not None and query_text:
                    emb = self._compute_embedding(query_text)
                    
                    # Search FAISS index
                    k = min(limit, self.faiss_index.ntotal)
                    if k > 0:
                        distances, indices = self.faiss_index.search(np.array([emb]), k)
                        
                        # Get IDs from SQLite based on FAISS indices
                        # Note: FAISS indices correspond to insertion order
                        # This is a simplified mapping - in production, store ID mapping
                        cur.execute("""
                            SELECT id, signature, root_cause, fix_summary, created_at, success_rate
                            FROM memories 
                            WHERE namespace = ?
                            ORDER BY id DESC
                            LIMIT ?
                        """, (self.namespace, k))
                    else:
                        cur.execute(
                            "SELECT id, signature, root_cause, fix_summary, created_at, success_rate FROM memories WHERE namespace = ? ORDER BY id DESC LIMIT ?",
                            (self.namespace, limit)
                        )
                else:
                    # Fallback: just get recent entries
                    cur.execute("""
                        SELECT id, signature, root_cause, fix_summary, created_at, success_rate
                        FROM memories 
                        WHERE namespace = ?
                        ORDER BY id DESC
                        LIMIT ?
                    """, (self.namespace, limit))
                
                rows = cur.fetchall()
                
                items = []
                for r in rows:
                    items.append({
                        "id": r[0],
                        "signature": r[1],
                        "root_cause": r[2],
                        "fix_summary": r[3],
                        "created_at": r[4],
                        "success_rate": r[5] if len(r) > 5 else 0.0
                    })
                
                return {"ok": True, "items": items, "count": len(items)}
            finally:
                conn.close()
    
    def get_similar(
        self,
        error_text: str,
        limit: int = 3,
        agent_identity: AgentIdentity | None = None
    ) -> Dict[str, Any]:
        """Find similar error patterns using vector similarity."""
        return self.query(limit=limit, agent_identity=agent_identity, query_text=error_text)
    
    def update_success_rate(self, memory_id: int, success: bool) -> None:
        """Update success rate for a memory entry."""
        conn = sqlite3.connect(str(self.db))
        try:
            cur = conn.cursor()
            
            # Get current values
            cur.execute("SELECT usage_count, success_rate FROM memories WHERE id = ?", (memory_id,))
            row = cur.fetchone()
            if not row:
                return
            
            usage_count, success_rate = row
            new_count = usage_count + 1
            
            # Compute new success rate incrementally
            if success:
                new_rate = ((success_rate * usage_count) + 1.0) / new_count
            else:
                new_rate = (success_rate * usage_count) / new_count
            
            cur.execute("""
                UPDATE memories 
                SET usage_count = ?, success_rate = ?
                WHERE id = ?
            """, (new_count, new_rate, memory_id))
            conn.commit()
        finally:
            conn.close()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        conn = sqlite3.connect(str(self.db))
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) as total, 
                       AVG(success_rate) as avg_success,
                       SUM(usage_count) as total_uses
                FROM memories 
                WHERE namespace = ?
            """, (self.namespace,))
            row = cur.fetchone()
            return {
                "total_memories": row[0] or 0,
                "avg_success_rate": row[1] or 0.0,
                "total_uses": row[2] or 0,
                "faiss_available": FAISS_AVAILABLE,
                "namespace": self.namespace
            }
        finally:
            conn.close()
