"""
CrossSellEngine — Zero-cost deterministic recommendation engine.

Pure Python, no AI calls. Recommends complementary verticals based on what
the user just searched/booked, filtered by which verticals have credentials.

MYSTES KYRIOS LLC — Confidential.
"""

from urllib.parse import urlencode


# Priority-ordered recommendation rules per trigger vertical
_RULES = {
    "flight":    ["hotel", "car", "activities", "insurance"],
    "hotel":     ["activities", "car", "insurance"],
    "car":       ["insurance"],
    "activity":  ["insurance", "hotel"],
    "insurance": [],  # terminal — nothing to cross-sell
}

# Display metadata for each vertical
_VERTICAL_META = {
    "hotel": {
        "title": "Need a Place to Stay?",
        "subtitle": "Search 2M+ properties worldwide",
        "icon": "fas fa-hotel",
        "base_url": "/hotels",
    },
    "car": {
        "title": "Rent a Car",
        "subtitle": "500+ suppliers, best price guaranteed",
        "icon": "fas fa-car",
        "base_url": "/cars",
    },
    "activities": {
        "title": "Discover Experiences",
        "subtitle": "300,000+ tours and activities",
        "icon": "fas fa-hiking",
        "base_url": "/activities",
    },
    "insurance": {
        "title": "Protect Your Trip",
        "subtitle": "Travel insurance from a few dollars/day",
        "icon": "fas fa-shield-alt",
        "base_url": "/flights",
    },
    "flight": {
        "title": "Search Flights",
        "subtitle": "Compare prices across airlines",
        "icon": "fas fa-plane",
        "base_url": "/flights",
    },
}

# Tiers that get bonus points on cross-sold bookings
_BONUS_TIERS = {"travel_plus", "b2b_starter", "b2b_growth", "b2b_volume"}


class CrossSellEngine:
    """Zero-cost deterministic cross-sell recommendations."""

    def __init__(self, capabilities=None):
        """
        Args:
            capabilities: dict of {vertical: bool} — which verticals are available.
                          If None, all verticals are assumed available.
        """
        self._capabilities = capabilities or {}

    def _is_available(self, vertical):
        """Check if a vertical has credentials configured."""
        if not self._capabilities:
            return True
        # Map recommendation names to capability keys
        key_map = {"hotel": "hotels", "car": "cars", "activity": "activities",
                   "flight": "flights", "activities": "activities", "insurance": "insurance"}
        key = key_map.get(vertical, vertical)
        return self._capabilities.get(key, False)

    @staticmethod
    def _build_url(base_url, vertical, destination="", date="", return_date=""):
        """Build destination-aware URL for a vertical."""
        params = {}
        if destination:
            params["destination"] = destination
        if date:
            if vertical == "hotel":
                params["check_in"] = date
                if return_date:
                    params["check_out"] = return_date
            elif vertical == "car":
                params["pickup_date"] = date
                if return_date:
                    params["dropoff_date"] = return_date
            elif vertical == "activities":
                params["date_from"] = date
            elif vertical == "insurance":
                params["start_date"] = date
                if return_date:
                    params["end_date"] = return_date

        if params:
            return f"{base_url}?{urlencode(params)}"
        return base_url

    def recommend(self, current_vertical, destination="", date="", return_date="", user_tier="free"):
        """
        Get priority-ordered cross-sell recommendations.

        Args:
            current_vertical: What the user is currently looking at
            destination: Optional destination for URL building
            date: Optional date for URL building
            return_date: Optional return date for URL building
            user_tier: User subscription tier for points multiplier

        Returns:
            List of recommendation dicts [{vertical, title, subtitle, url, icon, priority, points_multiplier}]
        """
        rules = _RULES.get(current_vertical, [])
        recommendations = []
        points_multiplier = 2.0 if user_tier in _BONUS_TIERS else 1.0

        for priority, vertical in enumerate(rules):
            if not self._is_available(vertical):
                continue

            meta = _VERTICAL_META.get(vertical)
            if not meta:
                continue

            url = self._build_url(meta["base_url"], vertical, destination, date, return_date)

            recommendations.append({
                "vertical": vertical,
                "title": meta["title"],
                "subtitle": meta["subtitle"],
                "url": url,
                "icon": meta["icon"],
                "priority": priority,
                "points_multiplier": points_multiplier,
            })

        return recommendations

    def for_concierge(self, current_vertical, destination="", date=""):
        """
        Get single highest-priority recommendation for concierge chat bubble.

        Returns:
            dict with {vertical, title, subtitle, url, icon} or None
        """
        recs = self.recommend(current_vertical, destination=destination, date=date)
        return recs[0] if recs else None

    def for_trip(self, existing_verticals, destination="", date="", return_date=""):
        """
        Recommend what's missing from a trip.

        Args:
            existing_verticals: list of verticals already in trip ["flight", "hotel"]
            destination: Trip destination
            date: Trip start date
            return_date: Trip end date

        Returns:
            List of recommendations for missing verticals
        """
        all_verticals = ["flight", "hotel", "car", "activities", "insurance"]
        missing = [v for v in all_verticals if v not in existing_verticals and self._is_available(v)]

        recs = []
        for priority, vertical in enumerate(missing):
            meta = _VERTICAL_META.get(vertical)
            if not meta:
                continue
            url = self._build_url(meta["base_url"], vertical, destination, date, return_date)
            recs.append({
                "vertical": vertical,
                "title": meta["title"],
                "subtitle": meta["subtitle"],
                "url": url,
                "icon": meta["icon"],
                "priority": priority,
            })
        return recs
