"""
CrossSellEngine Tests — Build #182 + #183

Tests zero-cost deterministic recommendation engine.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cross_sell_engine import CrossSellEngine


class TestCrossSellRules:
    """Test recommendation rules per vertical."""

    def test_flight_recommends_hotel_first(self):
        engine = CrossSellEngine()
        recs = engine.recommend("flight")
        assert len(recs) >= 1
        assert recs[0]["vertical"] == "hotel"

    def test_flight_full_chain(self):
        engine = CrossSellEngine()
        recs = engine.recommend("flight")
        verticals = [r["vertical"] for r in recs]
        assert verticals == ["hotel", "car", "activities", "insurance"]

    def test_hotel_recommends_activities_first(self):
        engine = CrossSellEngine()
        recs = engine.recommend("hotel")
        assert recs[0]["vertical"] == "activities"

    def test_car_recommends_insurance(self):
        engine = CrossSellEngine()
        recs = engine.recommend("car")
        assert len(recs) == 1
        assert recs[0]["vertical"] == "insurance"

    def test_insurance_is_terminal(self):
        engine = CrossSellEngine()
        recs = engine.recommend("insurance")
        assert recs == []

    def test_activity_recommends_insurance_and_hotel(self):
        engine = CrossSellEngine()
        recs = engine.recommend("activity")
        verticals = [r["vertical"] for r in recs]
        assert verticals == ["insurance", "hotel"]


class TestCrossSellCapabilities:
    """Test capability-based filtering."""

    def test_filters_unavailable_verticals(self):
        caps = {"flights": True, "hotels": True, "cars": False, "activities": False, "insurance": False}
        engine = CrossSellEngine(capabilities=caps)
        recs = engine.recommend("flight")
        verticals = [r["vertical"] for r in recs]
        assert "car" not in verticals
        assert "activities" not in verticals
        assert "insurance" not in verticals
        assert "hotel" in verticals

    def test_all_capabilities_disabled_returns_empty(self):
        caps = {"flights": True, "hotels": False, "cars": False, "activities": False, "insurance": False}
        engine = CrossSellEngine(capabilities=caps)
        recs = engine.recommend("flight")
        assert recs == []


class TestCrossSellURLs:
    """Test destination-aware URL building."""

    def test_destination_in_hotel_url(self):
        engine = CrossSellEngine()
        recs = engine.recommend("flight", destination="FCO", date="2026-05-01", return_date="2026-05-10")
        hotel_rec = next(r for r in recs if r["vertical"] == "hotel")
        assert "destination=FCO" in hotel_rec["url"]
        assert "check_in=2026-05-01" in hotel_rec["url"]
        assert "check_out=2026-05-10" in hotel_rec["url"]

    def test_destination_in_car_url(self):
        engine = CrossSellEngine()
        recs = engine.recommend("flight", destination="LAX", date="2026-06-01")
        car_rec = next(r for r in recs if r["vertical"] == "car")
        assert "destination=LAX" in car_rec["url"]
        assert "pickup_date=2026-06-01" in car_rec["url"]

    def test_no_destination_uses_base_url(self):
        engine = CrossSellEngine()
        recs = engine.recommend("flight")
        hotel_rec = next(r for r in recs if r["vertical"] == "hotel")
        assert hotel_rec["url"] == "/hotels"


class TestCrossSellConcierge:
    """Test for_concierge single recommendation."""

    def test_for_concierge_returns_single(self):
        engine = CrossSellEngine()
        rec = engine.for_concierge("flight")
        assert rec is not None
        assert rec["vertical"] == "hotel"
        assert "title" in rec

    def test_for_concierge_none_for_terminal(self):
        engine = CrossSellEngine()
        rec = engine.for_concierge("insurance")
        assert rec is None

    def test_for_concierge_respects_capabilities(self):
        caps = {"flights": True, "hotels": False, "cars": False, "activities": False, "insurance": False}
        engine = CrossSellEngine(capabilities=caps)
        rec = engine.for_concierge("flight")
        assert rec is None


class TestCrossSellForTrip:
    """Test for_trip() missing vertical recommendations (Build #183)."""

    def test_missing_verticals_recommended(self):
        engine = CrossSellEngine()
        recs = engine.for_trip(["flight", "hotel"])
        verticals = [r["vertical"] for r in recs]
        assert "car" in verticals
        assert "activities" in verticals
        assert "insurance" in verticals
        assert "flight" not in verticals
        assert "hotel" not in verticals

    def test_all_present_returns_empty(self):
        engine = CrossSellEngine()
        recs = engine.for_trip(["flight", "hotel", "car", "activities", "insurance"])
        assert recs == []

    def test_for_trip_respects_capabilities(self):
        caps = {"flights": True, "hotels": True, "cars": False, "activities": True, "insurance": False}
        engine = CrossSellEngine(capabilities=caps)
        recs = engine.for_trip(["flight"])
        verticals = [r["vertical"] for r in recs]
        assert "hotel" in verticals
        assert "activities" in verticals
        assert "car" not in verticals
        assert "insurance" not in verticals


class TestCrossSellPointsMultiplier:
    """Test points_multiplier in recommendations (Build #183)."""

    def test_free_tier_gets_1x(self):
        engine = CrossSellEngine()
        recs = engine.recommend("flight", user_tier="free")
        assert all(r["points_multiplier"] == 1.0 for r in recs)

    def test_travel_plus_gets_2x(self):
        engine = CrossSellEngine()
        recs = engine.recommend("flight", user_tier="travel_plus")
        assert all(r["points_multiplier"] == 2.0 for r in recs)

    def test_multiplier_in_recommendation_dict(self):
        engine = CrossSellEngine()
        recs = engine.recommend("flight")
        for rec in recs:
            assert "points_multiplier" in rec
            assert isinstance(rec["points_multiplier"], float)
