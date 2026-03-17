"""
SafetyWing Travel Insurance API Client for MYSTES

Integrate travel/health insurance quotes and policy purchases directly
into the MYSTES booking flow. Upsell on every flight/hotel booking.

SafetyWing API:
    Sandbox: https://chick.test-bird.one
    Production: https://api.safetywing.com (confirm after sandbox testing)
    Auth: X-API-KEY header
    Docs: https://documentation.safetywing.com/docs/getting-started

Products:
    - Nomad Insurance: travel medical insurance for nomads/travelers
    - Remote Health: comprehensive health insurance for remote teams

Usage:
    from safetywing_client import SafetyWingClient, get_insurance_quote

    result = get_insurance_quote(
        destination="FR",
        start_date="2026-04-15",
        end_date="2026-04-22",
        travelers=1,
    )
    if result["success"]:
        for plan in result["plans"]:
            print(plan["name"], plan["price"], plan["currency"])
"""

import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

SAFETYWING_SANDBOX_URL = "https://chick.test-bird.one"
SAFETYWING_PRODUCTION_URL = "https://api.safetywing.com"


class SafetyWingClient:
    """
    SafetyWing Insurance API client.

    Auth: X-API-KEY header.
    Sandbox registration: https://test-bird.one/remote-health/signup

    Booking flow:
        1. Get available plans + pricing
        2. Get quote for specific dates/destination
        3. Add members (create policy)
        4. Retrieve policy/member status

    Set SAFETYWING_API_KEY in .env.
    Set SAFETYWING_ENV=production for live (default: sandbox).
    """

    def __init__(self, api_key: Optional[str] = None):
        import requests
        self._key = api_key or os.environ.get("SAFETYWING_API_KEY", "")
        self._session = requests.Session()

        env = os.environ.get("SAFETYWING_ENV", "sandbox").lower()
        if env == "production":
            self._base_url = SAFETYWING_PRODUCTION_URL
        else:
            self._base_url = SAFETYWING_SANDBOX_URL

        self._session.headers.update({
            "X-API-KEY": self._key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def is_configured(self) -> bool:
        return bool(self._key) and len(self._key) >= 10

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _request(self, method: str, path: str, json_data: dict = None,
                 params: dict = None, timeout: int = 30) -> dict:
        """Make an authenticated request to SafetyWing API."""
        try:
            resp = self._session.request(
                method,
                self._url(path),
                json=json_data,
                params=params,
                timeout=timeout,
            )
            if resp.status_code >= 400:
                error_body = resp.json() if resp.text else {}
                error_msg = error_body.get("message", resp.text)
                logger.error("SafetyWing API error %d: %s", resp.status_code, error_msg)
                return {"success": False, "error": error_msg, "status": resp.status_code}
            return {"success": True, "data": resp.json()}
        except Exception as e:
            logger.error("SafetyWing request failed: %s", str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # PLANS
    # =========================================================================

    def get_plans(self) -> dict:
        """
        Get all available insurance plans with pricing.

        Returns:
            dict with plans list (name, coverage, pricing)
        """
        result = self._request("GET", "/api/remote-health/v1/plans")
        if not result["success"]:
            return result

        data = result["data"]
        plans_raw = data if isinstance(data, list) else data.get("data", data.get("plans", []))

        plans = []
        for plan in plans_raw:
            plans.append({
                "plan_id": plan.get("id", plan.get("planId", "")),
                "name": plan.get("name", ""),
                "description": plan.get("description", ""),
                "price_monthly": plan.get("priceMonthly", plan.get("price", {}).get("monthly", 0)),
                "price_weekly": plan.get("priceWeekly", plan.get("price", {}).get("weekly", 0)),
                "currency": plan.get("currency", "USD"),
                "coverage": plan.get("coverage", {}),
                "deductible": plan.get("deductible", 0),
                "max_coverage": plan.get("maxCoverage", plan.get("coverageLimit", 0)),
                "countries": plan.get("countries", plan.get("availableCountries", [])),
            })

        return {"success": True, "plans": plans, "source": "safetywing"}

    # =========================================================================
    # QUOTES
    # =========================================================================

    def get_quote(
        self,
        destination_country: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        travelers: int = 1,
        ages: Optional[List[int]] = None,
        plan_id: Optional[str] = None,
    ) -> dict:
        """
        Get an insurance quote for a trip.

        Args:
            destination_country: ISO country code (e.g., "FR", "US")
            start_date: "YYYY-MM-DD"
            end_date: "YYYY-MM-DD"
            travelers: Number of travelers
            ages: List of traveler ages (if age-based pricing)
            plan_id: Specific plan to quote (optional)

        Returns:
            dict with quote details, pricing per plan
        """
        if not start_date:
            start_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = (datetime.now() + timedelta(days=8)).strftime("%Y-%m-%d")

        body = {
            "startDate": start_date,
            "endDate": end_date,
            "numberOfTravelers": travelers,
        }

        if destination_country:
            body["destinationCountry"] = destination_country.upper()
        if ages:
            body["ages"] = ages
        if plan_id:
            body["planId"] = plan_id

        result = self._request("POST", "/api/remote-health/v1/quotes", json_data=body)
        if not result["success"]:
            # Try alternative endpoint
            result = self._request("POST", "/api/v1/insurance/quotes", json_data=body)

        if not result["success"]:
            return result

        data = result["data"]
        quotes = data if isinstance(data, list) else data.get("quotes", [data])

        parsed_quotes = []
        for quote in quotes:
            parsed_quotes.append({
                "quote_id": quote.get("id", quote.get("quoteId", "")),
                "plan_name": quote.get("planName", quote.get("name", "")),
                "total_price": float(quote.get("totalPrice", quote.get("price", 0))),
                "currency": quote.get("currency", "USD"),
                "price_per_day": float(quote.get("pricePerDay", 0)),
                "coverage_amount": quote.get("coverageAmount", 0),
                "deductible": quote.get("deductible", 0),
                "start_date": start_date,
                "end_date": end_date,
                "travelers": travelers,
                "destination": destination_country,
            })

        return {
            "success": True,
            "quotes": parsed_quotes,
            "source": "safetywing",
        }

    # =========================================================================
    # MEMBERS (Policy Creation)
    # =========================================================================

    def add_member(
        self,
        plan_id: str,
        member: dict,
        start_date: Optional[str] = None,
    ) -> dict:
        """
        Add a member to an insurance plan (creates a policy).

        Args:
            plan_id: Plan ID from get_plans()
            member: {first_name, last_name, email, date_of_birth, nationality}
            start_date: "YYYY-MM-DD" policy start date

        Returns:
            dict with member_id, policy details
        """
        if not start_date:
            start_date = datetime.now().strftime("%Y-%m-%d")

        body = {
            "planId": plan_id,
            "startDate": start_date,
            "firstName": member.get("first_name", ""),
            "lastName": member.get("last_name", ""),
            "email": member.get("email", ""),
            "dateOfBirth": member.get("date_of_birth", ""),
        }

        if member.get("nationality"):
            body["nationality"] = member["nationality"]

        result = self._request("POST", "/api/remote-health/v1/members", json_data=body)
        if not result["success"]:
            return result

        data = result["data"]
        return {
            "success": True,
            "member_id": data.get("id", data.get("memberId", "")),
            "status": data.get("status", ""),
            "policy_number": data.get("policyNumber", ""),
            "plan_name": data.get("planName", ""),
            "start_date": data.get("startDate", start_date),
            "raw": data,
        }

    def get_member(self, member_id: str) -> dict:
        """Get member/policy details."""
        return self._request("GET", f"/api/remote-health/v1/members/{member_id}")

    def list_members(self) -> dict:
        """List all members under the account."""
        return self._request("GET", "/api/remote-health/v1/members")

    # =========================================================================
    # POLICY MANAGEMENT
    # =========================================================================

    def cancel_policy(self, member_id: str, reason: str = "CUSTOMER_REQUEST") -> dict:
        """
        Cancel a member's insurance policy.

        Args:
            member_id: Member ID from add_member
            reason: Cancellation reason

        Returns:
            dict with cancellation status
        """
        body = {"reason": reason}
        result = self._request(
            "POST",
            f"/api/remote-health/v1/members/{member_id}/cancel",
            json_data=body,
        )
        if not result["success"]:
            return result

        data = result["data"]
        return {
            "success": True,
            "member_id": member_id,
            "status": data.get("status", "cancelled"),
        }


# =============================================================================
# CONVENIENCE FUNCTIONS (matches other vertical client patterns)
# =============================================================================

_sw_client: Optional[SafetyWingClient] = None


def _get_client() -> SafetyWingClient:
    global _sw_client
    if _sw_client is None:
        _sw_client = SafetyWingClient()
    return _sw_client


def get_insurance_quote(
    destination: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    travelers: int = 1,
    ages: Optional[List[int]] = None,
) -> dict:
    """
    Get travel insurance quotes via SafetyWing.

    Convenience wrapper matching other vertical client patterns.
    """
    client = _get_client()
    if not client.is_configured():
        return {
            "success": False,
            "error": "SafetyWing not configured — set SAFETYWING_API_KEY in .env",
            "quotes": [],
        }
    return client.get_quote(
        destination_country=destination,
        start_date=start_date,
        end_date=end_date,
        travelers=travelers,
        ages=ages,
    )


def get_insurance_plans() -> dict:
    """Get all available insurance plans."""
    client = _get_client()
    if not client.is_configured():
        return {
            "success": False,
            "error": "SafetyWing not configured — set SAFETYWING_API_KEY in .env",
            "plans": [],
        }
    return client.get_plans()
