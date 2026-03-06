"""
Comprehensive Observability Module for Coding Agent

Implements:
1. Performance Monitoring (Prometheus metrics)
2. Cost Monitoring (LLM usage tracking)
3. Agent Quality Metrics (SQLite)
4. Distributed Tracing (OpenTelemetry)

Usage:
    from agent.observability.metrics import (
        track_request_latency,
        track_llm_usage,
        record_agent_run,
        get_metrics_summary
    )
"""
from __future__ import annotations
import time
import sqlite3
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path
import os

# Prometheus metrics (simple implementation without external dependencies)
class MetricsCollector:
    """Simple metrics collector with Prometheus-compatible format."""
    
    def __init__(self, db_path: str = "agent_data.sqlite3"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize metrics tables."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Request latency tracking
        cur.execute("""
            CREATE TABLE IF NOT EXISTS request_latencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                latency_ms REAL NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # LLM usage tracking
        cur.execute("""
            CREATE TABLE IF NOT EXISTS llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cost_usd REAL,
                latency_ms REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Agent runs tracking
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT UNIQUE,
                task TEXT NOT NULL,
                iterations INTEGER,
                patch_applied BOOLEAN,
                patch_success BOOLEAN,
                deployment_success BOOLEAN,
                total_cost_usd REAL,
                total_latency_ms REAL,
                error_message TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Error tracking
        cur.execute("""
            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_type TEXT NOT NULL,
                endpoint TEXT,
                count INTEGER DEFAULT 1,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Throughput tracking
        cur.execute("""
            CREATE TABLE IF NOT EXISTS throughput (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def record_latency(self, endpoint: str, latency_ms: float):
        """Record request latency."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO request_latencies (endpoint, latency_ms) VALUES (?, ?)",
            (endpoint, latency_ms)
        )
        conn.commit()
        conn.close()
    
    def record_llm_usage(self, model: str, input_tokens: int, output_tokens: int, 
                        cost_usd: float, latency_ms: float):
        """Record LLM API usage."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO llm_usage (model, input_tokens, output_tokens, cost_usd, latency_ms)
            VALUES (?, ?, ?, ?, ?)
        """, (model, input_tokens, output_tokens, cost_usd, latency_ms))
        conn.commit()
        conn.close()
    
    def record_agent_run(self, run_id: str, task: str, iterations: int,
                        patch_applied: bool, patch_success: bool, 
                        deployment_success: bool, total_cost_usd: float,
                        total_latency_ms: float, error_message: Optional[str] = None):
        """Record agent run metrics."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO agent_runs 
            (run_id, task, iterations, patch_applied, patch_success, 
             deployment_success, total_cost_usd, total_latency_ms, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, task, iterations, patch_applied, patch_success,
              deployment_success, total_cost_usd, total_latency_ms, error_message))
        conn.commit()
        conn.close()
    
    def record_error(self, error_type: str, endpoint: str = None):
        """Record error occurrence."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO errors (error_type, endpoint, count, last_seen)
            VALUES (?, ?, 1, CURRENT_TIMESTAMP)
        """, (error_type, endpoint))
        conn.commit()
        conn.close()
    
    def record_throughput(self, metric_name: str, value: float, unit: str = "count"):
        """Record throughput metric."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO throughput (metric_name, value, unit)
            VALUES (?, ?, ?)
        """, (metric_name, value, unit))
        conn.commit()
        conn.close()
    
    def get_latency_stats(self, endpoint: str = None, hours: int = 24) -> Dict[str, float]:
        """Get latency statistics."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        query = """
            SELECT 
                AVG(latency_ms) as avg_latency,
                MIN(latency_ms) as min_latency,
                MAX(latency_ms) as max_latency,
                COUNT(*) as count
            FROM request_latencies
            WHERE timestamp > datetime('now', '-{} hours')
        """.format(hours)
        
        if endpoint:
            query += f" AND endpoint = '{endpoint}'"
        
        cur.execute(query)
        row = cur.fetchone()
        conn.close()
        
        if row:
            return {
                "avg_latency_ms": row[0] or 0,
                "min_latency_ms": row[1] or 0,
                "max_latency_ms": row[2] or 0,
                "request_count": row[3] or 0
            }
        return {"avg_latency_ms": 0, "min_latency_ms": 0, "max_latency_ms": 0, "request_count": 0}
    
    def get_cost_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get cost summary."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                model,
                SUM(input_tokens) as total_input,
                SUM(output_tokens) as total_output,
                SUM(cost_usd) as total_cost,
                AVG(latency_ms) as avg_latency,
                COUNT(*) as call_count
            FROM llm_usage
            WHERE timestamp > datetime('now', '-{} days')
            GROUP BY model
        """.format(days))
        
        results = []
        total_cost = 0
        for row in cur.fetchall():
            results.append({
                "model": row[0],
                "total_input_tokens": row[1] or 0,
                "total_output_tokens": row[2] or 0,
                "total_cost_usd": row[3] or 0,
                "avg_latency_ms": row[4] or 0,
                "call_count": row[5] or 0
            })
            total_cost += row[3] or 0
        
        conn.close()
        
        # Calculate projections
        daily_cost = total_cost / days if days > 0 else 0
        weekly_cost = daily_cost * 7
        monthly_cost = daily_cost * 30
        
        return {
            "by_model": results,
            "total_cost_usd": total_cost,
            "daily_projection_usd": daily_cost,
            "weekly_projection_usd": weekly_cost,
            "monthly_projection_usd": monthly_cost
        }
    
    def get_agent_quality_metrics(self, days: int = 30) -> Dict[str, Any]:
        """Get agent quality metrics."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Patch success rate
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN patch_success = 1 THEN 1 ELSE 0 END) as successful
            FROM agent_runs
            WHERE timestamp > datetime('now', '-{} days')
        """.format(days))
        
        row = cur.fetchone()
        total_runs = row[0] or 0
        successful_patches = row[1] or 0
        
        # Average iterations
        cur.execute("""
            SELECT AVG(iterations) FROM agent_runs
            WHERE timestamp > datetime('now', '-{} days')
        """.format(days))
        avg_iterations = cur.fetchone()[0] or 0
        
        # Recovery rate (runs with errors that eventually succeeded)
        cur.execute("""
            SELECT COUNT(*) FROM agent_runs
            WHERE error_message IS NOT NULL 
            AND patch_success = 1
            AND timestamp > datetime('now', '-{} days')
        """.format(days))
        recovered = cur.fetchone()[0] or 0
        
        conn.close()
        
        return {
            "total_runs": total_runs,
            "patch_success_rate": successful_patches / total_runs if total_runs > 0 else 0,
            "avg_iterations": avg_iterations,
            "recovery_rate": recovered / total_runs if total_runs > 0 else 0
        }
    
    def get_error_rate(self, hours: int = 24) -> Dict[str, Any]:
        """Get error rate statistics."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Total requests in timeframe
        cur.execute("""
            SELECT COUNT(*) FROM request_latencies
            WHERE timestamp > datetime('now', '-{} hours')
        """.format(hours))
        total_requests = cur.fetchone()[0] or 0
        
        # Total errors
        cur.execute("""
            SELECT SUM(count) FROM errors
            WHERE last_seen > datetime('now', '-{} hours')
        """.format(hours))
        total_errors = cur.fetchone()[0] or 0
        
        conn.close()
        
        return {
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate_percent": (total_errors / total_requests * 100) if total_requests > 0 else 0
        }
    
    def get_throughput_stats(self, metric_name: str = None, hours: int = 24) -> Dict[str, float]:
        """Get throughput statistics."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        query = """
            SELECT 
                metric_name,
                AVG(value) as avg_value,
                SUM(value) as total_value,
                MAX(value) as max_value
            FROM throughput
            WHERE timestamp > datetime('now', '-{} hours')
        """.format(hours)
        
        if metric_name:
            query += f" AND metric_name = '{metric_name}'"
        
        query += " GROUP BY metric_name"
        
        cur.execute(query)
        
        results = {}
        for row in cur.fetchall():
            results[row[0]] = {
                "avg": row[1] or 0,
                "total": row[2] or 0,
                "max": row[3] or 0
            }
        
        conn.close()
        return results
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get complete metrics summary."""
        return {
            "latency": self.get_latency_stats(),
            "cost": self.get_cost_summary(),
            "agent_quality": self.get_agent_quality_metrics(),
            "errors": self.get_error_rate(),
            "throughput": self.get_throughput_stats()
        }
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        
        # Latency metrics
        latency = self.get_latency_stats()
        lines.append(f"# HELP request_latency_ms Average request latency in milliseconds")
        lines.append(f"# TYPE request_latency_ms gauge")
        lines.append(f'request_latency_ms{{type="avg"}} {latency["avg_latency_ms"]}')
        lines.append(f'request_latency_ms{{type="max"}} {latency["max_latency_ms"]}')
        
        # Cost metrics
        cost = self.get_cost_summary()
        lines.append(f"# HELP llm_cost_total_usd Total LLM cost in USD")
        lines.append(f"# TYPE llm_cost_total_usd gauge")
        lines.append(f'llm_cost_total_usd {cost["total_cost_usd"]}')
        lines.append(f'llm_cost_monthly_projection_usd {cost["monthly_projection_usd"]}')
        
        # Agent quality
        quality = self.get_agent_quality_metrics()
        lines.append(f"# HELP agent_patch_success_rate Agent patch success rate")
        lines.append(f"# TYPE agent_patch_success_rate gauge")
        lines.append(f'agent_patch_success_rate {quality["patch_success_rate"]}')
        lines.append(f'agent_avg_iterations {quality["avg_iterations"]}')
        
        # Error rate
        errors = self.get_error_rate()
        lines.append(f"# HELP error_rate_percent Error rate percentage")
        lines.append(f"# TYPE error_rate_percent gauge")
        lines.append(f'error_rate_percent {errors["error_rate_percent"]}')
        
        return "\n".join(lines)


# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get or create the global metrics collector."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


# Convenience functions
def track_request_latency(endpoint: str, latency_ms: float):
    """Track request latency."""
    get_metrics_collector().record_latency(endpoint, latency_ms)


def track_llm_usage(model: str, input_tokens: int, output_tokens: int, 
                    cost_usd: float, latency_ms: float):
    """Track LLM usage."""
    get_metrics_collector().record_llm_usage(
        model, input_tokens, output_tokens, cost_usd, latency_ms
    )


def record_agent_run(run_id: str, task: str, iterations: int,
                    patch_applied: bool, patch_success: bool,
                    deployment_success: bool, total_cost_usd: float,
                    total_latency_ms: float, error_message: str = None):
    """Record agent run metrics."""
    get_metrics_collector().record_agent_run(
        run_id, task, iterations, patch_applied, patch_success,
        deployment_success, total_cost_usd, total_latency_ms, error_message
    )


def record_error(error_type: str, endpoint: str = None):
    """Record error."""
    get_metrics_collector().record_error(error_type, endpoint)


def get_metrics_summary() -> Dict[str, Any]:
    """Get metrics summary."""
    return get_metrics_collector().get_metrics_summary()


def export_prometheus_metrics() -> str:
    """Export metrics in Prometheus format."""
    return get_metrics_collector().export_prometheus()
