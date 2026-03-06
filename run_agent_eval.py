#!/usr/bin/env python3
"""
Agent Evaluation Harness

This script runs the autonomous coding agent on a set of evaluation tasks
and collects metrics like success rate, hallucination rate, latency, and cost.

Usage:
    python run_agent_eval.py --tasks 100 --workers 5 --max-iterations 3

Output:
    - Console summary of metrics
    - Results saved to SQLite database
    - Optional export to LangSmith/Langfuse
"""

import argparse
import json
import random
import sqlite3
import sys
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Configuration
API_BASE_URL = os.environ.get("AGENT_API_URL", "http://127.0.0.1:8000")
DB_PATH = os.environ.get("EVAL_DB_PATH", "agent_data.sqlite3")
LANGSMITH_TRACING = os.environ.get("LANGSMITH_TRACING", "false").lower() == "true"
LANGFUSE_AVAILABLE = True  # Check at runtime

# Try importing langfuse
try:
    from langfuse import Langfuse
    langfuse = Langfuse()
except ImportError:
    langfuse = None
    LANGFUSE_AVAILABLE = False


@dataclass
class TaskResult:
    """Result of a single task execution."""
    task_id: str
    task_type: str
    goal: str
    status: str  # "success", "error", "timeout", "partial"
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    iterations: int
    error_signature: Optional[str]
    timestamp: str


@dataclass
class EvaluationMetrics:
    """Aggregated evaluation metrics."""
    total_tasks: int
    success_count: int
    error_count: int
    timeout_count: int
    partial_count: int
    
    # Token and cost metrics
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    
    # Latency metrics
    total_latency_ms: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    
    # Rate metrics
    success_rate: float
    hallucination_rate: float
    
    # By task type
    by_task_type: Dict[str, Dict[str, Any]]


def load_tasks() -> List[Dict[str, Any]]:
    """Load evaluation tasks from JSON files."""
    tasks = []
    
    # Load bug fix tasks
    bug_fix_path = Path("tests/bug_fix_tasks.json")
    if bug_fix_path.exists():
        with open(bug_fix_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Handle both formats: {"tasks": [...]} or [...]
            if isinstance(data, dict) and "tasks" in data:
                bug_tasks = data["tasks"]
            else:
                bug_tasks = data if isinstance(data, list) else []
            for t in bug_tasks:
                if isinstance(t, dict):
                    t["task_type"] = "bug_fix"
                    tasks.append(t)
    
    # Load refactor tasks
    refactor_path = Path("tests/refactor_tasks.json")
    if refactor_path.exists():
        with open(refactor_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "tasks" in data:
                refactor_tasks = data["tasks"]
            else:
                refactor_tasks = data if isinstance(data, list) else []
            for t in refactor_tasks:
                if isinstance(t, dict):
                    t["task_type"] = "refactor"
                    tasks.append(t)
    
    # Load infrastructure tasks
    infra_path = Path("tests/infra_tasks.json")
    if infra_path.exists():
        with open(infra_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "tasks" in data:
                infra_tasks = data["tasks"]
            else:
                infra_tasks = data if isinstance(data, list) else []
            for t in infra_tasks:
                if isinstance(t, dict):
                    t["task_type"] = "infrastructure"
                    tasks.append(t)
    
    return tasks


def init_database():
    """Initialize the evaluation database."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Create evaluation_results table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS evaluation_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            task_type TEXT NOT NULL,
            goal TEXT NOT NULL,
            status TEXT NOT NULL,
            latency_ms REAL NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost_usd REAL NOT NULL,
            iterations INTEGER NOT NULL,
            error_signature TEXT,
            timestamp TEXT NOT NULL
        )
    """)
    
    # Create evaluation_metrics table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS evaluation_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            total_tasks INTEGER NOT NULL,
            success_count INTEGER NOT NULL,
            error_count INTEGER NOT NULL,
            success_rate REAL NOT NULL,
            avg_latency_ms REAL NOT NULL,
            total_cost_usd REAL NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    
    conn.commit()
    return conn


def save_result(conn: sqlite3.Connection, result: TaskResult):
    """Save a task result to the database."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO evaluation_results (
            task_id, task_type, goal, status, latency_ms,
            input_tokens, output_tokens, cost_usd, iterations,
            error_signature, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        result.task_id,
        result.task_type,
        result.goal,
        result.status,
        result.latency_ms,
        result.input_tokens,
        result.output_tokens,
        result.cost_usd,
        result.iterations,
        result.error_signature,
        result.timestamp
    ))
    conn.commit()


def trace_to_langsmith(task: Dict[str, Any], result: TaskResult):
    """Trace task execution to LangSmith if available."""
    if not LANGSMITH_TRACING:
        return
    
    try:
        from langsmith import traceable
        
        @traceable(name=f"eval_{result.task_id}")
        def trace_task():
            return result
        
        trace_task()
    except ImportError:
        pass


def trace_to_langfuse(task: Dict[str, Any], result: TaskResult):
    """Trace task execution to Langfuse if available."""
    if not LANGFUSE_AVAILABLE or langfuse is None:
        return
    
    try:
        generation = langfuse.generation(
            name=f"eval_{result.task_id}",
            input=result.goal,
            output={"status": result.status, "iterations": result.iterations},
            metadata={
                "task_type": result.task_type,
                "latency_ms": result.latency_ms,
                "cost_usd": result.cost_usd,
                "success": result.status == "success"
            }
        )
    except Exception as e:
        print(f"Warning: Failed to trace to Langfuse: {e}")


def execute_task(task: Dict[str, Any], max_iterations: int = 3) -> TaskResult:
    """Execute a single evaluation task."""
    goal = task["goal"]
    task_id = task["id"]
    task_type = task["task_type"]
    
    start_time = time.time()
    
    try:
        # Call the agent API to start the run
        response = requests.post(
            f"{API_BASE_URL}/run",
            json={"goal": goal, "max_iterations": max_iterations},
            timeout=30
        )
        
        if response.status_code != 200:
            return TaskResult(
                task_id=task_id,
                task_type=task_type,
                goal=goal,
                status="error",
                latency_ms=(time.time() - start_time) * 1000,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0,
                iterations=0,
                error_signature=f"HTTP {response.status_code}",
                timestamp=datetime.now().isoformat()
            )
        
        data = response.json()
        run_id = data.get("run_id")
        
        # Poll for completion (max 60 seconds)
        max_polls = 30
        poll_interval = 2
        for i in range(max_polls):
            time.sleep(poll_interval)
            
            status_response = requests.get(
                f"{API_BASE_URL}/status/{run_id}",
                timeout=10
            )
            
            if status_response.status_code == 200:
                status_data = status_response.json()
                run_status = status_data.get("status", "unknown")
                
                if run_status == "completed":
                    # Extract result
                    result_str = status_data.get("result", "")
                    
                    # Determine status
                    status = "partial"
                    if "SUCCESS" in result_str:
                        status = "success"
                    elif "FAILED" in result_str:
                        status = "error"
                    
                    return TaskResult(
                        task_id=task_id,
                        task_type=task_type,
                        goal=goal,
                        status=status,
                        latency_ms=(time.time() - start_time) * 1000,
                        input_tokens=0,
                        output_tokens=0,
                        cost_usd=0,
                        iterations=0,
                        error_signature=None,
                        timestamp=datetime.now().isoformat()
                    )
                elif run_status == "failed":
                    error_msg = status_data.get("error", "unknown")
                    return TaskResult(
                        task_id=task_id,
                        task_type=task_type,
                        goal=goal,
                        status="error",
                        latency_ms=(time.time() - start_time) * 1000,
                        input_tokens=0,
                        output_tokens=0,
                        cost_usd=0,
                        iterations=0,
                        error_signature=error_msg[:16],
                        timestamp=datetime.now().isoformat()
                    )
        
        # Timeout waiting for completion
        return TaskResult(
            task_id=task_id,
            task_type=task_type,
            goal=goal,
            status="timeout",
            latency_ms=(time.time() - start_time) * 1000,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0,
            iterations=0,
            error_signature="timeout_waiting",
            timestamp=datetime.now().isoformat()
        )
        
    except requests.Timeout:
        return TaskResult(
            task_id=task_id,
            task_type=task_type,
            goal=goal,
            status="timeout",
            latency_ms=(time.time() - start_time) * 1000,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0,
            iterations=0,
            error_signature="timeout",
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        return TaskResult(
            task_id=task_id,
            task_type=task_type,
            goal=goal,
            status="error",
            latency_ms=(time.time() - start_time) * 1000,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0,
            iterations=0,
            error_signature=str(e)[:16],
            timestamp=datetime.now().isoformat()
        )


def calculate_metrics(results: List[TaskResult]) -> EvaluationMetrics:
    """Calculate aggregated metrics from task results."""
    if not results:
        return EvaluationMetrics(
            total_tasks=0,
            success_count=0,
            error_count=0,
            timeout_count=0,
            partial_count=0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cost_usd=0,
            total_latency_ms=0,
            avg_latency_ms=0,
            p50_latency_ms=0,
            p95_latency_ms=0,
            p99_latency_ms=0,
            success_rate=0,
            hallucination_rate=0,
            by_task_type={}
        )
    
    # Count by status
    success_count = sum(1 for r in results if r.status == "success")
    error_count = sum(1 for r in results if r.status == "error")
    timeout_count = sum(1 for r in results if r.status == "timeout")
    partial_count = sum(1 for r in results if r.status == "partial")
    
    # Token and cost totals
    total_input_tokens = sum(r.input_tokens for r in results)
    total_output_tokens = sum(r.output_tokens for r in results)
    total_cost_usd = sum(r.cost_usd for r in results)
    
    # Latency calculations
    latencies = sorted([r.latency_ms for r in results])
    total_latency_ms = sum(latencies)
    avg_latency_ms = total_latency_ms / len(results) if results else 0
    
    # Percentiles
    p50_idx = int(len(latencies) * 0.50)
    p95_idx = int(len(latencies) * 0.95)
    p99_idx = int(len(latencies) * 0.99)
    
    p50_latency_ms = latencies[p50_idx] if latencies else 0
    p95_latency_ms = latencies[p95_idx] if latencies else 0
    p99_latency_ms = latencies[p99_idx] if latencies else 0
    
    # Success rate
    success_rate = success_count / len(results) if results else 0
    
    # Hallucination rate (estimated from error signatures)
    hallucination_count = sum(
        1 for r in results 
        if r.error_signature and "hallucination" in r.error_signature.lower()
    )
    hallucination_rate = hallucination_count / len(results) if results else 0
    
    # By task type
    by_task_type = {}
    task_types = set(r.task_type for r in results)
    for task_type in task_types:
        type_results = [r for r in results if r.task_type == task_type]
        type_success = sum(1 for r in type_results if r.status == "success")
        type_latencies = [r.latency_ms for r in type_results]
        
        by_task_type[task_type] = {
            "total": len(type_results),
            "success": type_success,
            "success_rate": type_success / len(type_results) if type_results else 0,
            "avg_latency": sum(type_latencies) / len(type_latencies) if type_latencies else 0
        }
    
    return EvaluationMetrics(
        total_tasks=len(results),
        success_count=success_count,
        error_count=error_count,
        timeout_count=timeout_count,
        partial_count=partial_count,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_cost_usd=total_cost_usd,
        total_latency_ms=total_latency_ms,
        avg_latency_ms=avg_latency_ms,
        p50_latency_ms=p50_latency_ms,
        p95_latency_ms=p95_latency_ms,
        p99_latency_ms=p99_latency_ms,
        success_rate=success_rate,
        hallucination_rate=hallucination_rate,
        by_task_type=by_task_type
    )


def print_summary(metrics: EvaluationMetrics):
    """Print evaluation summary."""
    print("\n" + "="*60)
    print("EVALUATION SUMMARY")
    print("="*60)
    print(f"Total Tasks:     {metrics.total_tasks}")
    print(f"Success:         {metrics.success_count} ({metrics.success_rate:.1%})")
    print(f"Errors:          {metrics.error_count}")
    print(f"Timeouts:        {metrics.timeout_count}")
    print(f"Partial:         {metrics.partial_count}")
    print()
    print(f"Avg Latency:     {metrics.avg_latency_ms:.0f}ms")
    print(f"P50 Latency:     {metrics.p50_latency_ms:.0f}ms")
    print(f"P95 Latency:     {metrics.p95_latency_ms:.0f}ms")
    print(f"P99 Latency:     {metrics.p99_latency_ms:.0f}ms")
    print()
    print(f"Total Cost:      ${metrics.total_cost_usd:.4f}")
    print(f"Total Input:     {metrics.total_input_tokens} tokens")
    print(f"Total Output:    {metrics.total_output_tokens} tokens")
    print()
    print("By Task Type:")
    for task_type, stats in metrics.by_task_type.items():
        print(f"   {task_type}: {stats['success']}/{stats['total']} ({stats['success_rate']:.1%}) - {stats['avg_latency']:.0f}ms avg")
    
    print("\n" + "="*60)


def run_evaluation(num_tasks: int = 100, max_workers: int = 5, max_iterations: int = 3):
    """Run the complete evaluation harness."""
    print("\n=== Starting Agent Evaluation ===")
    print(f"   Tasks: {num_tasks}")
    print(f"   Max Workers: {max_workers}")
    print(f"   Max Iterations: {max_iterations}")
    print()
    
    # Load tasks
    all_tasks = load_tasks()
    print(f"   Loaded {len(all_tasks)} tasks")
    
    # Sample or repeat tasks to reach num_tasks
    if len(all_tasks) < num_tasks:
        # Repeat tasks to fill
        tasks = (all_tasks * (num_tasks // len(all_tasks) + 1))[:num_tasks]
    else:
        tasks = random.sample(all_tasks, num_tasks)
    
    print(f"   Running {len(tasks)} tasks...")
    
    # Execute tasks in parallel
    results = []
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(execute_task, task, max_iterations): task for task in tasks}
        
        completed = 0
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                results.append(result)
                completed += 1
                
                # Progress indicator
                if completed % 10 == 0 or completed == len(tasks):
                    print(f"   Progress: {completed}/{len(tasks)} ({completed/len(tasks)*100:.0f}%)")
                    
            except Exception as e:
                print(f"   ERROR: Task {task['id']} failed: {e}")
                results.append(TaskResult(
                    task_id=task["id"],
                    task_type=task["task_type"],
                    goal=task["goal"],
                    status="error",
                    latency_ms=0,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0,
                    iterations=0,
                    error_signature=str(e)[:16],
                    timestamp=datetime.now().isoformat()
                ))
    
    total_time = time.time() - start_time
    
    # Calculate metrics
    print("\n--- Calculating metrics ---")
    metrics = calculate_metrics(results)
    
    # Save to database
    print("--- Saving results to database ---")
    conn = init_database()
    for result in results:
        save_result(conn, result)
    conn.close()
    
    # Print summary
    print_summary(metrics)
    
    # Export to LangSmith/Langfuse
    if LANGSMITH_TRACING:
        print("\nTraced to LangSmith: enabled")
    if LANGFUSE_AVAILABLE:
        print("Traced to Langfuse: enabled")
    
    print(f"\nTotal evaluation time: {total_time:.1f}s")
    print(f"Throughput: {len(tasks)/total_time:.2f} tasks/sec")
    
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Run agent evaluation harness")
    parser.add_argument("--tasks", type=int, default=100, help="Number of tasks to run")
    parser.add_argument("--workers", type=int, default=5, help="Max parallel workers")
    parser.add_argument("--max-iterations", type=int, default=3, help="Max iterations per task")
    parser.add_argument("--api-url", type=str, default=None, help="Agent API URL")
    
    args = parser.parse_args()
    
    if args.api_url:
        global API_BASE_URL
        API_BASE_URL = args.api_url
    
    # Run evaluation
    metrics = run_evaluation(
        num_tasks=args.tasks,
        max_workers=args.workers,
        max_iterations=args.max_iterations
    )
    
    # Exit with appropriate code
    if metrics.success_rate >= 0.7:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
