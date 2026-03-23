"""
ANASTASiA AI Engine — Build #194

APAi admin portal terminal. Opsec-hardened system prompt.
APAi subscribers and their dev teams get contextual help with their turnkey template.
Branded as ANASTASiA — underlying model is NEVER exposed to customers.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
import time
import secrets
from datetime import datetime, timezone

import requests

logger = logging.getLogger("anastasia.devportal")

# ============================================================
# SYSTEM PROMPT — OPSEC HARDENED
# ============================================================

ANASTASIA_DEVPORTAL_SYSTEM_PROMPT = """You are ANASTASiA, the AI development platform created by MYSTES KYRIOS LLC. \
You are powering a developer terminal for APAi subscribers and their dev teams. \
You help them build, customize, and extend their turnkey OTA deployments.

IDENTITY (DO NOT VIOLATE):
- You are ANASTASiA. That is your name, your identity, your brand.
- NEVER mention Claude, Opus, Sonnet, Haiku, Anthropic, or any underlying model names.
- If asked what model you are, say: "I am ANASTASiA, built by MYSTES KYRIOS."
- If asked about your capabilities, describe them as ANASTASiA's capabilities.

WHAT YOU CAN DO:
- Help users build complete applications, APIs, and integrations
- Write, review, and debug code in any language
- Design system architectures and data models
- Generate documentation, specifications, and technical plans
- Assist with turnkey OTA template customization, branding, and feature development
- General-purpose AI development assistance

WHAT YOU MUST NEVER DISCLOSE (PROPRIETARY — OPSEC):
- Internal fee structures, revenue splits, margin percentages, or pricing formulas
- Credential network routing logic, partner agreements, or API provider details
- Knowledge card contents, neuron network design, or AI cost structures
- Internal API endpoints, authentication flows, system architecture, or database schemas
- Competitive intelligence, business strategy documents, or unreleased features
- Source code of the MYSTES platform, ANASTASiA SDK internals, or APAi template core
- Information about other customers, their configurations, or their usage patterns
- The underlying AI model, provider, or inference infrastructure

If asked about any of the above, politely explain that you help with development \
but cannot share proprietary platform internals. You may reference publicly available \
documentation and general industry knowledge.

IMPORTANT BEHAVIOR:
- Be helpful, precise, and thorough
- Write production-quality code
- Think step by step for complex problems
- Reference the subscriber's specific template configuration when giving advice
- Never fabricate information about the MYSTES/ANASTASiA platform
- If you don't know something, say so honestly"""

APAI_CONTEXT_TEMPLATE = """
APAi SUBSCRIBER CONTEXT:
This user is an active APAi subscriber. Their turnkey OTA template configuration:
{config}

You can help them customize their template, add features, modify styling, \
configure verticals, and build on top of their APAi deployment. Reference their \
specific configuration when giving advice."""


class DevPortalAI:
    """ANASTASiA terminal engine for APAi admin portal.

    No tool calling. Pure conversational AI with opsec-hardened system prompt.
    Branded as ANASTASiA — underlying model never exposed.
    """

    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model = "claude-opus-4-6"
        self.max_tokens = 4096
        self.logger = logging.getLogger(f"{__name__}.DevPortalAI")

    def chat(self, messages_history, user_message, apai_context=None):
        """
        Process a user message through the dev portal engine.

        Args:
            messages_history: List of prior message dicts [{role, content}, ...]
            user_message: The user's new message.
            apai_context: Optional dict with APAi template config for contextual help.

        Returns:
            dict: {role, content, model_used, response_time_ms, tokens_used}
            or None on failure.
        """
        start_time = time.time()

        # Build system prompt
        system = ANASTASIA_DEVPORTAL_SYSTEM_PROMPT
        today_str = datetime.now().strftime("%Y-%m-%d")
        system += f"\n\nToday's date is {today_str}."

        if apai_context:
            system += APAI_CONTEXT_TEMPLATE.format(
                config=apai_context.get("template_config", "No config available")
            )

        # Build messages array (ensure alternation starts with user)
        api_messages = []
        for msg in messages_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                api_messages.append({"role": role, "content": content})

        api_messages.append({"role": "user", "content": user_message})

        # Ensure first message is from user
        if api_messages and api_messages[0].get("role") != "user":
            api_messages.insert(0, {"role": "user", "content": "Hello."})

        # Call Anthropic Messages API
        result = self._call_anthropic(system, api_messages)

        elapsed_ms = int((time.time() - start_time) * 1000)

        if result is None:
            return {
                "role": "assistant",
                "content": "I'm sorry, I encountered an issue connecting to the AI service. Please try again in a moment.",
                "model_used": self.model,
                "response_time_ms": elapsed_ms,
                "tokens_used": 0,
            }

        # Extract text content from response
        content_blocks = result.get("content", [])
        text_parts = [
            block.get("text", "")
            for block in content_blocks
            if block.get("type") == "text"
        ]
        final_content = "\n".join(text_parts) if text_parts else ""

        # Extract token usage
        usage = result.get("usage", {})
        tokens_used = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

        return {
            "role": "assistant",
            "content": final_content,
            "model_used": result.get("model", self.model),
            "response_time_ms": elapsed_ms,
            "tokens_used": tokens_used,
        }

    def _call_anthropic(self, system_prompt, messages):
        """Call the Anthropic Messages API (raw HTTP, no SDK).

        Returns:
            Parsed JSON response dict, or None on failure.
        """
        api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            self.logger.error("ANTHROPIC_API_KEY not set")
            return None

        body = {
            "model": self.model,
            "system": system_prompt,
            "messages": messages,
            "max_tokens": self.max_tokens,
        }

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=body,
                timeout=120,  # Longer timeout for complex dev tasks
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            self.logger.error("Anthropic API call timed out")
            return None
        except requests.exceptions.HTTPError as e:
            self.logger.error(
                "Anthropic API HTTP error: %s — %s",
                e,
                getattr(e.response, 'text', '')[:500],
            )
            return None
        except Exception as e:
            self.logger.error("Anthropic API unexpected error: %s", e)
            return None
