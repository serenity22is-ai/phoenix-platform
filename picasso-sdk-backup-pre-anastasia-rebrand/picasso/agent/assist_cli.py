"""
ANASTASIA CLI — Local companion for the AI booking agent.

Runs on the customer's machine. Connects to Claude for the AI brain,
executes file operations locally. Code never leaves the machine.

Usage:
    # Interactive mode
    anastasia --project /path/to/my-ota

    # Or via Python
    python -m picasso.agent.assist_cli --project .

    # With explicit credentials
    anastasia --project . --api-key mys_abc123 --anthropic-key sk-ant-...

    # Generate an admin token at first install
    anastasia --project . --generate-token

MYSTES KYRIOS LLC — Confidential.
"""

import argparse
import json
import os
import sys
import uuid


def get_user_confirmation(description: str) -> bool:
    """Ask the user to confirm a potentially destructive action."""
    print(f"\n  Action: {description}")
    while True:
        resp = input("  Proceed? [y/n]: ").strip().lower()
        if resp in ("y", "yes"):
            return True
        if resp in ("n", "no"):
            return False


def main():
    parser = argparse.ArgumentParser(
        description="ANASTASIA — AI-powered flight booking agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  anastasia --project .
  anastasia --project /path/to/my-ota --agency "Skyline Travel"
  anastasia --project . --model claude-sonnet-4-5-20250929
  anastasia --project . --generate-token

Commands during chat:
  /auth <token> — Authorize admin for code changes (1hr session)
  /audit        — View recent agent actions
  /daemon       — Show auto-heal daemon status
  /usage        — Show token usage and cost
  /reset        — Clear conversation history
  /config       — Show current agency config
  /health       — Run integration health check
  /quit         — Exit
        """,
    )
    parser.add_argument(
        "--project", "-p",
        required=True,
        help="Path to the customer's project root",
    )
    parser.add_argument(
        "--api-key",
        help="ANASTASIA API key (or set ANASTASIA_API_KEY env var)",
    )
    parser.add_argument(
        "--anthropic-key",
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)",
    )
    parser.add_argument(
        "--agency",
        help="Agency name for personalized responses",
    )
    parser.add_argument(
        "--agency-id",
        help="Cockpit agency ID (or set PICASSO_AGENCY_ID env var)",
    )
    parser.add_argument(
        "--branch",
        help="Cockpit branch (or set PICASSO_BRANCH env var)",
    )
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Claude model to use (default: haiku for cost efficiency)",
    )
    parser.add_argument(
        "--auto-confirm",
        action="store_true",
        help="Skip confirmation prompts for file operations (use with caution)",
    )
    parser.add_argument(
        "--generate-token",
        action="store_true",
        help="Generate a new admin auth token and save to .env",
    )
    parser.add_argument(
        "--no-daemon",
        action="store_true",
        help="Disable the auto-heal daemon",
    )
    parser.add_argument(
        "--daemon-interval",
        type=int,
        default=30,
        help="Health check interval in seconds (default: 30)",
    )

    args = parser.parse_args()

    # Load .env if available
    try:
        from dotenv import load_dotenv
        # Try project .env first, then parent
        env_path = os.path.join(args.project, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
        else:
            load_dotenv()
    except ImportError:
        pass

    # Resolve project path
    project_root = os.path.abspath(args.project)
    if not os.path.isdir(project_root):
        print(f"Error: Project directory not found: {project_root}")
        sys.exit(1)

    # Import SDK components
    try:
        from ..client import RedboxClient
        from .assist import AssistAgent
        from .security import AdminAuth, AuditLog, generate_admin_token, hash_token
        from .daemon import AutoHealDaemon
    except ImportError:
        # Handle running as script vs package
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from picasso.client import RedboxClient
        from picasso.agent.assist import AssistAgent
        from picasso.agent.security import AdminAuth, AuditLog, generate_admin_token, hash_token
        from picasso.agent.daemon import AutoHealDaemon

    # Handle --generate-token
    if args.generate_token:
        token = generate_admin_token()
        token_h = hash_token(token)
        print()
        print("=" * 60)
        print("  Admin Auth Token Generated")
        print("=" * 60)
        print()
        print(f"  Token:  {token}")
        print(f"  Hash:   {token_h}")
        print()
        print("  Save the token securely. Add to your project .env:")
        print(f"    ADMIN_AUTH_TOKEN_HASH={token_h}")
        print()
        print("  Give the token to your admin. They'll use /auth <token>")
        print("  in the CLI to authorize code changes.")
        print()

        # Offer to auto-save to .env
        env_path = os.path.join(project_root, ".env")
        try:
            resp = input("  Auto-append to .env? [y/n]: ").strip().lower()
            if resp in ("y", "yes"):
                with open(env_path, "a") as f:
                    f.write(f"\n# ANASTASIA admin auth token hash (generated)\n")
                    f.write(f"ADMIN_AUTH_TOKEN_HASH={token_h}\n")
                print(f"  Saved to {env_path}")
        except (EOFError, KeyboardInterrupt):
            pass

        print()
        return

    # Resolve credentials
    anthropic_key = args.anthropic_key or os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("Error: Anthropic API key required.")
        print("Set ANTHROPIC_API_KEY env var or pass --anthropic-key")
        sys.exit(1)

    agency_id = args.agency_id or os.environ.get("PICASSO_AGENCY_ID", "")
    branch = args.branch or os.environ.get("PICASSO_BRANCH", "")
    session_token = os.environ.get("PICASSO_SESSION_TOKEN", "")

    # Initialize security
    token_hash = os.environ.get("ADMIN_AUTH_TOKEN_HASH", "")
    admin_auth = AdminAuth(token_hash=token_hash or None)
    audit_log = AuditLog(os.path.join(project_root, ".anastasia"))
    session_id = f"cli_{uuid.uuid4().hex[:16]}"

    # Initialize SDK client
    def token_provider():
        return session_token or os.environ.get("PICASSO_SESSION_TOKEN", "")

    client = RedboxClient(
        agency_id=agency_id,
        branch=branch,
        token_provider=token_provider,
    )

    # Confirmation handler
    confirm_fn = (lambda desc: True) if args.auto_confirm else get_user_confirmation

    # Initialize agent with security
    agent = AssistAgent(
        client=client,
        anthropic_api_key=anthropic_key,
        model=args.model,
        mode="cli",
        agency_name=args.agency,
        project_root=project_root,
        on_confirm=confirm_fn,
        admin_auth=admin_auth,
        audit_log=audit_log,
        session_id=session_id,
    )

    # Initialize auto-heal daemon
    daemon = None
    if not args.no_daemon:
        api_base = os.environ.get("ANASTASIA_API_BASE", "") or os.environ.get("MYSTES_API_BASE", "")
        api_key = args.api_key or os.environ.get("ANASTASIA_API_KEY", "") or os.environ.get("MYSTES_API_KEY", "")
        daemon = AutoHealDaemon(
            api_base=api_base,
            api_key=api_key,
            project_root=project_root,
            check_interval=args.daemon_interval,
            error_log_path=os.path.join(project_root, "error.log"),
            audit_log=audit_log,
        )
        daemon.start()

    # Banner
    auth_status = "token configured" if token_hash else "no token (dev mode — all changes allowed)"
    daemon_status = f"running (every {args.daemon_interval}s)" if daemon else "disabled"

    print()
    print("=" * 60)
    print("  ANASTASIA — AI Flight Booking Agent")
    print("=" * 60)
    print(f"  Project:  {project_root}")
    print(f"  Agency:   {args.agency or 'Not set'}")
    print(f"  Model:    {args.model}")
    print(f"  Mode:     CLI (local file access enabled)")
    print(f"  Auth:     {auth_status}")
    print(f"  Daemon:   {daemon_status}")
    print()
    print("  Commands: /auth /audit /daemon /usage /reset /config /health /quit")
    print("=" * 60)
    print()

    # Interactive loop
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            if daemon:
                daemon.stop()
            break

        if not user_input:
            continue

        # Handle slash commands
        if user_input.lower() == "/quit":
            print("Goodbye!")
            if daemon:
                daemon.stop()
            break

        elif user_input.lower().startswith("/auth"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                print("\n  Usage: /auth <admin_token>")
                print("  Authorizes this session for code changes (1hr).")
                if not token_hash:
                    print("  Note: No token configured — run with --generate-token first.")
                print()
                continue

            token = parts[1].strip()
            if agent.authorize_admin(token):
                print("\n  Authorized. Code changes enabled for this session (1hr).\n")
            else:
                print("\n  Invalid token. Authorization denied.\n")
            continue

        elif user_input.lower() == "/audit":
            entries = audit_log.get_recent(20)
            if not entries:
                print("\n  No audit entries yet.\n")
                continue
            print(f"\n  Recent Actions ({len(entries)}):")
            print("  " + "-" * 56)
            for e in entries[-10:]:
                status = "OK" if e.get("success") else "FAIL"
                by = e.get("triggered_by", "?")
                iso = e.get("iso_time", "?")
                tool = e.get("tool", "?")
                summary = e.get("input_summary", "")[:40]
                action = e.get("action_type", "?")[:4].upper()
                print(f"  {iso} [{action}] {tool}: {summary} ({status}, by {by})")
            print()
            continue

        elif user_input.lower() == "/daemon":
            if not daemon:
                print("\n  Daemon is disabled. Start with --no-daemon=false\n")
                continue
            status = daemon.get_status()
            print(f"\n  Auto-Heal Daemon Status:")
            print(f"  " + "-" * 40)
            print(f"  Running:   {status['running']}")
            print(f"  Uptime:    {status['uptime_seconds']}s")
            print(f"  Checks:    {status['total_checks']}")
            print(f"  Fixes:     {status['total_fixes']}")
            print(f"  Failures:  {status['consecutive_failures']} consecutive")
            print(f"  Interval:  {status['check_interval']}s")
            if status["last_checks"]:
                print(f"  Last Check:")
                for c in status["last_checks"]:
                    icon = {"pass": "+", "fail": "!", "warn": "~", "fixed": "*", "skip": "-"}.get(c["status"], "?")
                    print(f"    [{icon}] {c['name']}: {c['message']}")
            print()
            continue

        elif user_input.lower() == "/usage":
            usage = agent.get_usage()
            print(f"\n  Input tokens:  {usage['input_tokens']:,}")
            print(f"  Output tokens: {usage['output_tokens']:,}")
            print(f"  API calls:     {usage['total_requests']}")
            print(f"  Est. cost:     ${usage['estimated_cost_usd']:.4f}")
            print(f"  Config changes: {usage['config_changes']}")
            print()
            continue

        elif user_input.lower() == "/reset":
            agent.reset()
            print("  Conversation cleared.\n")
            continue

        elif user_input.lower() == "/config":
            result = agent._tool_get_config({"section": "all"})
            print(f"\n{json.dumps(result, indent=2, default=str)}\n")
            continue

        elif user_input.lower() == "/health":
            result = agent._tool_check_health({"checks": ["all"]})
            print(f"\n{json.dumps(result, indent=2, default=str)}\n")
            continue

        # Chat with agent
        print()
        response = agent.chat(user_input)
        print(f"ANASTASIA: {response}\n")

    # Cleanup
    if daemon:
        daemon.stop()


if __name__ == "__main__":
    main()
