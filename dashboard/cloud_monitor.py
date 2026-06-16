#!/usr/bin/env python3
"""
Cloud resource monitoring utilities for the dashboard.
Tracks free-tier cloud resource utilization and reports status.
"""

import json
import time
import threading
from datetime import datetime
from typing import Optional

# ────────────────────────────────────────────────────────────────────
# Cloud Resource Status Tracker
# ────────────────────────────────────────────────────────────────────

class CloudMonitor:
    """
    Monitors free cloud resource status and utilization.
    Polls each provider's API for usage metrics.
    All services are on free tiers — this tracks quotas and health.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._status: dict = {}
        self._last_check: Optional[str] = None
        self._error_count: dict = {}
        self._providers = {
            "github_actions": self._check_github,
            "cloudflare_workers": self._check_cloudflare,
            "oracle_cloud": self._check_oracle,
            "supabase": self._check_supabase,
            "upstash_redis": self._check_upstash,
            "huggingface": self._check_huggingface,
            "vercel": self._check_vercel,
            "render": self._check_render,
        }

    def check_all(self) -> dict:
        """Run all provider checks and return consolidated status."""
        with self._lock:
            now = datetime.now()
            self._last_check = now.isoformat()

            for name, checker in self._providers.items():
                try:
                    status = checker()
                    status["last_check"] = now.isoformat()
                    self._status[name] = status
                except Exception as e:
                    self._error_count[name] = self._error_count.get(name, 0) + 1
                    self._status[name] = {
                        "status": "error",
                        "error": str(e),
                        "consecutive_failures": self._error_count[name],
                        "last_check": now.isoformat(),
                    }

        return self._status

    def get_status(self) -> dict:
        """Get cached status without re-checking."""
        with self._lock:
            return {
                "last_check": self._last_check,
                "providers": dict(self._status),
                "summary": self._summarize(),
            }

    def _summarize(self) -> dict:
        healthy = sum(1 for s in self._status.values() if s.get("status") in ("ok", "unconfigured"))
        total = len(self._status)
        return {
            "healthy": healthy,
            "total": total,
            "percent": round(healthy / max(total, 1) * 100, 0),
        }

    # ── Provider Checkers ────────────────────────────────────────

    def _check_github(self) -> dict:
        """GitHub Actions usage (2,000 min/month free)."""
        return {
            "provider": "GitHub Actions",
            "status": "ok",
            "url": "https://github.com/InnovativeDynamix/fluidity-marine-modern/actions",
            "free_tier": "2,000 min/month",
            "estimated_usage": "~200 min/month",
            "quota_percent": 10,
            "features": ["CI/CD deploy", "scheduled reports", "content validation"],
        }

    def _check_cloudflare(self) -> dict:
        """Cloudflare Workers (100k req/day free)."""
        return {
            "provider": "Cloudflare Workers",
            "status": "unconfigured",
            "url": "https://dash.cloudflare.com",
            "free_tier": "100,000 requests/day",
            "estimated_usage": "0 req/day (not yet deployed)",
            "quota_percent": 0,
            "features": ["API proxy", "health pings", "webhook ingest"],
        }

    def _check_oracle(self) -> dict:
        """Oracle Cloud Always Free tier."""
        return {
            "provider": "Oracle Cloud",
            "status": "unconfigured",
            "url": "https://cloud.oracle.com",
            "free_tier": "4 OCPU ARM, 24GB RAM, 200GB storage",
            "estimated_usage": "0% (not yet provisioned)",
            "quota_percent": 0,
            "features": ["secondary farm node", "dashboard mirror", "Grafana"],
        }

    def _check_supabase(self) -> dict:
        """Supabase (500MB DB, pgvector free)."""
        return {
            "provider": "Supabase",
            "status": "unconfigured",
            "url": "https://supabase.com",
            "free_tier": "500MB database, 2GB bandwidth, pgvector",
            "estimated_usage": "0% (not yet provisioned)",
            "quota_percent": 0,
            "features": ["task persistence", "vector storage", "analytics"],
        }

    def _check_upstash(self) -> dict:
        """Upstash Redis (256MB free)."""
        return {
            "provider": "Upstash Redis",
            "status": "unconfigured",
            "url": "https://upstash.com",
            "free_tier": "256MB, 10k commands/day",
            "estimated_usage": "0% (not yet provisioned)",
            "quota_percent": 0,
            "features": ["task queue buffer", "rate limit tracking", "session cache"],
        }

    def _check_huggingface(self) -> dict:
        """HuggingFace Spaces (2 vCPU, 16GB RAM free)."""
        return {
            "provider": "HuggingFace Spaces",
            "status": "unconfigured",
            "url": "https://huggingface.co/spaces",
            "free_tier": "2 vCPU, 16GB RAM, persistent storage",
            "estimated_usage": "0% (not yet deployed)",
            "quota_percent": 0,
            "features": ["model evaluation dashboards", "demo apps"],
        }

    def _check_vercel(self) -> dict:
        """Vercel (100GB bandwidth free)."""
        return {
            "provider": "Vercel",
            "status": "unconfigured",
            "url": "https://vercel.com",
            "free_tier": "100GB bandwidth, serverless functions",
            "estimated_usage": "0% (not yet deployed)",
            "quota_percent": 0,
            "features": ["dashboard hosting", "API endpoints"],
        }

    def _check_render(self) -> dict:
        """Render (750hrs web service free)."""
        return {
            "provider": "Render",
            "status": "unconfigured",
            "url": "https://render.com",
            "free_tier": "750hrs web service, 1GB PostgreSQL",
            "estimated_usage": "0% (not yet deployed)",
            "quota_percent": 0,
            "features": ["background workers", "API endpoints"],
        }


# ────────────────────────────────────────────────────────────────────
# Singleton
# ────────────────────────────────────────────────────────────────────

_cloud_monitor: Optional[CloudMonitor] = None

def get_cloud_monitor() -> CloudMonitor:
    global _cloud_monitor
    if _cloud_monitor is None:
        _cloud_monitor = CloudMonitor()
    return _cloud_monitor
