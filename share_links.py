"""
PHOENIX Multi-Platform Share Links & Contract Templates

Generates platform-specific share URLs for deal links (P2P escrow contracts)
and referral links (app signup). Wraps any Phoenix URL into deep links for
WhatsApp, Telegram, Signal, Facebook, Messenger, X/Twitter, Instagram,
TikTok, Gmail, SMS, and generic clipboard copy.

Also provides reusable smart contract templates for common transaction types.

Usage:
    from share_links import generate_deal_share_links, generate_referral_share_links
    from share_links import get_contract_templates, get_template, apply_template

    links = generate_deal_share_links(deal_dict, "https://phoenix.app")
    links = generate_referral_share_links("MYCODE", "John", "https://phoenix.app")
    templates = get_contract_templates()
    details = apply_template("goods_standard", {"item_description": "...", "agreed_price": 500})
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import quote, quote_plus

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:5001")


# ---------------------------------------------------------------------------
# Platform Registry
# ---------------------------------------------------------------------------

PLATFORMS = {
    "whatsapp": {
        "name": "WhatsApp",
        "icon": "whatsapp",
        "direct_share": True,
        "template": "https://wa.me/?text={message}",
    },
    "telegram": {
        "name": "Telegram",
        "icon": "telegram",
        "direct_share": True,
        "template": "https://t.me/share/url?url={url}&text={text}",
    },
    "signal": {
        "name": "Signal",
        "icon": "signal",
        "direct_share": False,
        "note": "Copy the message and paste it in Signal",
    },
    "facebook": {
        "name": "Facebook",
        "icon": "facebook",
        "direct_share": True,
        "template": "https://www.facebook.com/sharer/sharer.php?u={url}&quote={text}",
    },
    "messenger": {
        "name": "Messenger",
        "icon": "messenger",
        "direct_share": True,
        "template": "https://www.facebook.com/dialog/send?link={url}&redirect_uri={url}",
    },
    "x": {
        "name": "X (Twitter)",
        "icon": "x-twitter",
        "direct_share": True,
        "template": "https://twitter.com/intent/tweet?url={url}&text={text}",
    },
    "instagram": {
        "name": "Instagram",
        "icon": "instagram",
        "direct_share": False,
        "note": "Copy the message and share it via Instagram DM",
    },
    "tiktok": {
        "name": "TikTok",
        "icon": "tiktok",
        "direct_share": False,
        "note": "Copy the message and share it via TikTok",
    },
    "gmail": {
        "name": "Gmail",
        "icon": "gmail",
        "direct_share": True,
        "template": "https://mail.google.com/mail/?view=cm&su={subject}&body={body}",
    },
    "sms": {
        "name": "SMS",
        "icon": "sms",
        "direct_share": True,
        "template": "sms:?body={message}",
    },
    "email": {
        "name": "Email",
        "icon": "email",
        "direct_share": True,
        "template": "mailto:?subject={subject}&body={body}",
    },
    "copy": {
        "name": "Copy Link",
        "icon": "copy",
        "direct_share": False,
    },
}


# ---------------------------------------------------------------------------
# Share Link Generation
# ---------------------------------------------------------------------------

@dataclass
class ShareContext:
    """Context for generating share links."""
    url: str
    title: str
    description: str
    message: str
    subject: str = ""


def generate_share_links(ctx: ShareContext) -> dict:
    """Generate platform-specific share URLs for any Phoenix URL.

    Returns a dict with 'platforms' (per-platform URLs), 'raw_url', and 'raw_message'.
    """
    encoded_url = quote(ctx.url, safe="")
    encoded_msg = quote(ctx.message, safe="")
    encoded_text = quote(ctx.description, safe="")
    encoded_subject = quote(ctx.subject or ctx.title, safe="")
    encoded_body = quote(f"{ctx.message}\n\n{ctx.url}", safe="")

    platforms = {}

    for key, cfg in PLATFORMS.items():
        entry = {
            "name": cfg["name"],
            "icon": cfg["icon"],
            "direct_share": cfg["direct_share"],
        }

        if key == "copy":
            entry["text"] = f"{ctx.message}\n\n{ctx.url}"
            entry["url"] = ctx.url
        elif cfg["direct_share"] and "template" in cfg:
            url_str = cfg["template"].format(
                url=encoded_url,
                text=encoded_text,
                message=encoded_msg,
                subject=encoded_subject,
                body=encoded_body,
            )
            entry["url"] = url_str
        else:
            # No direct share — return clipboard text
            entry["text"] = f"{ctx.message}\n\n{ctx.url}"
            entry["url"] = ctx.url
            if "note" in cfg:
                entry["note"] = cfg["note"]

        platforms[key] = entry

    return {
        "platforms": platforms,
        "raw_url": ctx.url,
        "raw_message": ctx.message,
    }


def generate_deal_share_links(deal: dict, base_url: str = None) -> dict:
    """Generate share links for a private market deal.

    Args:
        deal: Deal dict (from PrivateMarketDeal.to_dict())
        base_url: Base URL for the app (default: from env)

    Returns:
        Share links dict with all platform URLs.
    """
    base = base_url or BASE_URL
    link_token = deal.get("link_token", "")
    full_url = f"{base}/deal/link/{link_token}"

    item = deal.get("item_description", "Item")[:80]
    price = deal.get("agreed_price_rlusd", 0)

    message = (
        f"I'm sending you a secure escrow deal through PHOENIX:\n\n"
        f"{item}\n"
        f"{price:.2f} RLUSD\n"
        f"Protected by XRPL smart contract escrow\n\n"
        f"Click to review and accept: {full_url}\n\n"
        f"PHOENIX — Trustless P2P transactions powered by XRPL"
    )

    ctx = ShareContext(
        url=full_url,
        title=f"Deal Proposal: {item[:50]}",
        description=f"Secure escrow deal for {item[:50]} — {price:.2f} RLUSD",
        message=message,
        subject=f"PHOENIX Deal Proposal: {item[:50]}",
    )

    return generate_share_links(ctx)


def generate_referral_share_links(referral_code: str, user_name: str = "",
                                   base_url: str = None) -> dict:
    """Generate share links for a referral/app download invitation.

    Args:
        referral_code: User's referral code
        user_name: Name of the person sharing
        base_url: Base URL for the app (default: from env)

    Returns:
        Share links dict with all platform URLs.
    """
    base = base_url or BASE_URL
    referral_url = f"{base}/join/{referral_code}"

    inviter = user_name or "A friend"

    message = (
        f"{inviter} invited you to join PHOENIX — the geographic proxy arbitrage engine.\n\n"
        f"Browse any market worldwide through proxy nodes\n"
        f"Save on flights, hotels, and products across borders\n"
        f"All transactions secured by XRPL escrow\n\n"
        f"Sign up: {referral_url}"
    )

    ctx = ShareContext(
        url=referral_url,
        title="Join PHOENIX",
        description=f"{inviter} invited you to PHOENIX — geographic arbitrage engine",
        message=message,
        subject=f"{inviter} invited you to PHOENIX",
    )

    return generate_share_links(ctx)


def get_platform_list() -> List[dict]:
    """Return list of all supported share platforms with metadata."""
    return [
        {
            "id": key,
            "name": cfg["name"],
            "icon": cfg["icon"],
            "direct_share": cfg["direct_share"],
        }
        for key, cfg in PLATFORMS.items()
    ]


# ---------------------------------------------------------------------------
# Smart Contract Templates
# ---------------------------------------------------------------------------

CONTRACT_TEMPLATES = {
    "goods_standard": {
        "template_id": "goods_standard",
        "name": "Standard Goods Purchase",
        "description": "Physical goods with delivery confirmation. Buyer confirms receipt to release funds.",
        "defaults": {
            "deal_type": "goods",
            "deadline_days": 14,
            "dispute_window_days": 7,
            "auto_release": False,
            "inspection_days": 0,
        },
        "escrow_terms": (
            "Funds locked until buyer confirms delivery. "
            "Dispute window: 7 days after delivery confirmation."
        ),
        "disclaimer": "PHOENIX is not liable for physical goods condition or delivery.",
    },
    "goods_high_value": {
        "template_id": "goods_high_value",
        "name": "High-Value Goods Purchase",
        "description": "Vehicles, electronics >$1000. Includes 3-day inspection period after delivery.",
        "defaults": {
            "deal_type": "goods",
            "deadline_days": 21,
            "dispute_window_days": 10,
            "auto_release": False,
            "inspection_days": 3,
        },
        "escrow_terms": (
            "Funds locked until buyer confirms delivery AND 3-day inspection period passes. "
            "Buyer may dispute during inspection. Dispute window: 10 days total."
        ),
        "disclaimer": "PHOENIX is not liable for physical goods condition, authenticity, or delivery.",
    },
    "services_standard": {
        "template_id": "services_standard",
        "name": "Standard Service Contract",
        "description": "Freelance, consulting, or one-time services. Buyer confirms completion.",
        "defaults": {
            "deal_type": "services",
            "deadline_days": 7,
            "dispute_window_days": 5,
            "auto_release": False,
            "inspection_days": 0,
        },
        "escrow_terms": (
            "Funds locked until buyer confirms service completion. "
            "Dispute window: 5 days after confirmation."
        ),
        "disclaimer": "PHOENIX is not liable for service quality or completion.",
    },
    "services_milestone": {
        "template_id": "services_milestone",
        "name": "Milestone-Based Service Contract",
        "description": "Long-term services with milestone-based partial releases.",
        "defaults": {
            "deal_type": "services",
            "deadline_days": 30,
            "dispute_window_days": 7,
            "auto_release": False,
            "inspection_days": 0,
            "milestones": True,
        },
        "escrow_terms": (
            "Funds can be partially released at agreed milestones. "
            "Each milestone release requires buyer confirmation. "
            "Dispute window: 7 days per milestone."
        ),
        "disclaimer": "PHOENIX is not liable for service quality or milestone completion.",
    },
    "digital_instant": {
        "template_id": "digital_instant",
        "name": "Digital Goods / Instant Delivery",
        "description": "Digital goods, codes, licenses. Auto-release after delivery proof.",
        "defaults": {
            "deal_type": "digital",
            "deadline_days": 1,
            "dispute_window_days": 3,
            "auto_release": True,
            "inspection_days": 0,
        },
        "escrow_terms": (
            "Funds auto-release 24 hours after seller marks delivered, "
            "unless buyer opens dispute. Dispute window: 3 days."
        ),
        "disclaimer": "PHOENIX is not liable for digital goods functionality or licensing.",
    },
    "vehicle_purchase": {
        "template_id": "vehicle_purchase",
        "name": "Vehicle Purchase",
        "description": "Cars, motorcycles, boats. Includes title transfer verification and inspection period.",
        "defaults": {
            "deal_type": "vehicle",
            "deadline_days": 30,
            "dispute_window_days": 14,
            "auto_release": False,
            "inspection_days": 5,
        },
        "escrow_terms": (
            "Funds locked until buyer confirms receipt, title transfer, "
            "AND 5-day mechanical inspection period passes. "
            "Dispute window: 14 days total."
        ),
        "disclaimer": (
            "PHOENIX is not liable for vehicle condition, title status, or delivery. "
            "Buyer should conduct independent inspection."
        ),
    },
    "rental_deposit": {
        "template_id": "rental_deposit",
        "name": "Rental Deposit / Security Bond",
        "description": "Equipment rental, property deposit. Refundable on return in agreed condition.",
        "defaults": {
            "deal_type": "rental",
            "deadline_days": 90,
            "dispute_window_days": 7,
            "auto_release": False,
            "inspection_days": 1,
        },
        "escrow_terms": (
            "Deposit locked for rental duration. Released back to renter on return "
            "in agreed condition, or to owner if condition not met. "
            "Dispute window: 7 days after return."
        ),
        "disclaimer": "PHOENIX is not liable for rental property condition or return logistics.",
    },
    "custom": {
        "template_id": "custom",
        "name": "Custom Agreement",
        "description": "User-defined terms. Set your own deadlines, conditions, and dispute windows.",
        "defaults": {
            "deal_type": "other",
            "deadline_days": 14,
            "dispute_window_days": 7,
            "auto_release": False,
            "inspection_days": 0,
        },
        "escrow_terms": "Custom terms defined by the parties.",
        "disclaimer": "PHOENIX is not liable for transaction execution. Terms are between the parties.",
    },
}


def get_contract_templates() -> List[dict]:
    """Return all available contract templates."""
    return list(CONTRACT_TEMPLATES.values())


def get_template(template_id: str) -> Optional[dict]:
    """Get a specific contract template by ID."""
    return CONTRACT_TEMPLATES.get(template_id)


def apply_template(template_id: str, deal_details: dict) -> dict:
    """Apply a contract template to deal details, merging defaults.

    Template defaults are applied ONLY for keys not already present
    in deal_details, so user overrides always win.

    Args:
        template_id: Template ID (e.g. 'goods_standard')
        deal_details: User-provided deal details dict

    Returns:
        Merged deal details with template defaults applied.
    """
    template = CONTRACT_TEMPLATES.get(template_id)
    if not template:
        return deal_details

    merged = dict(deal_details)

    # Apply defaults (user overrides win)
    for key, value in template["defaults"].items():
        if key not in merged:
            merged[key] = value

    # Attach template metadata
    merged["_template_id"] = template_id
    merged["_template_name"] = template["name"]
    merged["_escrow_terms"] = template["escrow_terms"]
    merged["_disclaimer"] = template["disclaimer"]

    return merged
