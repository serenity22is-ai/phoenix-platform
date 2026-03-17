"""
Trend Analyzer — Price trend analysis and simple forecasting.

Analyzes historical pricing data from the PricingAggregator to detect
trends (rising/falling/stable), seasonal patterns, price anomalies,
and optimal booking windows. Prediction uses moving-average extrapolation
only — no ML dependencies.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .aggregator import PricingAggregator

logger = logging.getLogger(__name__)

# Minimum data points required for meaningful analysis
_MIN_DATA_POINTS = 5

# Threshold for "stable" trend: change must exceed this percentage
_STABLE_THRESHOLD_PCT = 3.0

# Standard deviations threshold for anomaly detection
_ANOMALY_STD_DEVS = 2.0

# Number of days per "season" for seasonality detection (quarterly)
_SEASON_LENGTH_DAYS = 91


class TrendAnalyzer:
    """
    Price trend analysis engine.

    Operates on data collected by a PricingAggregator instance. Provides
    trend direction detection, seasonality analysis, moving-average
    predictions, anomaly detection, and booking window optimization.

    All analysis is statistical — no machine learning models are used.
    This keeps the module lightweight and deterministic.

    Args:
        aggregator: PricingAggregator instance to read historical data from.

    Usage:
        analyzer = TrendAnalyzer(aggregator)
        trend = analyzer.analyze_trend("JFK-LHR", period_days=90)
        prediction = analyzer.predict_price("JFK-LHR", days_ahead=7)
    """

    def __init__(self, aggregator: PricingAggregator):
        self._aggregator = aggregator

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_trend(
        self,
        route: str,
        period_days: int = 90,
    ) -> Dict[str, Any]:
        """
        Analyze the price trend for a route over a time period.

        Computes a linear regression over daily average prices to determine
        whether the trend is rising, falling, or stable. Confidence is
        based on the R-squared value of the regression and the number of
        data points.

        Args:
            route: Route identifier (e.g. ``"JFK-LHR"``).
            period_days: Number of days to analyze. Defaults to 90.

        Returns:
            Dict with keys:
            - ``direction``: ``"rising"``, ``"falling"``, or ``"stable"``
            - ``change_pct``: Percentage change over the period
            - ``confidence``: Confidence score (0.0 to 1.0)
            - ``data_points``: Number of daily data points used
            - ``route``: The route analyzed
            - ``period_days``: The period analyzed
        """
        route = route.upper().strip()
        daily_avgs = self._get_daily_averages(route, period_days)

        if len(daily_avgs) < _MIN_DATA_POINTS:
            return {
                "direction": "stable",
                "change_pct": 0.0,
                "confidence": 0.0,
                "data_points": len(daily_avgs),
                "route": route,
                "period_days": period_days,
            }

        # Extract x (day index) and y (average price) for regression
        prices = [avg["avg_price"] for avg in daily_avgs]
        x_values = list(range(len(prices)))

        slope, intercept, r_squared = self._linear_regression(
            x_values, prices
        )

        # Calculate percentage change from start to end of regression line
        start_price = intercept
        end_price = intercept + slope * (len(prices) - 1)

        if start_price > 0:
            change_pct = ((end_price - start_price) / start_price) * 100.0
        else:
            change_pct = 0.0

        # Determine direction
        if abs(change_pct) < _STABLE_THRESHOLD_PCT:
            direction = "stable"
        elif change_pct > 0:
            direction = "rising"
        else:
            direction = "falling"

        # Confidence: combination of R-squared and data sufficiency
        data_sufficiency = min(len(daily_avgs) / 30.0, 1.0)
        confidence = round(r_squared * 0.7 + data_sufficiency * 0.3, 3)

        return {
            "direction": direction,
            "change_pct": round(change_pct, 2),
            "confidence": min(confidence, 1.0),
            "data_points": len(daily_avgs),
            "route": route,
            "period_days": period_days,
        }

    def detect_seasonality(
        self,
        route: str,
    ) -> Dict[str, Any]:
        """
        Detect seasonal price patterns for a route.

        Analyzes up to 365 days of data, grouping by month to identify
        which months tend to have higher or lower prices. Requires at
        least 90 days of data for meaningful results.

        Args:
            route: Route identifier (e.g. ``"JFK-LHR"``).

        Returns:
            Dict with keys:
            - ``seasonal``: Whether a seasonal pattern was detected (bool)
            - ``monthly_averages``: Dict mapping month name to average price
            - ``cheapest_month``: Month name with the lowest average price
            - ``most_expensive_month``: Month name with the highest average
            - ``price_range_pct``: Percentage difference between cheapest
              and most expensive months
            - ``data_points``: Total observations used
            - ``route``: The route analyzed
        """
        route = route.upper().strip()
        daily_avgs = self._get_daily_averages(route, period_days=365)

        if len(daily_avgs) < _MIN_DATA_POINTS:
            return {
                "seasonal": False,
                "monthly_averages": {},
                "cheapest_month": None,
                "most_expensive_month": None,
                "price_range_pct": 0.0,
                "data_points": len(daily_avgs),
                "route": route,
            }

        # Group by month
        month_prices: Dict[str, List[float]] = {}
        month_names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]

        for avg in daily_avgs:
            dt = datetime.fromtimestamp(avg["timestamp"], tz=timezone.utc)
            month_name = month_names[dt.month - 1]
            if month_name not in month_prices:
                month_prices[month_name] = []
            month_prices[month_name].append(avg["avg_price"])

        # Calculate monthly averages
        monthly_averages = {}
        for month, prices in month_prices.items():
            monthly_averages[month] = round(sum(prices) / len(prices), 2)

        if not monthly_averages:
            return {
                "seasonal": False,
                "monthly_averages": {},
                "cheapest_month": None,
                "most_expensive_month": None,
                "price_range_pct": 0.0,
                "data_points": len(daily_avgs),
                "route": route,
            }

        cheapest_month = min(monthly_averages, key=monthly_averages.get)
        most_expensive_month = max(monthly_averages, key=monthly_averages.get)

        cheapest_price = monthly_averages[cheapest_month]
        expensive_price = monthly_averages[most_expensive_month]

        if cheapest_price > 0:
            price_range_pct = (
                (expensive_price - cheapest_price) / cheapest_price
            ) * 100.0
        else:
            price_range_pct = 0.0

        # A seasonal pattern exists if the price range exceeds 15%
        seasonal = price_range_pct > 15.0 and len(monthly_averages) >= 3

        return {
            "seasonal": seasonal,
            "monthly_averages": monthly_averages,
            "cheapest_month": cheapest_month,
            "most_expensive_month": most_expensive_month,
            "price_range_pct": round(price_range_pct, 2),
            "data_points": len(daily_avgs),
            "route": route,
        }

    def predict_price(
        self,
        route: str,
        days_ahead: int = 7,
    ) -> Dict[str, Any]:
        """
        Predict future price using moving-average extrapolation.

        Uses a weighted moving average of the last 14 days to project
        the price forward. This is a simple statistical method, not
        machine learning. Confidence decreases with longer prediction
        horizons.

        Args:
            route: Route identifier (e.g. ``"JFK-LHR"``).
            days_ahead: Number of days to predict forward. Defaults to 7.

        Returns:
            Dict with keys:
            - ``predicted_price``: The forecasted price
            - ``current_price``: Most recent observed average price
            - ``change_pct``: Predicted change from current price
            - ``confidence``: Prediction confidence (decays with horizon)
            - ``method``: Always ``"weighted_moving_average"``
            - ``route``: The route analyzed
            - ``days_ahead``: The prediction horizon
        """
        route = route.upper().strip()
        daily_avgs = self._get_daily_averages(route, period_days=30)

        if len(daily_avgs) < _MIN_DATA_POINTS:
            return {
                "predicted_price": 0.0,
                "current_price": 0.0,
                "change_pct": 0.0,
                "confidence": 0.0,
                "method": "weighted_moving_average",
                "route": route,
                "days_ahead": days_ahead,
            }

        prices = [avg["avg_price"] for avg in daily_avgs]
        current_price = prices[-1]

        # Weighted moving average: recent prices have higher weight
        window = min(14, len(prices))
        recent = prices[-window:]
        weights = list(range(1, window + 1))  # 1, 2, 3, ..., window
        total_weight = sum(weights)

        wma = sum(p * w for p, w in zip(recent, weights)) / total_weight

        # Calculate daily rate of change from the WMA trend
        if len(recent) >= 2:
            # Use last 7 days (or fewer) to estimate daily change
            trend_window = min(7, len(recent))
            recent_trend = recent[-trend_window:]
            if recent_trend[0] > 0:
                daily_change_rate = (
                    (recent_trend[-1] - recent_trend[0])
                    / recent_trend[0]
                    / trend_window
                )
            else:
                daily_change_rate = 0.0
        else:
            daily_change_rate = 0.0

        # Project forward
        predicted_price = wma * (1 + daily_change_rate * days_ahead)
        predicted_price = max(predicted_price, 0.0)  # Price cannot be negative

        if current_price > 0:
            change_pct = (
                (predicted_price - current_price) / current_price
            ) * 100.0
        else:
            change_pct = 0.0

        # Confidence decays with prediction horizon
        base_confidence = min(len(daily_avgs) / 20.0, 1.0)
        horizon_decay = max(1.0 - (days_ahead / 30.0), 0.1)
        confidence = round(base_confidence * horizon_decay, 3)

        return {
            "predicted_price": round(predicted_price, 2),
            "current_price": round(current_price, 2),
            "change_pct": round(change_pct, 2),
            "confidence": min(confidence, 1.0),
            "method": "weighted_moving_average",
            "route": route,
            "days_ahead": days_ahead,
        }

    def find_anomalies(
        self,
        route: str,
        period_days: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Detect price anomalies for a route.

        An anomaly is a daily average price that deviates more than 2
        standard deviations from the period mean. Both unusually cheap
        and unusually expensive prices are flagged.

        Args:
            route: Route identifier (e.g. ``"JFK-LHR"``).
            period_days: Number of days to analyze. Defaults to 30.

        Returns:
            List of anomaly dicts, each with:
            - ``date``: ISO date string
            - ``price``: The anomalous average price
            - ``mean``: The period mean price
            - ``std_dev``: The period standard deviation
            - ``deviation``: How many standard deviations from the mean
            - ``type``: ``"high"`` or ``"low"``
        """
        route = route.upper().strip()
        daily_avgs = self._get_daily_averages(route, period_days)

        if len(daily_avgs) < _MIN_DATA_POINTS:
            return []

        prices = [avg["avg_price"] for avg in daily_avgs]
        mean = sum(prices) / len(prices)
        std_dev = self._std_dev(prices)

        if std_dev == 0:
            return []

        anomalies = []
        for avg in daily_avgs:
            price = avg["avg_price"]
            deviation = abs(price - mean) / std_dev

            if deviation > _ANOMALY_STD_DEVS:
                dt = datetime.fromtimestamp(
                    avg["timestamp"], tz=timezone.utc
                )
                anomalies.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "price": round(price, 2),
                    "mean": round(mean, 2),
                    "std_dev": round(std_dev, 2),
                    "deviation": round(deviation, 2),
                    "type": "high" if price > mean else "low",
                })

        # Sort by deviation descending (most anomalous first)
        anomalies.sort(key=lambda a: a["deviation"], reverse=True)
        return anomalies

    def get_best_booking_window(
        self,
        route: str,
    ) -> Dict[str, Any]:
        """
        Determine the optimal booking window for cheapest prices.

        Analyzes historical daily averages to find which day-of-week and
        which period within the available data had the lowest prices. This
        helps identify patterns like "Tuesdays are cheapest" or "book
        3-4 weeks before departure."

        Args:
            route: Route identifier (e.g. ``"JFK-LHR"``).

        Returns:
            Dict with keys:
            - ``best_day_of_week``: Day name with lowest average price
            - ``day_of_week_averages``: Dict mapping day name to avg price
            - ``best_period``: Description of cheapest booking period
            - ``recommendation``: Human-readable booking recommendation
            - ``data_points``: Number of daily data points used
            - ``route``: The route analyzed
        """
        route = route.upper().strip()
        daily_avgs = self._get_daily_averages(route, period_days=180)

        day_names = [
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday",
        ]

        if len(daily_avgs) < _MIN_DATA_POINTS:
            return {
                "best_day_of_week": None,
                "day_of_week_averages": {},
                "best_period": None,
                "recommendation": (
                    "Insufficient data to determine optimal booking window."
                ),
                "data_points": len(daily_avgs),
                "route": route,
            }

        # Group by day of week
        dow_prices: Dict[str, List[float]] = {
            day: [] for day in day_names
        }

        for avg in daily_avgs:
            dt = datetime.fromtimestamp(avg["timestamp"], tz=timezone.utc)
            day_name = day_names[dt.weekday()]
            dow_prices[day_name].append(avg["avg_price"])

        # Calculate day-of-week averages
        dow_averages = {}
        for day, prices in dow_prices.items():
            if prices:
                dow_averages[day] = round(sum(prices) / len(prices), 2)

        # Find cheapest day
        if dow_averages:
            best_day = min(dow_averages, key=dow_averages.get)
        else:
            best_day = None

        # Find best period (split data into thirds and compare)
        prices = [avg["avg_price"] for avg in daily_avgs]
        third = max(len(prices) // 3, 1)

        early = prices[:third]
        middle = prices[third:2 * third]
        late = prices[2 * third:]

        period_avgs = {}
        if early:
            period_avgs["early (4-6 months out)"] = (
                sum(early) / len(early)
            )
        if middle:
            period_avgs["middle (2-4 months out)"] = (
                sum(middle) / len(middle)
            )
        if late:
            period_avgs["recent (0-2 months out)"] = (
                sum(late) / len(late)
            )

        if period_avgs:
            best_period = min(period_avgs, key=period_avgs.get)
        else:
            best_period = None

        # Build recommendation
        parts = []
        if best_day and dow_averages:
            worst_day = max(dow_averages, key=dow_averages.get)
            if best_day != worst_day:
                savings = dow_averages[worst_day] - dow_averages[best_day]
                parts.append(
                    f"Book on {best_day}s for the best prices "
                    f"(avg ${dow_averages[best_day]:.0f} vs "
                    f"${dow_averages[worst_day]:.0f} on {worst_day}s, "
                    f"saving ~${savings:.0f})."
                )
        if best_period:
            parts.append(
                f"The {best_period} booking window tends to have "
                f"the lowest fares."
            )

        recommendation = " ".join(parts) if parts else (
            "No strong booking window pattern detected."
        )

        return {
            "best_day_of_week": best_day,
            "day_of_week_averages": dow_averages,
            "best_period": best_period,
            "recommendation": recommendation,
            "data_points": len(daily_avgs),
            "route": route,
        }

    def compare_periods(
        self,
        route: str,
        period1_start: float,
        period1_end: float,
        period2_start: float,
        period2_end: float,
    ) -> Dict[str, Any]:
        """
        Compare pricing between two time periods.

        Calculates average, min, max, and sample count for each period,
        then computes the difference. Useful for year-over-year or
        before/after comparisons.

        Args:
            route: Route identifier (e.g. ``"JFK-LHR"``).
            period1_start: Unix timestamp for the start of period 1.
            period1_end: Unix timestamp for the end of period 1.
            period2_start: Unix timestamp for the start of period 2.
            period2_end: Unix timestamp for the end of period 2.

        Returns:
            Dict with keys:
            - ``route``: The route analyzed
            - ``period1``: Stats dict for period 1
            - ``period2``: Stats dict for period 2
            - ``change_pct``: Percentage change from period 1 to period 2
            - ``direction``: ``"rising"``, ``"falling"``, or ``"stable"``
        """
        route = route.upper().strip()

        # Determine the total date range needed
        earliest = min(period1_start, period2_start)
        total_days = int((time.time() - earliest) / 86400) + 1
        daily_avgs = self._get_daily_averages(route, period_days=total_days)

        def filter_period(
            avgs: List[Dict[str, Any]],
            start: float,
            end: float,
        ) -> Dict[str, Any]:
            filtered = [
                a for a in avgs
                if start <= a["timestamp"] <= end
            ]
            if not filtered:
                return {
                    "avg_price": 0.0,
                    "min": 0.0,
                    "max": 0.0,
                    "samples": 0,
                    "start": datetime.fromtimestamp(
                        start, tz=timezone.utc
                    ).strftime("%Y-%m-%d"),
                    "end": datetime.fromtimestamp(
                        end, tz=timezone.utc
                    ).strftime("%Y-%m-%d"),
                }
            prices = [a["avg_price"] for a in filtered]
            return {
                "avg_price": round(sum(prices) / len(prices), 2),
                "min": round(min(prices), 2),
                "max": round(max(prices), 2),
                "samples": len(prices),
                "start": datetime.fromtimestamp(
                    start, tz=timezone.utc
                ).strftime("%Y-%m-%d"),
                "end": datetime.fromtimestamp(
                    end, tz=timezone.utc
                ).strftime("%Y-%m-%d"),
            }

        p1_stats = filter_period(daily_avgs, period1_start, period1_end)
        p2_stats = filter_period(daily_avgs, period2_start, period2_end)

        # Calculate change
        if p1_stats["avg_price"] > 0:
            change_pct = (
                (p2_stats["avg_price"] - p1_stats["avg_price"])
                / p1_stats["avg_price"]
            ) * 100.0
        else:
            change_pct = 0.0

        if abs(change_pct) < _STABLE_THRESHOLD_PCT:
            direction = "stable"
        elif change_pct > 0:
            direction = "rising"
        else:
            direction = "falling"

        return {
            "route": route,
            "period1": p1_stats,
            "period2": p2_stats,
            "change_pct": round(change_pct, 2),
            "direction": direction,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_daily_averages(
        self,
        route: str,
        period_days: int,
    ) -> List[Dict[str, Any]]:
        """
        Get daily average prices for a route, sorted chronologically.

        Groups raw observations by calendar day (UTC) and computes the
        average price per day.

        Returns:
            List of dicts, each with ``date``, ``avg_price``, ``count``,
            and ``timestamp`` (midnight UTC for the day).
        """
        observations = self._aggregator._get_observations(route, period_days)

        if not observations:
            return []

        # Group by date
        daily: Dict[str, List[float]] = {}
        daily_ts: Dict[str, float] = {}

        for obs in observations:
            ts = obs.get("timestamp", 0)
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            date_key = dt.strftime("%Y-%m-%d")
            if date_key not in daily:
                daily[date_key] = []
                # Store a representative timestamp (midnight UTC)
                daily_ts[date_key] = datetime(
                    dt.year, dt.month, dt.day, tzinfo=timezone.utc
                ).timestamp()
            daily[date_key].append(obs.get("price", 0.0))

        # Build sorted list of daily averages
        result = []
        for date_key in sorted(daily.keys()):
            prices = daily[date_key]
            result.append({
                "date": date_key,
                "avg_price": sum(prices) / len(prices),
                "count": len(prices),
                "timestamp": daily_ts[date_key],
            })

        return result

    @staticmethod
    def _linear_regression(
        x: List[float],
        y: List[float],
    ) -> Tuple[float, float, float]:
        """
        Simple linear regression (y = slope * x + intercept).

        Returns:
            Tuple of (slope, intercept, r_squared).
        """
        n = len(x)
        if n < 2:
            return 0.0, 0.0, 0.0

        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi ** 2 for xi in x)
        sum_y2 = sum(yi ** 2 for yi in y)

        denominator = n * sum_x2 - sum_x ** 2
        if denominator == 0:
            return 0.0, sum_y / n, 0.0

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n

        # R-squared calculation
        ss_res = sum((yi - (slope * xi + intercept)) ** 2 for xi, yi in zip(x, y))
        mean_y = sum_y / n
        ss_tot = sum((yi - mean_y) ** 2 for yi in y)

        if ss_tot == 0:
            r_squared = 1.0 if ss_res == 0 else 0.0
        else:
            r_squared = max(1.0 - (ss_res / ss_tot), 0.0)

        return slope, intercept, r_squared

    @staticmethod
    def _std_dev(values: List[float]) -> float:
        """Calculate population standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return math.sqrt(variance)
