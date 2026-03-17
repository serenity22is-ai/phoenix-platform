#!/usr/bin/env python3
"""
Agent Demo — Interactive CLI for the Redbox Booking Agent.

Run: python3 examples/agent_demo.py

Requires:
    - ANTHROPIC_API_KEY in .env or environment
    - Valid Cockpit credentials (PICASSO_USERNAME, PICASSO_PASSWORD, PICASSO_TOTP_SECRET)
      OR PICASSO_SESSION_TOKEN
    - PICASSO_AGENCY_ID and PICASSO_BRANCH in .env or environment
"""

import os
import sys

# Add parent to path for local dev
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from picasso.auth import TokenManager
from picasso.client import RedboxClient
from picasso.agent.orchestrator import BookingAgent


def main():
    # Validate config
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("ERROR: ANTHROPIC_API_KEY not set in .env or environment")
        sys.exit(1)

    agency_id = os.environ.get("PICASSO_AGENCY_ID", "629818")
    branch = os.environ.get("PICASSO_BRANCH", "PICL_707")

    # Set up auth
    token_manager = TokenManager(
        username=os.environ.get("PICASSO_USERNAME"),
        password=os.environ.get("PICASSO_PASSWORD"),
        totp_secret=os.environ.get("PICASSO_TOTP_SECRET"),
        manual_token=os.environ.get("PICASSO_SESSION_TOKEN"),
    )

    # Create SDK client
    client = RedboxClient(
        agency_id=agency_id,
        branch=branch,
        token_provider=token_manager.get_token,
    )

    # Verify token
    if not client.is_configured():
        print("ERROR: No valid Cockpit session token. Check credentials.")
        sys.exit(1)

    print("=" * 60)
    print("  REDBOX BOOKING AGENT — Interactive Demo")
    print("  Powered by Claude + Picasso Redbox SDK")
    print("=" * 60)
    print()
    print("Type your request in natural language.")
    print("Examples:")
    print('  "Find flights from JFK to London next Tuesday"')
    print('  "Search business class LAX to Tokyo in March"')
    print('  "Show me the cheapest nonstop from Miami to New York"')
    print()
    print("Commands:  /usage  /reset  /quit")
    print("-" * 60)

    # Create agent
    agent = BookingAgent(
        client=client,
        anthropic_api_key=anthropic_key,
        agency_name="Demo Agency",
    )

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/quit", "/exit", "quit", "exit"):
            print("Goodbye!")
            break

        if user_input.lower() == "/usage":
            usage = agent.get_usage()
            print(f"\n  Input tokens:  {usage['input_tokens']:,}")
            print(f"  Output tokens: {usage['output_tokens']:,}")
            print(f"  API requests:  {usage['total_requests']}")
            print(f"  Est. cost:     ${usage['estimated_cost_usd']:.4f}")
            continue

        if user_input.lower() == "/reset":
            agent.reset()
            print("\n  Conversation reset.")
            continue

        # Chat
        print("\nAgent: ", end="", flush=True)
        response = agent.chat(user_input)
        print(response)


if __name__ == "__main__":
    main()
