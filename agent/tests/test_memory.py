from datetime import datetime
import pytest
from agent.memory.working_memory import WorkingMemory, IterationRecord
from agent.memory.retrieval_trigger import RetrievalTrigger
from agent.memory.memory_relational_store import RelationalStore
from agent.rbac import AgentIdentity
from datetime import datetime as dt


def test_working_memory_eviction():
    wm = WorkingMemory(session_id="s1", window=3)
    for i in range(5):
        wm.add(IterationRecord(iteration_id=i, plan=f"p{i}", code_diff=f"d{i}", error=None if i%2==0 else "err", timestamp=datetime.utcnow()))
    recs = wm.get_recent(5)
    assert len(recs) == 3


def test_retrieval_trigger():
    t = RetrievalTrigger(error_signature="abc", similarity_score=0.8, threshold=0.75)
    assert t.should_retrieve()
    t2 = RetrievalTrigger(error_signature="abc", similarity_score=0.5, threshold=0.75)
    assert not t2.should_retrieve()


def test_relational_store_namespace_isolation(tmp_path):
    db = tmp_path / "mem.db"
    rs = RelationalStore(db_path=db)
    ident = AgentIdentity(agent_id="agent-1", role="coder_agent", session_id="s1", timestamp=dt.utcnow())
    mid = rs.store(error_signature="sig1", fix_strategy="fix", success=True, project_id="projA", agent_identity=ident)
    assert mid.get("ok")
    items = rs.query_by_signature("sig1", project_id="projA", limit=5, agent_identity=ident)
    assert items.get("ok") and len(items.get("items", [])) >= 1
    # ensure other project returns empty
    other = rs.query_by_signature("sig1", project_id="projB", limit=5, agent_identity=ident)
    assert other.get("ok") and other.get("items") == []
