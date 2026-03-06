from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import threading
import time
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

app = FastAPI(title="Coding Agent API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RunRequest(BaseModel):
    goal: str
    max_iterations: Optional[int] = 3


runs: dict = {}


def _run_workflow_thread(goal: str, max_iterations: int, run_id: str) -> None:
    try:
        # Importing here to avoid import-time side-effects when module is imported
        from agent.main import run_workflow
        
        # Track start time
        start_time = time.time()
        
        result = run_workflow(goal, max_iterations)
        
        # Track metrics
        try:
            from agent.observability.metrics import record_agent_run, track_llm_usage
            
            # Record agent run
            record_agent_run(
                run_id=run_id,
                task=goal,
                iterations=getattr(result, 'iteration', 1),
                patch_applied=True,
                patch_success=getattr(result, 'status', '') == 'SUCCESS',
                deployment_success=getattr(result, 'status', '') == 'SUCCESS',
                total_cost_usd=0.0,  # Will be updated from LLM tracking
                total_latency_ms=(time.time() - start_time) * 1000,
                error_message=None if getattr(result, 'status', '') == 'SUCCESS' else 'Workflow completed with issues'
            )
        except Exception as e:
            logger.warning(f"Failed to record metrics: {e}")
        
        runs[run_id] = {"status": "completed", "result": repr(result)}
    except Exception as e:
        logger.exception("Run failed")
        
        # Track error
        try:
            from agent.observability.metrics import record_error
            record_error("agent_failure", "run_workflow")
        except:
            pass
        
        runs[run_id] = {"status": "failed", "error": str(e)}


@app.post("/run")
def run_agent(req: RunRequest, background_tasks: BackgroundTasks):
    run_id = f"run_{int(time.time() * 1000)}"
    runs[run_id] = {"status": "running"}
    thread = threading.Thread(target=_run_workflow_thread, args=(req.goal, req.max_iterations, run_id), daemon=True)
    thread.start()
    
    # Track request
    try:
        from agent.observability.metrics import track_request_latency
        track_request_latency("/run", 0)  # Will be updated
    except:
        pass
    
    return {"run_id": run_id, "status": "started"}


@app.get("/status/{run_id}")
def status(run_id: str):
    return runs.get(run_id, {"status": "unknown"})


@app.get("/files")
def list_files():
    """List generated files in the agent workspace"""
    workspace_path = Path("agent_workspace")
    if not workspace_path.exists():
        return {"files": []}
    
    files = []
    for f in workspace_path.glob("*.py"):
        files.append(str(f.name))
    
    return {"files": files}


@app.get("/metrics")
def get_metrics():
    """Get comprehensive metrics summary"""
    try:
        from agent.observability.metrics import get_metrics_summary
        return get_metrics_summary()
    except Exception as e:
        return {"error": str(e)}


@app.get("/metrics/prometheus")
def prometheus_metrics():
    """Export metrics in Prometheus format"""
    try:
        from agent.observability.metrics import export_prometheus_metrics
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=export_prometheus_metrics())
    except Exception as e:
        return PlainTextResponse(content=f"# Error: {e}", status_code=500)


@app.get("/health")
def health():
    return {"status": "ok"}
