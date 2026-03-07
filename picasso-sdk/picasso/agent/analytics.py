"""
Analytics — Usage dashboards, error tracking, and business intelligence.

Provides:
    - Per-agency usage summaries (searches, bookings, AI requests, revenue)
    - Error rate tracking and classification
    - Platform-wide aggregate metrics (for ANASTASiA internal)
    - Cost estimation (COGS per agency)
    - Exportable reports

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import time
from collections import defaultdict
from typing import List, Optional

logger = logging.getLogger(__name__)


class ErrorTracker:
    """
    Track and classify API errors per agency.

    Categories:
        - auth: Token/session errors (401, 403)
        - search: Flight search failures
        - booking: Booking/cart failures
        - network: Timeout, connection errors
        - rate_limit: 429 responses
        - internal: 500+ server errors
        - validation: 400 bad request
    """

    CATEGORIES = ("auth", "search", "booking", "network", "rate_limit", "internal", "validation")

    def __init__(self, data_dir: str = ".error_data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    def _period_key(self, timestamp: float = None) -> str:
        t = time.gmtime(timestamp or time.time())
        return f"{t.tm_year:04d}-{t.tm_mon:02d}"

    def _path(self, key_hash: str, period: str) -> str:
        return os.path.join(self.data_dir, f"err_{key_hash}_{period}.json")

    def _load(self, key_hash: str, period: str = None) -> dict:
        period = period or self._period_key()
        path = self._path(key_hash, period)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "key_hash": key_hash,
            "period": period,
            "total_errors": 0,
            "by_category": {cat: 0 for cat in self.CATEGORIES},
            "recent_errors": [],
        }

    def _save(self, key_hash: str, data: dict, period: str = None):
        period = period or self._period_key()
        path = self._path(key_hash, period)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def record_error(
        self,
        key_hash: str,
        category: str,
        endpoint: str = "",
        status_code: int = 0,
        message: str = "",
    ):
        """
        Record an API error.

        Args:
            key_hash: Agency API key hash
            category: Error category (auth, search, booking, network, rate_limit, internal, validation)
            endpoint: API endpoint that failed
            status_code: HTTP status code
            message: Error message (truncated to 200 chars)
        """
        period = self._period_key()
        data = self._load(key_hash, period)

        data["total_errors"] += 1
        cat = category if category in self.CATEGORIES else "internal"
        data["by_category"][cat] = data["by_category"].get(cat, 0) + 1

        # Keep last 50 errors
        data["recent_errors"].append({
            "timestamp": time.time(),
            "category": cat,
            "endpoint": endpoint,
            "status_code": status_code,
            "message": message[:200],
        })
        if len(data["recent_errors"]) > 50:
            data["recent_errors"] = data["recent_errors"][-50:]

        self._save(key_hash, data, period)

    def classify_http_error(self, status_code: int) -> str:
        """Classify an HTTP status code into an error category."""
        if status_code in (401, 403):
            return "auth"
        elif status_code == 429:
            return "rate_limit"
        elif status_code == 400:
            return "validation"
        elif status_code >= 500:
            return "internal"
        return "network"

    def get_errors(self, key_hash: str, period: str = None) -> dict:
        """Get error summary for an agency."""
        return self._load(key_hash, period or self._period_key())

    def get_error_rate(self, key_hash: str, total_requests: int) -> dict:
        """
        Calculate error rate as percentage of total requests.

        Returns:
            {"error_rate_pct": float, "total_errors": int, "total_requests": int, "by_category": {...}}
        """
        errors = self._load(key_hash)
        total = errors.get("total_errors", 0)
        rate = (total / max(total_requests, 1)) * 100

        return {
            "error_rate_pct": round(rate, 2),
            "total_errors": total,
            "total_requests": total_requests,
            "by_category": errors.get("by_category", {}),
        }


class AnalyticsEngine:
    """
    Analytics engine for usage dashboards and business intelligence.

    Aggregates data from UsageTracker + ErrorTracker + BillingManager.
    """

    def __init__(
        self,
        usage_tracker,
        error_tracker: ErrorTracker,
        billing_manager=None,
    ):
        self.usage = usage_tracker
        self.errors = error_tracker
        self.billing = billing_manager

    def agency_dashboard(self, key_hash: str) -> dict:
        """
        Generate dashboard data for a single agency.

        Returns everything an agency admin needs:
        - Current period usage vs limits
        - Error rates
        - Cost estimation
        - Trends (last 3 months)
        """
        # Current usage
        current_usage = self.usage.get_usage(key_hash)

        # Error data
        error_data = self.errors.get_errors(key_hash)
        total_requests = (
            current_usage.get("ai_requests", 0)
            + current_usage.get("searches", 0)
            + current_usage.get("bookings", 0)
            + current_usage.get("documents", 0)
        )
        error_rate = self.errors.get_error_rate(key_hash, total_requests)

        # Billing / subscription
        billing_info = {}
        cost_info = {}
        if self.billing:
            billing_info = self.billing.get_subscription(key_hash)
            cost_info = self.billing.estimate_cost(key_hash)

        # Usage history (last 3 months)
        history = self.usage.get_usage_history(key_hash, months=3)

        # Compute daily average for current period
        first_req = current_usage.get("first_request_at")
        if first_req:
            days_active = max(1, (time.time() - first_req) / 86400)
            daily_avg = {
                "ai_requests": round(current_usage.get("ai_requests", 0) / days_active, 1),
                "searches": round(current_usage.get("searches", 0) / days_active, 1),
                "bookings": round(current_usage.get("bookings", 0) / days_active, 1),
            }
        else:
            daily_avg = {"ai_requests": 0, "searches": 0, "bookings": 0}

        return {
            "period": current_usage.get("period"),
            "usage": {
                "ai_requests": current_usage.get("ai_requests", 0),
                "searches": current_usage.get("searches", 0),
                "bookings": current_usage.get("bookings", 0),
                "documents": current_usage.get("documents", 0),
                "ai_input_tokens": current_usage.get("ai_input_tokens", 0),
                "ai_output_tokens": current_usage.get("ai_output_tokens", 0),
            },
            "daily_average": daily_avg,
            "errors": {
                "total": error_data.get("total_errors", 0),
                "rate_pct": error_rate.get("error_rate_pct", 0),
                "by_category": error_data.get("by_category", {}),
                "recent": error_data.get("recent_errors", [])[-5:],
            },
            "billing": billing_info,
            "cost": cost_info,
            "history": [
                {
                    "period": h.get("period"),
                    "ai_requests": h.get("ai_requests", 0),
                    "searches": h.get("searches", 0),
                    "bookings": h.get("bookings", 0),
                }
                for h in history
            ],
        }

    def platform_metrics(self, config_store) -> dict:
        """
        Platform-wide aggregate metrics (ANASTASiA internal).

        Scans all agency configs and usage data.

        Args:
            config_store: ConfigStore instance to enumerate agencies.

        Returns:
            Aggregate metrics across all agencies.
        """
        agencies = config_store.list_all()
        totals = {
            "total_agencies": len(agencies),
            "active_agencies": 0,
            "total_ai_requests": 0,
            "total_searches": 0,
            "total_bookings": 0,
            "total_documents": 0,
            "total_errors": 0,
            "total_ai_input_tokens": 0,
            "total_ai_output_tokens": 0,
            "by_plan": defaultdict(int),
            "by_tier": defaultdict(int),
            "estimated_revenue": 0.0,
            "estimated_cogs": 0.0,
        }

        for agency in agencies:
            key_hash = agency.get("key_hash", "")
            if not key_hash:
                continue

            if agency.get("active", True):
                totals["active_agencies"] += 1

            # Usage
            usage = self.usage.get_usage(key_hash)
            totals["total_ai_requests"] += usage.get("ai_requests", 0)
            totals["total_searches"] += usage.get("searches", 0)
            totals["total_bookings"] += usage.get("bookings", 0)
            totals["total_documents"] += usage.get("documents", 0)
            totals["total_ai_input_tokens"] += usage.get("ai_input_tokens", 0)
            totals["total_ai_output_tokens"] += usage.get("ai_output_tokens", 0)

            # Errors
            errors = self.errors.get_errors(key_hash)
            totals["total_errors"] += errors.get("total_errors", 0)

            # Plan distribution
            tier = agency.get("tier", "unknown")
            totals["by_tier"][tier] += 1

            # Revenue estimate
            if self.billing:
                sub = self.billing.get_subscription(key_hash)
                plan_id = sub.get("plan_id")
                if plan_id:
                    totals["by_plan"][plan_id] += 1
                    from .billing import PLANS
                    plan = PLANS.get(plan_id)
                    if plan:
                        totals["estimated_revenue"] += plan.price_monthly_usd

        # COGS estimation (Haiku pricing)
        input_cost = (totals["total_ai_input_tokens"] / 1_000_000) * 0.80
        output_cost = (totals["total_ai_output_tokens"] / 1_000_000) * 4.00
        totals["estimated_cogs"] = round(input_cost + output_cost, 2)
        totals["estimated_revenue"] = round(totals["estimated_revenue"], 2)
        totals["estimated_margin"] = round(totals["estimated_revenue"] - totals["estimated_cogs"], 2)

        # Convert defaultdicts
        totals["by_plan"] = dict(totals["by_plan"])
        totals["by_tier"] = dict(totals["by_tier"])

        return totals

    def export_usage_csv(self, key_hash: str, months: int = 6) -> str:
        """
        Export usage data as CSV string.

        Returns:
            CSV with columns: period, ai_requests, searches, bookings, documents, errors
        """
        history = self.usage.get_usage_history(key_hash, months)
        lines = ["period,ai_requests,searches,bookings,documents,errors"]
        for h in history:
            period = h.get("period", "")
            errors = self.errors.get_errors(key_hash, period)
            lines.append(
                f"{period},"
                f"{h.get('ai_requests', 0)},"
                f"{h.get('searches', 0)},"
                f"{h.get('bookings', 0)},"
                f"{h.get('documents', 0)},"
                f"{errors.get('total_errors', 0)}"
            )
        return "\n".join(lines)


# ============================================================================
# ANALYTICS DASHBOARD HTML
# ============================================================================

ANALYTICS_DASHBOARD_HTML = """
<div id="analyticsTab" class="tab-content">
    <div class="tab-header">
        <h2>Usage & Analytics</h2>
        <button class="btn btn-small" onclick="refreshAnalytics()">Refresh</button>
    </div>

    <!-- Usage Summary Cards -->
    <div class="analytics-grid">
        <div class="metric-card">
            <div class="metric-label">AI Requests</div>
            <div class="metric-value" id="metricAiRequests">—</div>
            <div class="metric-sub" id="metricAiLimit">/ — limit</div>
            <div class="metric-bar"><div class="metric-fill" id="barAiRequests"></div></div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Flight Searches</div>
            <div class="metric-value" id="metricSearches">—</div>
            <div class="metric-sub" id="metricSearchAvg">— avg/day</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Bookings</div>
            <div class="metric-value" id="metricBookings">—</div>
            <div class="metric-sub" id="metricBookingAvg">— avg/day</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Error Rate</div>
            <div class="metric-value" id="metricErrorRate">—</div>
            <div class="metric-sub" id="metricErrors">— total errors</div>
        </div>
    </div>

    <!-- Cost Estimate -->
    <div class="analytics-section">
        <h3>Current Period Cost</h3>
        <div class="cost-grid">
            <div class="cost-item">
                <span class="cost-label">Base Plan</span>
                <span class="cost-value" id="costBase">$—</span>
            </div>
            <div class="cost-item">
                <span class="cost-label">Overage</span>
                <span class="cost-value" id="costOverage">$—</span>
            </div>
            <div class="cost-item total">
                <span class="cost-label">Estimated Total</span>
                <span class="cost-value" id="costTotal">$—</span>
            </div>
        </div>
    </div>

    <!-- Error Breakdown -->
    <div class="analytics-section">
        <h3>Error Breakdown</h3>
        <div class="error-categories" id="errorCategories">
            <div class="error-cat"><span class="cat-name">Loading...</span></div>
        </div>
    </div>

    <!-- Recent Errors -->
    <div class="analytics-section">
        <h3>Recent Errors</h3>
        <div class="error-log" id="errorLog">
            <div class="error-entry">No errors recorded.</div>
        </div>
    </div>
</div>

<style>
.analytics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
}
.metric-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
}
.metric-label {
    font-size: 12px;
    color: #999;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
}
.metric-value {
    font-size: 32px;
    font-weight: 600;
    color: #f5f5f5;
}
.metric-sub {
    font-size: 11px;
    color: #666;
    margin-top: 4px;
}
.metric-bar {
    height: 4px;
    background: rgba(255,255,255,0.08);
    border-radius: 2px;
    margin-top: 12px;
    overflow: hidden;
}
.metric-fill {
    height: 100%;
    background: linear-gradient(90deg, #6366f1, #a855f7);
    border-radius: 2px;
    transition: width 0.5s ease;
    width: 0%;
}
.analytics-section {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
}
.analytics-section h3 {
    font-family: 'Cinzel', serif;
    font-size: 15px;
    margin-bottom: 16px;
    color: #ccc;
}
.cost-grid {
    display: flex;
    flex-direction: column;
    gap: 8px;
}
.cost-item {
    display: flex;
    justify-content: space-between;
    padding: 8px 0;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    font-size: 14px;
}
.cost-item.total {
    border-bottom: none;
    border-top: 1px solid rgba(255,255,255,0.15);
    padding-top: 12px;
    font-weight: 600;
    font-size: 16px;
}
.cost-label { color: #999; }
.cost-value { color: #f5f5f5; }
.error-categories {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 8px;
}
.error-cat {
    display: flex;
    justify-content: space-between;
    padding: 8px 12px;
    background: rgba(255,255,255,0.03);
    border-radius: 6px;
    font-size: 13px;
}
.cat-name { color: #999; }
.cat-count { color: #f5f5f5; font-weight: 500; }
.cat-count.high { color: #ef4444; }
.error-log {
    max-height: 200px;
    overflow-y: auto;
}
.error-entry {
    padding: 8px 12px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
    font-size: 12px;
    font-family: 'SF Mono', monospace;
    color: #999;
}
.error-entry .err-time { color: #666; margin-right: 8px; }
.error-entry .err-cat {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    text-transform: uppercase;
    margin-right: 6px;
}
.err-cat.auth { background: rgba(239,68,68,0.2); color: #ef4444; }
.err-cat.search { background: rgba(245,158,11,0.2); color: #f59e0b; }
.err-cat.booking { background: rgba(239,68,68,0.2); color: #ef4444; }
.err-cat.network { background: rgba(107,114,128,0.2); color: #9ca3af; }
.err-cat.rate_limit { background: rgba(245,158,11,0.2); color: #f59e0b; }
.err-cat.internal { background: rgba(239,68,68,0.3); color: #f87171; }
.err-cat.validation { background: rgba(99,102,241,0.2); color: #818cf8; }
</style>

<script>
async function refreshAnalytics() {
    try {
        const resp = await fetch(API_BASE + '/api/v1/analytics/dashboard', {
            headers: {'Authorization': 'Bearer ' + API_KEY}
        });
        const data = await resp.json();

        // Usage metrics
        const u = data.usage || {};
        document.getElementById('metricAiRequests').textContent = (u.ai_requests || 0).toLocaleString();
        document.getElementById('metricSearches').textContent = (u.searches || 0).toLocaleString();
        document.getElementById('metricBookings').textContent = (u.bookings || 0).toLocaleString();

        // AI limit bar
        const billing = data.billing || {};
        const aiUsage = billing.usage?.ai_requests || {};
        const limit = aiUsage.limit || 0;
        if (limit > 0) {
            document.getElementById('metricAiLimit').textContent = `/ ${limit.toLocaleString()} limit`;
            const pct = Math.min(100, ((u.ai_requests || 0) / limit) * 100);
            document.getElementById('barAiRequests').style.width = pct + '%';
            if (pct > 90) document.getElementById('barAiRequests').style.background = '#ef4444';
        }

        // Daily averages
        const avg = data.daily_average || {};
        document.getElementById('metricSearchAvg').textContent = (avg.searches || 0) + ' avg/day';
        document.getElementById('metricBookingAvg').textContent = (avg.bookings || 0) + ' avg/day';

        // Errors
        const e = data.errors || {};
        document.getElementById('metricErrorRate').textContent = (e.rate_pct || 0) + '%';
        document.getElementById('metricErrors').textContent = (e.total || 0) + ' total errors';

        // Cost
        const c = data.cost || {};
        document.getElementById('costBase').textContent = '$' + (c.base_cost || 0).toFixed(2);
        document.getElementById('costOverage').textContent = '$' + (c.overage_cost || 0).toFixed(2);
        document.getElementById('costTotal').textContent = '$' + (c.total_estimated || 0).toFixed(2);

        // Error categories
        const cats = e.by_category || {};
        const catEl = document.getElementById('errorCategories');
        catEl.innerHTML = Object.entries(cats).map(([cat, count]) =>
            `<div class="error-cat"><span class="cat-name">${cat}</span><span class="cat-count${count>10?' high':''}">${count}</span></div>`
        ).join('');

        // Recent errors
        const recent = e.recent || [];
        const logEl = document.getElementById('errorLog');
        if (recent.length === 0) {
            logEl.innerHTML = '<div class="error-entry" style="color:#22c55e">No errors recorded this period.</div>';
        } else {
            logEl.innerHTML = recent.map(err => {
                const t = new Date(err.timestamp * 1000).toLocaleString();
                return `<div class="error-entry"><span class="err-time">${t}</span><span class="err-cat ${err.category}">${err.category}</span>${err.endpoint} — ${err.message}</div>`;
            }).join('');
        }
    } catch(e) {
        console.error('Analytics fetch error:', e);
    }
}

// Auto-refresh on tab switch
if (typeof tabObserver === 'undefined') {
    refreshAnalytics();
}
</script>
"""
