"""
MYSTES AI Search Engine — Multi-Provider Ensemble + Private Market Escrow

Queries multiple LLM providers in parallel (Claude, Grok, DeepSeek, ChatGPT,
Gemini, Mistral, Cohere, HuggingFace, Ollama), ranks responses, and returns
the best combined answer. Also builds real-time XRPL escrow contracts for
private market transactions discovered through the proxy portal.

Architecture:
    User query → MystesAI.search() → ThreadPoolExecutor fans out to N providers
    → responses collected → ranked by relevance/specificity/agreement → best returned

BYOAI (Bring Your Own AI) — Two paths:
    1. Proxy Portal (primary): User logs into their own AI subscription (ChatGPT,
       Claude, etc.) through the proxy portal. Their AI sees market data from the
       proxy's geographic location. No API key needed — user's existing subscription
       handles billing. Mystes just provides the geographic tunnel.
    2. API Key (advanced): User adds their provider API key to Mystes's ensemble.
       Their provider is included in parallel queries. No Mystes credit cost.

Payment:
    Platform API keys: 0.001 RLUSD per query (free tier: 10/day)
    User's own API keys in ensemble: no Mystes credit cost
    User's own AI via proxy: no Mystes credit cost (proxy session cost only)
    Private market escrow: tiered fee 1.5-3% of transaction value

Usage:
    from ai_search import mystes_ai
    result = mystes_ai.search(user_id=1, query="cheapest flights Tokyo March", market="JP")
    deal = mystes_ai.build_deal_contract(user_id=1, deal_details={...})
"""

import hashlib
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import re
import requests

logger = logging.getLogger(__name__)


def _validate_xrpl_address(address):
    """Validate XRPL wallet address format.

    Basic check: starts with 'r', 25-35 Base58 characters.
    Uses xrpl-py is_classic_address() if available.
    """
    if not address or not isinstance(address, str):
        return False
    if not re.match(r'^r[1-9A-HJ-NP-Za-km-z]{24,34}$', address):
        return False
    try:
        from xrpl.core.addresscodec import is_classic_address
        return is_classic_address(address)
    except (ImportError, Exception):
        return True  # Pattern matched, library unavailable


# ---------------------------------------------------------------------------
# Provider Registry
# ---------------------------------------------------------------------------

AI_PROVIDERS = {
    "anthropic": {
        "name": "Claude (Anthropic)",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "env_key": "ANTHROPIC_API_KEY",
        "default_model": "claude-sonnet-4-20250514",
        "strengths": "Reasoning, analysis, safety, nuanced responses",
    },
    "openai": {
        "name": "ChatGPT (OpenAI)",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
        "strengths": "General knowledge, coding, creative, broad coverage",
    },
    "xai": {
        "name": "Grok (xAI)",
        "endpoint": "https://api.x.ai/v1/chat/completions",
        "env_key": "XAI_API_KEY",
        "default_model": "grok-3",
        "strengths": "Real-time knowledge, unfiltered, X/Twitter data",
    },
    "deepseek": {
        "name": "DeepSeek",
        "endpoint": "https://api.deepseek.com/v1/chat/completions",
        "env_key": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "strengths": "Deep reasoning, math, price analysis, cost-effective",
    },
    "google": {
        "name": "Gemini (Google)",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "env_key": "GOOGLE_AI_API_KEY",
        "default_model": "gemini-2.0-flash",
        "strengths": "Multimodal, Google knowledge, fast",
    },
    "mistral": {
        "name": "Mistral",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "env_key": "MISTRAL_API_KEY",
        "default_model": "mistral-large-latest",
        "strengths": "European markets, multilingual, efficient",
    },
    "cohere": {
        "name": "Cohere",
        "endpoint": "https://api.cohere.com/v2/chat",
        "env_key": "COHERE_API_KEY",
        "default_model": "command-r-plus",
        "strengths": "Search/RAG, enterprise, multilingual",
    },
    "huggingface": {
        "name": "HuggingFace Inference",
        "endpoint": "https://api-inference.huggingface.co/models/{model}",
        "env_key": "HUGGINGFACE_API_KEY",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct",
        "strengths": "Open-source models, variety, experimentation",
    },
    "ollama": {
        "name": "Ollama (Local)",
        "endpoint": "http://localhost:11434/api/chat",
        "env_key": None,
        "default_model": "llama3.3",
        "strengths": "Privacy, no API costs, offline capable, user-controlled",
    },
}

# ---------------------------------------------------------------------------
# System Prompts
# ---------------------------------------------------------------------------

SEARCH_PROMPT = (
    "You are MYSTES AI, a data-driven geographic market intelligence assistant. "
    "You have access to Mystes's proprietary cross-market pricing data, demand signals, "
    "and historical price trends gathered from proxy-based arbitrage across global markets. "
    "Use the market intelligence provided in your context to give precise, data-backed answers. "
    "Cite specific prices, savings percentages, and market comparisons from the data. "
    "Be concise and actionable — users want data, not disclaimers."
)

ANALYSIS_PROMPT = (
    "You are MYSTES AI analyzing a marketplace listing. "
    "Assess the item's fair market value, identify red flags, "
    "and compare pricing across markets. Be specific with numbers."
)

COMPARISON_PROMPT = (
    "You are MYSTES AI comparing prices across geographic markets. "
    "Calculate landed cost (price + shipping + customs duties + tax) for physical goods. "
    "Show the true delivered cost, not just sticker price."
)

DEAL_ASSESSMENT_PROMPT = (
    "You are MYSTES AI assessing a private market transaction. "
    "Evaluate the fair market value of the item described, "
    "identify risk factors (price vs market value, item category, cross-border complexity), "
    "and recommend escrow terms. Return a JSON object with: "
    "fair_value_estimate (number), risk_score (1-10), risk_factors (list of strings), "
    "recommended_escrow_days (number)."
)

# ---------------------------------------------------------------------------
# Credit costs
# ---------------------------------------------------------------------------

CREDIT_COST_PER_QUERY = float(os.environ.get("AI_CREDIT_COST", "0.001"))
FREE_QUERIES_PER_DAY = int(os.environ.get("AI_FREE_QUERIES_DAY", "10"))
PROVIDER_TIMEOUT = int(os.environ.get("AI_PROVIDER_TIMEOUT", "30"))

# ---------------------------------------------------------------------------
# Escrow fee tiers
# ---------------------------------------------------------------------------

ESCROW_FEE_TIERS = [
    (100, 0.03, 1.0),       # under $100: 3%, min $1
    (1000, 0.025, 2.50),    # $100-$1000: 2.5%
    (10000, 0.02, 25.0),    # $1000-$10000: 2%
    (float('inf'), 0.015, 150.0),  # $10000+: 1.5%
]
ESCROW_FEE_CAP = 500.0


# ---------------------------------------------------------------------------
# Encryption helpers (simple Fernet for API key storage)
# ---------------------------------------------------------------------------

def _get_encryption_key():
    """Get or generate encryption key for API key storage."""
    key = os.environ.get("MYSTES_ENCRYPTION_KEY")
    if key:
        return key.encode() if isinstance(key, str) else key
    # Fallback: derive from SECRET_KEY
    secret = os.environ.get("SECRET_KEY", "mystes-dev-key")
    import base64
    raw = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(raw)


def encrypt_api_key(plain_key):
    """Encrypt an API key for database storage."""
    try:
        from cryptography.fernet import Fernet
        f = Fernet(_get_encryption_key())
        return f.encrypt(plain_key.encode()).decode()
    except ImportError:
        # Fallback: base64 encode (not secure, but functional without cryptography)
        import base64
        return base64.b64encode(plain_key.encode()).decode()


def decrypt_api_key(encrypted_key):
    """Decrypt an API key from database storage."""
    try:
        from cryptography.fernet import Fernet
        f = Fernet(_get_encryption_key())
        return f.decrypt(encrypted_key.encode()).decode()
    except ImportError:
        import base64
        return base64.b64decode(encrypted_key.encode()).decode()


# ---------------------------------------------------------------------------
# MystesAI — Main Class
# ---------------------------------------------------------------------------

class MystesAI:
    """Multi-provider AI ensemble search engine + private market escrow builder."""

    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="mystes_ai")

    # ----- Provider Management -----

    def get_platform_providers(self):
        """Return providers configured with platform-level API keys (env vars)."""
        available = {}
        for key, info in AI_PROVIDERS.items():
            env_key = info.get("env_key")
            if env_key is None:
                # Ollama — check if reachable
                available[key] = {**info, "source": "platform"}
            elif os.environ.get(env_key):
                available[key] = {**info, "source": "platform"}
        return available

    def get_user_providers(self, user_id):
        """Return providers the user has added custom API keys for."""
        from models import UserAIProvider
        providers = UserAIProvider.query.filter_by(
            user_id=user_id, is_active=True
        ).all()
        result = {}
        for p in providers:
            base = AI_PROVIDERS.get(p.provider_key, {})
            result[p.provider_key] = {
                **base,
                "source": "user",
                "custom_model": p.custom_model,
                "custom_endpoint": p.custom_endpoint,
                "db_id": p.id,
            }
        return result

    def get_all_available(self, user_id):
        """Merged list: platform providers + user's custom providers."""
        providers = self.get_platform_providers()
        user_providers = self.get_user_providers(user_id)
        # User providers override platform for same key
        providers.update(user_providers)
        return providers

    def add_user_provider(self, user_id, provider_key, api_key=None, custom_model=None, custom_endpoint=None):
        """User onboards their own API key for a provider."""
        from models import UserAIProvider, db as appdb

        if provider_key not in AI_PROVIDERS:
            return {"error": f"Unknown provider: {provider_key}"}

        existing = UserAIProvider.query.filter_by(
            user_id=user_id, provider_key=provider_key
        ).first()

        encrypted = encrypt_api_key(api_key) if api_key else None

        if existing:
            if encrypted:
                existing.api_key_encrypted = encrypted
            if custom_model:
                existing.custom_model = custom_model
            if custom_endpoint:
                existing.custom_endpoint = custom_endpoint
            existing.is_active = True
        else:
            existing = UserAIProvider(
                user_id=user_id,
                provider_key=provider_key,
                api_key_encrypted=encrypted,
                custom_model=custom_model,
                custom_endpoint=custom_endpoint,
            )
            appdb.session.add(existing)

        appdb.session.commit()
        return existing.to_dict()

    def remove_user_provider(self, user_id, provider_key):
        """User removes their custom API key for a provider."""
        from models import UserAIProvider, db as appdb

        provider = UserAIProvider.query.filter_by(
            user_id=user_id, provider_key=provider_key
        ).first()
        if provider:
            provider.is_active = False
            provider.api_key_encrypted = None
            appdb.session.commit()
            return True
        return False

    def test_provider(self, provider_key, api_key=None):
        """Verify an API key works by sending a simple test query."""
        try:
            result = self._call_provider(
                provider_key,
                [{"role": "user", "content": "Say hello in one word."}],
                api_key=api_key,
            )
            return {"ok": True, "response": result.get("response", "")[:100]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ----- Ensemble Search -----

    def search(self, user_id, query, market=None, providers=None, mode="ensemble"):
        """Main entry point: query multiple AI providers, rank, return best."""
        start_time = time.time()

        # Check credits / free tier
        credit_check = self._check_credits(user_id)
        if credit_check.get("error"):
            return credit_check

        uses_own_keys = False

        # Get available providers
        if providers:
            available = {k: AI_PROVIDERS.get(k, {}) for k in providers if k in AI_PROVIDERS}
        else:
            available = self.get_all_available(user_id)

        if not available:
            return {"error": "No AI providers available. Add API keys or contact admin."}

        # Check if user is only using their own keys
        user_providers = self.get_user_providers(user_id)
        if all(k in user_providers for k in available):
            uses_own_keys = True

        # Build messages with Mystes intelligence context
        system_content = SEARCH_PROMPT
        try:
            from mystes_intelligence import intelligence
            mystes_context = intelligence.build_ai_context(query, market=market)
            if mystes_context:
                system_content += f"\n\n{mystes_context}"
        except Exception as e:
            logger.warning(f"Intelligence context failed (non-blocking): {e}")
            if market:
                market_ctx = self._build_market_context(market)
                system_content += f"\n\nMarket context: {market_ctx}"

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": query},
        ]

        # Query all providers in parallel
        futures = {}
        for pkey, pinfo in available.items():
            api_key = self._get_api_key(user_id, pkey, pinfo)
            future = self._executor.submit(
                self._call_provider, pkey, messages, api_key=api_key, provider_info=pinfo
            )
            futures[future] = pkey

        responses = []
        for future in as_completed(futures, timeout=PROVIDER_TIMEOUT + 5):
            pkey = futures[future]
            try:
                result = future.result(timeout=1)
                if result and result.get("response"):
                    responses.append(result)
            except Exception as e:
                logger.warning(f"Provider {pkey} failed: {e}")

        if not responses:
            return {"error": "All providers failed. Try again later."}

        # Rank responses
        ranked = self._rank_responses(query, responses)
        best = ranked[0]

        total_time_ms = int((time.time() - start_time) * 1000)
        total_tokens = sum(r.get("tokens_used", 0) for r in responses)

        # Deduct credits (skip if user uses only their own keys)
        credits_used = 0.0
        if not uses_own_keys:
            credits_used = CREDIT_COST_PER_QUERY
            self._deduct_credits(user_id, credits_used)

        # Record query
        self._record_query(
            user_id=user_id,
            query_text=query,
            market=market,
            providers_queried=list(available.keys()),
            best=best,
            all_responses=ranked,
            total_tokens=total_tokens,
            response_time_ms=total_time_ms,
            credits_used=credits_used,
        )

        # Strategy observation hook (Build #73)
        try:
            from strategy_learner import strategy_learner
            strategy_learner.record_observation(
                source_type='byoai' if uses_own_keys else 'ensemble',
                provider_key=best.get("provider"),
                query_category=self._classify_query_category(query),
                query_params={'query': query, 'market': market},
                results=best,
                response_time_ms=total_time_ms,
            )
        except Exception:
            pass  # Never block search on learner failure

        return {
            "best_response": best.get("response"),
            "best_provider": best.get("provider"),
            "best_model": best.get("model"),
            "all_responses": [
                {
                    "provider": r["provider"],
                    "model": r.get("model"),
                    "response": r["response"],
                    "time_ms": r.get("time_ms", 0),
                    "score": r.get("_score", 0),
                }
                for r in ranked
            ],
            "market": market,
            "total_tokens": total_tokens,
            "response_time_ms": total_time_ms,
            "credits_used": credits_used,
            "providers_queried": len(available),
            "providers_responded": len(responses),
        }

    def _rank_responses(self, query, responses):
        """Score and rank provider responses."""
        query_words = set(query.lower().split())

        for r in responses:
            text = r.get("response", "")
            score = 0.0

            # Completeness: 100-2000 chars optimal
            length = len(text)
            if 100 <= length <= 2000:
                score += 20
            elif length > 2000:
                score += 15
            elif length > 50:
                score += 10

            # Relevance: query keyword overlap
            text_lower = text.lower()
            overlap = sum(1 for w in query_words if w in text_lower and len(w) > 2)
            score += min(overlap * 5, 25)

            # Specificity: contains prices, numbers, URLs
            import re
            numbers = len(re.findall(r'\$[\d,.]+|\d+\.\d{2}|¥[\d,.]+|€[\d,.]+|£[\d,.]+', text))
            urls = len(re.findall(r'https?://\S+', text))
            score += min(numbers * 5, 15)
            score += min(urls * 3, 9)

            # Confidence: absence of hedging phrases
            hedges = ["i'm not sure", "i cannot", "i don't have", "as an ai", "i apologize",
                       "i'm unable", "unfortunately"]
            hedge_count = sum(1 for h in hedges if h in text_lower)
            score -= hedge_count * 5

            # Speed bonus
            time_ms = r.get("time_ms", 30000)
            if time_ms < 3000:
                score += 5
            elif time_ms < 10000:
                score += 2

            r["_score"] = round(score, 1)

        # Agreement signal: if 3+ responses, boost those that agree with majority
        if len(responses) >= 3:
            all_texts = [r.get("response", "").lower() for r in responses]
            for i, r in enumerate(responses):
                agreements = 0
                my_words = set(all_texts[i].split())
                for j, other_text in enumerate(all_texts):
                    if i == j:
                        continue
                    other_words = set(other_text.split())
                    shared = len(my_words & other_words)
                    if shared > min(len(my_words), len(other_words)) * 0.3:
                        agreements += 1
                r["_score"] += agreements * 3

        responses.sort(key=lambda r: r.get("_score", 0), reverse=True)
        return responses

    # ----- Provider API Calls -----

    def _get_api_key(self, user_id, provider_key, provider_info):
        """Get API key: user's custom key first, then platform env var."""
        from models import UserAIProvider
        user_prov = UserAIProvider.query.filter_by(
            user_id=user_id, provider_key=provider_key, is_active=True
        ).first()
        if user_prov and user_prov.api_key_encrypted:
            return decrypt_api_key(user_prov.api_key_encrypted)

        env_key = provider_info.get("env_key") or AI_PROVIDERS.get(provider_key, {}).get("env_key")
        if env_key:
            return os.environ.get(env_key)
        return None

    def _call_provider(self, provider_key, messages, api_key=None, provider_info=None):
        """Route to the correct provider API implementation."""
        info = provider_info or AI_PROVIDERS.get(provider_key, {})
        model = (info.get("custom_model") or info.get("default_model", ""))
        endpoint = info.get("custom_endpoint") or info.get("endpoint", "")

        start = time.time()
        result = None

        if provider_key == "anthropic":
            result = self._call_anthropic(messages, api_key, model)
        elif provider_key in ("openai", "xai", "deepseek", "mistral"):
            result = self._call_openai_compat(messages, api_key, model, endpoint)
        elif provider_key == "google":
            result = self._call_google(messages, api_key, model)
        elif provider_key == "cohere":
            result = self._call_cohere(messages, api_key, model)
        elif provider_key == "huggingface":
            result = self._call_huggingface(messages, api_key, model)
        elif provider_key == "ollama":
            result = self._call_ollama(messages, model, endpoint)
        else:
            # Try OpenAI-compatible as default
            if api_key and endpoint:
                result = self._call_openai_compat(messages, api_key, model, endpoint)

        if result:
            result["time_ms"] = int((time.time() - start) * 1000)
            result["provider"] = provider_key
        return result

    def _call_anthropic(self, messages, api_key, model):
        """Call Anthropic Messages API."""
        if not api_key:
            return None
        system_msg = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                user_messages.append(m)

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 2048,
                "system": system_msg,
                "messages": user_messages,
            },
            timeout=PROVIDER_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block["text"]
        return {
            "response": text,
            "model": model,
            "tokens_used": data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get("output_tokens", 0),
        }

    def _call_openai_compat(self, messages, api_key, model, endpoint):
        """Call OpenAI-compatible API (OpenAI, xAI/Grok, DeepSeek, Mistral)."""
        if not api_key:
            return None
        resp = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": 2048,
            },
            timeout=PROVIDER_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        return {
            "response": choice.get("message", {}).get("content", ""),
            "model": model,
            "tokens_used": data.get("usage", {}).get("total_tokens", 0),
        }

    def _call_google(self, messages, api_key, model):
        """Call Google Generative AI REST API."""
        if not api_key:
            return None
        # Build Gemini-format contents
        contents = []
        system_instruction = None
        for m in messages:
            if m["role"] == "system":
                system_instruction = m["content"]
            else:
                role = "user" if m["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        body = {"contents": contents}
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        resp = requests.post(url, json=body, timeout=PROVIDER_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        text = ""
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                text += part.get("text", "")
        tokens = data.get("usageMetadata", {})
        return {
            "response": text,
            "model": model,
            "tokens_used": tokens.get("totalTokenCount", 0),
        }

    def _call_cohere(self, messages, api_key, model):
        """Call Cohere v2 chat API."""
        if not api_key:
            return None
        resp = requests.post(
            "https://api.cohere.com/v2/chat",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
            },
            timeout=PROVIDER_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        text = ""
        msg = data.get("message", {})
        for block in msg.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
        tokens = data.get("usage", {})
        return {
            "response": text,
            "model": model,
            "tokens_used": tokens.get("billed_units", {}).get("input_tokens", 0) +
                           tokens.get("billed_units", {}).get("output_tokens", 0),
        }

    def _call_huggingface(self, messages, api_key, model):
        """Call HuggingFace Inference API."""
        if not api_key:
            return None
        url = f"https://api-inference.huggingface.co/models/{model}/v1/chat/completions"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": 2048},
            timeout=PROVIDER_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        return {
            "response": choice.get("message", {}).get("content", ""),
            "model": model,
            "tokens_used": data.get("usage", {}).get("total_tokens", 0),
        }

    def _call_ollama(self, messages, model, endpoint=None):
        """Call local Ollama API (no API key needed)."""
        url = endpoint or "http://localhost:11434/api/chat"
        try:
            resp = requests.post(
                url,
                json={"model": model, "messages": messages, "stream": False},
                timeout=PROVIDER_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "response": data.get("message", {}).get("content", ""),
                "model": model,
                "tokens_used": data.get("eval_count", 0) + data.get("prompt_eval_count", 0),
            }
        except requests.ConnectionError:
            logger.debug("Ollama not available (connection refused)")
            return None

    # ----- Credit System -----

    def _check_credits(self, user_id):
        """Check if user has credits or free queries remaining."""
        from models import AISearchQuery, db as appdb
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = AISearchQuery.query.filter(
            AISearchQuery.user_id == user_id,
            AISearchQuery.created_at >= today_start,
        ).count()

        if today_count < FREE_QUERIES_PER_DAY:
            return {"ok": True, "free_remaining": FREE_QUERIES_PER_DAY - today_count}

        # Check RLUSD balance
        balance = self.get_user_credits(user_id)
        if balance < CREDIT_COST_PER_QUERY:
            return {
                "error": "Insufficient AI credits. Deposit RLUSD to your wallet or add your own API keys.",
                "balance": balance,
                "cost_per_query": CREDIT_COST_PER_QUERY,
            }
        return {"ok": True, "balance": balance}

    def get_user_credits(self, user_id):
        """Check user's RLUSD balance available for AI queries."""
        from models import UserWallet
        wallet = UserWallet.query.filter_by(user_id=user_id, currency='RLUSD').first()
        if not wallet:
            return 0.0
        return float(wallet.balance or 0)

    def _deduct_credits(self, user_id, amount):
        """Deduct RLUSD credits after a successful query."""
        from models import UserWallet, db as appdb
        wallet = UserWallet.query.filter_by(user_id=user_id, currency='RLUSD').first()
        if wallet and wallet.balance >= amount:
            wallet.balance -= amount
            appdb.session.commit()
            return True
        return False

    def _record_query(self, user_id, query_text, market, providers_queried,
                      best, all_responses, total_tokens, response_time_ms, credits_used):
        """Record a completed AI search query."""
        from models import AISearchQuery, db as appdb
        record = AISearchQuery(
            user_id=user_id,
            query_text=query_text,
            market=market,
            providers_queried=json.dumps(providers_queried),
            best_provider=best.get("provider"),
            best_model=best.get("model"),
            best_response=best.get("response"),
            all_responses=json.dumps([
                {"provider": r["provider"], "model": r.get("model"), "response": r["response"],
                 "time_ms": r.get("time_ms", 0)}
                for r in all_responses
            ]),
            total_tokens=total_tokens,
            response_time_ms=response_time_ms,
            credits_used=credits_used,
        )
        appdb.session.add(record)
        appdb.session.commit()
        return record

    # ----- Query Classification (Build #73) -----

    def _classify_query_category(self, query):
        """Classify a search query into a category for strategy learning."""
        q = query.lower()
        if any(w in q for w in ['flight', 'fly', 'airline', 'airport', 'jfk', 'lhr', 'nrt', 'lax']):
            return 'flights'
        if any(w in q for w in ['hotel', 'stay', 'accommodation', 'booking', 'resort', 'hostel']):
            return 'hotels'
        if any(w in q for w in ['product', 'buy', 'shop', 'price', 'amazon', 'ebay', 'purchase']):
            return 'products'
        if any(w in q for w in ['cruise', 'ship', 'sailing', 'voyage']):
            return 'cruises'
        return 'general'

    # ----- Market Context -----

    def _build_market_context(self, market):
        """Build geographic market context for system prompts."""
        try:
            from proxy_portal import COUNTRY_INFO, PORTAL_APP_DIRECTORY
            country = COUNTRY_INFO.get(market, {})
            name = country.get("name", market)

            # Gather relevant marketplace names for this market
            sites = []
            for cat_key, cat in PORTAL_APP_DIRECTORY.items():
                for site in cat.get("sites", []):
                    regions = site.get("regions", [])
                    if "*" in regions or market in regions:
                        sites.append(site["name"])

            return (
                f"Geographic market: {name} ({market}). "
                f"Available platforms: {', '.join(sites[:15])}. "
                f"Search results should be relevant to this geographic region."
            )
        except Exception:
            return f"Geographic market: {market}"

    # ----- Private Market Deal Escrow -----

    def calculate_escrow_fee(self, amount):
        """Calculate tiered escrow fee for a private market transaction."""
        for threshold, rate, minimum in ESCROW_FEE_TIERS:
            if amount < threshold:
                fee = max(amount * rate, minimum)
                return min(fee, ESCROW_FEE_CAP)
        return min(amount * 0.015, ESCROW_FEE_CAP)

    def assess_fair_value(self, item_description, market=None):
        """Query AI ensemble to estimate fair market value of an item."""
        query = f"What is the fair market value of: {item_description}"
        if market:
            from proxy_portal import COUNTRY_INFO
            country_name = COUNTRY_INFO.get(market, {}).get("name", market)
            query += f" in {country_name}"
        query += "? Respond with ONLY a JSON object: {\"fair_value_usd\": number, \"confidence\": \"high\"|\"medium\"|\"low\", \"reasoning\": \"string\"}"

        # Use a single reliable provider for assessment (prefer anthropic > openai > any)
        platform = self.get_platform_providers()
        provider_preference = ["anthropic", "openai", "deepseek", "google"]
        api_key = None
        chosen = None
        for p in provider_preference:
            if p in platform:
                env_key = AI_PROVIDERS[p].get("env_key")
                if env_key:
                    api_key = os.environ.get(env_key)
                    if api_key:
                        chosen = p
                        break

        if not chosen:
            return {"fair_value_usd": None, "confidence": "low", "reasoning": "No AI provider available for assessment"}

        messages = [
            {"role": "system", "content": DEAL_ASSESSMENT_PROMPT},
            {"role": "user", "content": query},
        ]
        try:
            result = self._call_provider(chosen, messages, api_key=api_key)
            if result and result.get("response"):
                # Try to parse JSON from response
                text = result["response"]
                # Extract JSON if wrapped in markdown
                if "```" in text:
                    import re
                    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
                    if json_match:
                        text = json_match.group(1)
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"fair_value_usd": None, "confidence": "low", "reasoning": text[:500]}
        except Exception as e:
            logger.error(f"Fair value assessment failed: {e}")

        return {"fair_value_usd": None, "confidence": "low", "reasoning": "Assessment failed"}

    def build_deal_contract(self, user_id, deal_details):
        """AI analyzes deal parameters and generates XRPL escrow terms."""
        item = deal_details.get("item_description", "")
        price = float(deal_details.get("agreed_price", 0))
        market = deal_details.get("market")
        deal_type = deal_details.get("deal_type", "goods")
        deadline_days = int(deal_details.get("deadline_days", 14))

        # Calculate fee
        fee = self.calculate_escrow_fee(price)

        # AI fair value assessment
        assessment = self.assess_fair_value(item, market)
        fair_value = assessment.get("fair_value_usd")

        # Calculate risk score
        risk_score = 5  # baseline
        risk_factors = []

        if fair_value and price > fair_value * 1.5:
            risk_score += 2
            risk_factors.append(f"Price ({price}) significantly above fair value estimate ({fair_value})")
        if price > 5000:
            risk_score += 1
            risk_factors.append("High-value transaction")
        if deal_type == "vehicle":
            risk_score += 1
            risk_factors.append("Vehicle transactions carry higher complexity")
        if market and market not in ("US", "GB", "CA", "AU"):
            risk_score += 1
            risk_factors.append("Cross-border transaction with non-standard market")

        risk_score = min(risk_score, 10)

        # Build XRPL escrow parameters
        now = datetime.utcnow()
        finish_after = now + timedelta(hours=1)  # Escrow can be finished 1 hour after creation
        cancel_after = now + timedelta(days=deadline_days + 7)  # 7-day dispute window after deadline

        # Generate condition/fulfillment pair for crypto-conditional escrow
        import secrets
        fulfillment_bytes = secrets.token_bytes(32)
        condition_hash = hashlib.sha256(fulfillment_bytes).digest()
        import base64
        fulfillment_hex = fulfillment_bytes.hex()
        condition_hex = condition_hash.hex()

        return {
            "escrow_terms": {
                "item": item,
                "price_rlusd": price,
                "fee_rlusd": round(fee, 4),
                "total_rlusd": round(price + fee, 4),
                "deal_type": deal_type,
                "delivery_deadline_days": deadline_days,
                "dispute_window_days": 7,
            },
            "risk_assessment": {
                "score": risk_score,
                "factors": risk_factors,
                "fair_value_estimate": fair_value,
                "assessment_confidence": assessment.get("confidence", "low"),
            },
            "xrpl_escrow_params": {
                "amount_drops": str(int(price * 1_000_000)),  # RLUSD in drops
                "fee_drops": str(int(fee * 1_000_000)),
                "finish_after": finish_after.isoformat(),
                "cancel_after": cancel_after.isoformat(),
                "condition": condition_hex,
                "fulfillment": fulfillment_hex,
            },
            "estimated_fees": {
                "escrow_fee": round(fee, 4),
                "xrpl_tx_fee": 0.000012,  # ~12 drops
                "total_fee": round(fee + 0.000012, 6),
            },
        }

    def create_private_deal(self, user_id, deal_details, contract):
        """Create a PrivateMarketDeal record from a built contract.

        seller_wallet is optional — for link-based deals, seller provides
        their wallet when they accept the shareable link.
        """
        from models import PrivateMarketDeal, db as appdb

        seller_wallet = deal_details.get("seller_wallet") or None

        deal = PrivateMarketDeal(
            buyer_id=user_id,
            seller_wallet=seller_wallet,
            item_description=deal_details.get("item_description", ""),
            agreed_price_rlusd=float(deal_details.get("agreed_price", 0)),
            market=deal_details.get("market"),
            deal_type=deal_details.get("deal_type", "goods"),
            escrow_fee_rlusd=contract["escrow_terms"]["fee_rlusd"],
            escrow_condition=contract["xrpl_escrow_params"]["condition"],
            escrow_fulfillment=contract["xrpl_escrow_params"]["fulfillment"],
            ai_fair_value_estimate=contract["risk_assessment"].get("fair_value_estimate"),
            risk_score=contract["risk_assessment"]["score"],
            status="draft",
            delivery_deadline=datetime.utcnow() + timedelta(
                days=contract["escrow_terms"]["delivery_deadline_days"]
            ),
            dispute_window_end=datetime.utcnow() + timedelta(
                days=contract["escrow_terms"]["delivery_deadline_days"] + 7
            ),
            seller_email=deal_details.get("seller_email"),
            seller_name=deal_details.get("seller_name"),
        )
        appdb.session.add(deal)
        appdb.session.commit()
        return deal

    def fund_deal_escrow(self, deal_id, user_id):
        """Fund an XRPL escrow for a private market deal. Returns tx hash.

        Accepts deals in 'draft' (direct wallet) or 'seller_accepted' (link-based) status.
        """
        from models import PrivateMarketDeal, db as appdb

        deal = PrivateMarketDeal.query.filter_by(id=deal_id, buyer_id=user_id).filter(
            PrivateMarketDeal.status.in_(["draft", "seller_accepted"])
        ).first()
        if not deal:
            return {"error": "Deal not found or not ready for funding"}

        if not deal.seller_wallet:
            return {"error": "Seller has not provided a wallet address yet"}

        # Build XRPL EscrowCreate transaction
        try:
            from xrpl.models.transactions import EscrowCreate
            from xrpl.models.amounts import IssuedCurrencyAmount
            from xrpl.utils import datetime_to_ripple_time
            import xrpl

            wallet_seed = os.environ.get("MYSTES_XRPL_SEED")
            if not wallet_seed:
                return {"error": "XRPL wallet not configured"}

            wallet = xrpl.wallet.Wallet.from_seed(wallet_seed)
            client_url = os.environ.get("XRPL_NODE_URL", "wss://s1.ripple.com")

            amount = IssuedCurrencyAmount(
                currency="RLUSD",
                issuer=os.environ.get("RLUSD_ISSUER", ""),
                value=str(deal.agreed_price_rlusd),
            )

            escrow_tx = EscrowCreate(
                account=wallet.address,
                amount=amount,
                destination=deal.seller_wallet,
                finish_after=datetime_to_ripple_time(datetime.utcnow() + timedelta(hours=1)),
                cancel_after=datetime_to_ripple_time(deal.dispute_window_end),
            )

            # Submit transaction
            from xrpl.clients import WebsocketClient
            with WebsocketClient(client_url) as client:
                response = xrpl.transaction.submit_and_wait(escrow_tx, client, wallet)

            if response.is_successful():
                deal.escrow_tx_hash = response.result.get("hash", "")
                deal.escrow_sequence = response.result.get("Sequence")
                deal.status = "escrow_funded"
                appdb.session.commit()

                logger.info(f"Escrow funded for deal {deal_id}: {deal.escrow_tx_hash}")
                return {"ok": True, "tx_hash": deal.escrow_tx_hash, "deal": deal.to_dict()}
            else:
                return {"error": f"XRPL transaction failed: {response.result.get('engine_result_message', 'Unknown')}"}

        except ImportError:
            return {"error": "XRPL library not available"}
        except Exception as e:
            logger.error(f"Escrow funding failed for deal {deal_id}: {e}")
            return {"error": str(e)}

    def confirm_delivery(self, deal_id, user_id):
        """Buyer confirms delivery — submits EscrowFinish to XRPL to release funds."""
        from models import PrivateMarketDeal, db as appdb

        deal = PrivateMarketDeal.query.filter_by(
            id=deal_id, buyer_id=user_id, status="escrow_funded"
        ).first()
        if not deal:
            return {"error": "Deal not found or not in escrow_funded status"}

        if not deal.escrow_tx_hash or not deal.escrow_fulfillment:
            return {"error": "Escrow not properly funded — missing tx hash or fulfillment"}

        try:
            from xrpl.models.transactions import EscrowFinish
            import xrpl

            wallet_seed = os.environ.get("MYSTES_XRPL_SEED")
            if not wallet_seed:
                return {"error": "XRPL wallet not configured"}

            wallet = xrpl.wallet.Wallet.from_seed(wallet_seed)
            client_url = os.environ.get("XRPL_NODE_URL", "wss://s1.ripple.com")

            finish_tx = EscrowFinish(
                account=wallet.address,
                owner=wallet.address,
                offer_sequence=deal.escrow_sequence,
                condition=deal.escrow_condition,
                fulfillment=deal.escrow_fulfillment,
            )

            from xrpl.clients import WebsocketClient
            with WebsocketClient(client_url) as client:
                response = xrpl.transaction.submit_and_wait(finish_tx, client, wallet)

            if response.is_successful():
                deal.status = "completed"
                deal.completed_at = datetime.utcnow()
                appdb.session.commit()
                logger.info(f"Deal {deal_id} completed — EscrowFinish tx: {response.result.get('hash')}")
                return {"ok": True, "tx_hash": response.result.get("hash"), "deal": deal.to_dict()}
            else:
                return {"error": f"EscrowFinish failed: {response.result.get('engine_result_message', 'Unknown')}"}

        except ImportError:
            # Fallback: mark completed in DB if xrpl lib unavailable
            deal.status = "completed"
            deal.completed_at = datetime.utcnow()
            appdb.session.commit()
            logger.warning(f"Deal {deal_id} marked completed (XRPL lib unavailable)")
            return {"ok": True, "deal": deal.to_dict()}
        except Exception as e:
            logger.error(f"EscrowFinish failed for deal {deal_id}: {e}")
            return {"error": str(e)}

    def dispute_deal(self, deal_id, user_id, reason=""):
        """Open a dispute on a funded deal — escrow holds."""
        from models import PrivateMarketDeal, db as appdb

        deal = PrivateMarketDeal.query.filter_by(
            id=deal_id, buyer_id=user_id, status="escrow_funded"
        ).first()
        if not deal:
            return {"error": "Deal not found or not in escrow_funded status"}

        deal.status = "disputed"
        appdb.session.commit()

        logger.info(f"Deal {deal_id} disputed by user {user_id}: {reason}")
        return {"ok": True, "deal": deal.to_dict()}

    # ------------------------------------------------------------------
    # Private P2P Deal Links — shareable escrow for foreign marketplace txns
    # ------------------------------------------------------------------

    def generate_deal_link(self, deal_id, user_id, expiration_days=7):
        """Generate a shareable link for a private market deal.

        Only ONE link can be active per deal. Generating a new link revokes
        the previous one (old token becomes invalid). This forces the buyer
        to re-verify with the seller if sent to the wrong person.
        """
        import secrets
        from models import PrivateMarketDeal, db as appdb

        deal = PrivateMarketDeal.query.filter_by(id=deal_id, buyer_id=user_id).first()
        if not deal:
            return {"error": "Deal not found or access denied"}

        if deal.status not in ("draft", "link_sent", "seller_accepted"):
            return {"error": f"Cannot generate link for deal in status: {deal.status}"}

        # Revoke previous link — reset seller fields so new recipient starts fresh
        deal.link_token = secrets.token_urlsafe(32)
        deal.link_expires_at = datetime.utcnow() + timedelta(days=expiration_days)
        deal.link_viewed_at = None
        deal.seller_accepted_at = None
        deal.seller_wallet = None
        deal.seller_name = None
        deal.status = "link_sent"
        appdb.session.commit()

        try:
            from event_stream import emit_deal_event
            emit_deal_event("deal_link_generated", {
                "deal_id": deal.id,
                "expires_at": deal.link_expires_at.isoformat(),
            }, user_id=user_id)
        except Exception:
            pass

        base_url = os.environ.get("BASE_URL", "http://localhost:5001")

        # Generate multi-platform share links
        try:
            from share_links import generate_deal_share_links
            share = generate_deal_share_links(deal.to_dict(), base_url)
        except Exception:
            share = None

        return {
            "ok": True,
            "link_token": deal.link_token,
            "link_url": f"/deal/link/{deal.link_token}",
            "full_url": f"{base_url}/deal/link/{deal.link_token}",
            "expires_at": deal.link_expires_at.isoformat(),
            "deal": deal.to_dict(),
            "share_links": share,
        }

    def send_deal_link_email(self, deal_id, user_id):
        """Send deal link to seller via email using existing email_service."""
        from models import PrivateMarketDeal, User

        deal = PrivateMarketDeal.query.filter_by(id=deal_id, buyer_id=user_id).first()
        if not deal:
            return {"error": "Deal not found or access denied"}

        if not deal.link_token:
            return {"error": "Deal link not generated — call generate_deal_link first"}
        if not deal.seller_email:
            return {"error": "No seller email on this deal"}

        buyer = User.query.get(user_id)
        base_url = os.environ.get("BASE_URL", "http://localhost:5001")
        link_url = f"{base_url}/deal/link/{deal.link_token}"
        expires_str = deal.link_expires_at.strftime('%B %d, %Y at %I:%M %p UTC') if deal.link_expires_at else 'N/A'

        html_content = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #4361ee;">You've Received a Deal Proposal</h2>
            <p>Hi {deal.seller_name or 'there'},</p>
            <p><strong>{buyer.name or buyer.email}</strong> has proposed a transaction through
            MYSTES and would like to use XRPL escrow for secure payment.</p>

            <div style="background: #f0f4ff; padding: 20px; border-radius: 8px; margin: 20px 0;
                        border-left: 4px solid #4361ee;">
                <h3 style="margin-top: 0;">Deal Details</h3>
                <p><strong>Item:</strong> {deal.item_description}</p>
                <p><strong>Price:</strong> {deal.agreed_price_rlusd:.2f} RLUSD</p>
                <p><strong>Platform Fee:</strong> {deal.escrow_fee_rlusd:.2f} RLUSD</p>
                <p><strong>Type:</strong> {deal.deal_type}</p>
            </div>

            <h3>How It Works</h3>
            <ol>
                <li>Click the link below to review the deal terms</li>
                <li>Provide your XRPL wallet address to receive payment</li>
                <li>Accept the deal</li>
                <li>The buyer creates an on-chain escrow with the funds</li>
                <li>Complete the transaction (deliver the item/service)</li>
                <li>Escrow releases payment to your wallet automatically</li>
            </ol>

            <a href="{link_url}"
               style="display: inline-block; background: #4361ee; color: white; padding: 15px 30px;
                      text-decoration: none; border-radius: 8px; font-weight: bold; margin: 20px 0;">
                Review Deal Terms
            </a>

            <p style="color: #666; font-size: 14px;">This link expires on {expires_str}</p>

            <div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px;
                        border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0; color: #856404; font-size: 13px;">
                    MYSTES uses XRPL (XRP Ledger) smart contract escrow for secure, trustless
                    transactions. Funds are locked on-chain and only release when both parties
                    fulfill the agreement. Mystes is NOT liable for physical goods execution.
                </p>
            </div>
        </div>
        """

        try:
            from email_service import send_email
            result = send_email(
                to_email=deal.seller_email,
                subject=f"Deal Proposal: {deal.item_description[:50]}",
                html_content=html_content,
            )
            if result:
                logger.info(f"Deal link email sent to {deal.seller_email} for deal {deal_id}")
                return {"ok": True, "message": "Email sent successfully"}
            else:
                return {"error": "Email service returned failure"}
        except Exception as e:
            logger.error(f"Failed to send deal link email: {e}")
            return {"error": f"Failed to send email: {e}"}

    def get_deal_by_link_token(self, link_token):
        """Retrieve a deal by its public link token (no auth required).

        Returns sanitised deal info safe for public display.
        """
        from models import PrivateMarketDeal, User

        deal = PrivateMarketDeal.query.filter_by(link_token=link_token).first()
        if not deal:
            return {"error": "Deal not found"}

        if deal.link_expires_at and deal.link_expires_at < datetime.utcnow():
            return {"error": "This deal link has expired", "expired": True}

        if deal.status not in ("link_sent", "seller_accepted"):
            return {"error": "This deal is no longer available"}

        buyer = User.query.get(deal.buyer_id)

        return {
            "ok": True,
            "deal": {
                "id": deal.id,
                "item_description": deal.item_description,
                "agreed_price_rlusd": deal.agreed_price_rlusd,
                "escrow_fee_rlusd": deal.escrow_fee_rlusd,
                "total_rlusd": deal.agreed_price_rlusd + deal.escrow_fee_rlusd,
                "market": deal.market,
                "deal_type": deal.deal_type,
                "delivery_deadline_days": (deal.delivery_deadline - datetime.utcnow()).days if deal.delivery_deadline else None,
                "buyer_name": buyer.name if buyer and buyer.name else "MYSTES User",
                "status": deal.status,
                "seller_accepted_at": deal.seller_accepted_at.isoformat() if deal.seller_accepted_at else None,
                "link_expires_at": deal.link_expires_at.isoformat() if deal.link_expires_at else None,
            },
        }

    def accept_deal_link(self, link_token, seller_wallet, seller_name=None):
        """Seller accepts a deal via the public link and provides XRPL wallet.

        No authentication required — the link token IS the auth.
        """
        from models import PrivateMarketDeal, db as appdb

        if not _validate_xrpl_address(seller_wallet):
            return {"error": "Invalid XRPL wallet address format. Must start with 'r' and be 25-35 characters."}

        deal = PrivateMarketDeal.query.filter_by(link_token=link_token).first()
        if not deal:
            return {"error": "Deal not found"}

        if deal.link_expires_at and deal.link_expires_at < datetime.utcnow():
            deal.status = "expired"
            appdb.session.commit()
            return {"error": "This deal link has expired"}

        if deal.status not in ("link_sent",):
            if deal.status == "seller_accepted":
                return {"error": "This deal has already been accepted"}
            return {"error": f"Cannot accept deal in status: {deal.status}"}

        deal.seller_wallet = seller_wallet
        if seller_name:
            deal.seller_name = seller_name
        deal.seller_accepted_at = datetime.utcnow()
        deal.status = "seller_accepted"
        appdb.session.commit()

        try:
            from event_stream import emit_deal_event
            emit_deal_event("deal_seller_accepted", {
                "deal_id": deal.id,
                "seller_wallet": seller_wallet,
            }, user_id=deal.buyer_id)
        except Exception:
            pass

        logger.info(f"Deal {deal.id} accepted by seller {seller_wallet}")
        return {
            "ok": True,
            "deal": deal.to_dict(),
            "message": "Deal accepted. The buyer will now fund the escrow.",
        }

    def mark_deal_link_viewed(self, link_token):
        """Record when seller first views the deal link (analytics)."""
        from models import PrivateMarketDeal, db as appdb

        deal = PrivateMarketDeal.query.filter_by(link_token=link_token).first()
        if deal and not deal.link_viewed_at:
            deal.link_viewed_at = datetime.utcnow()
            appdb.session.commit()

            try:
                from event_stream import emit_deal_event
                emit_deal_event("deal_link_viewed", {
                    "deal_id": deal.id,
                    "viewed_at": deal.link_viewed_at.isoformat(),
                }, user_id=deal.buyer_id)
            except Exception:
                pass

    def cleanup_expired_deal_links(self):
        """Mark expired deal links as 'expired' status. Called by periodic task."""
        from models import PrivateMarketDeal, db as appdb

        expired = PrivateMarketDeal.query.filter(
            PrivateMarketDeal.status == "link_sent",
            PrivateMarketDeal.link_expires_at < datetime.utcnow()
        ).all()

        for deal in expired:
            deal.status = "expired"

        if expired:
            appdb.session.commit()
            logger.info(f"Marked {len(expired)} deal links as expired")

        return len(expired)

    # ------------------------------------------------------------------
    # Data-aware search (flight data + AI analysis)
    # ------------------------------------------------------------------

    def search_with_data(self, user_id, query, origin=None, destination=None,
                         departure_date=None, market=None):
        """
        Combined search: pull real flight prices then ask AI to analyse them
        with full Mystes intelligence context.
        """
        flights_context = ""
        flights = []

        # Try to fetch actual flight data if route info available
        if origin and destination and departure_date:
            try:
                from amadeus_client import AmadeusClient
                client = AmadeusClient()
                result = client.search_flights(origin, destination, departure_date)
                if result and isinstance(result, list):
                    flights = result[:5]  # top 5
                    lines = []
                    for i, f in enumerate(flights, 1):
                        price = f.get("price", {})
                        amt = price.get("total", "N/A")
                        cur = price.get("currency", "USD")
                        airline = f.get("validatingAirlineCodes", [""])[0]
                        stops = 0
                        if f.get("itineraries"):
                            stops = len(f["itineraries"][0].get("segments", [])) - 1
                        lines.append(
                            f"  {i}. {airline} — {cur} {amt} "
                            f"({'nonstop' if stops == 0 else f'{stops} stop(s)'})"
                        )
                    flights_context = (
                        f"\n\nLIVE FLIGHT DATA ({origin}→{destination}, {departure_date}):\n"
                        + "\n".join(lines)
                    )
            except Exception as e:
                logger.warning(f"Flight data fetch failed (non-blocking): {e}")

        # Build enhanced query
        enhanced_query = query
        if flights_context:
            enhanced_query += (
                f"\n\nAnalyse these live flight options and recommend the best value. "
                f"Factor in Mystes's historical pricing data from the context below."
                f"{flights_context}"
            )

        # Run through normal AI ensemble with intelligence context
        result = self.search(user_id, enhanced_query, market=market)

        # Attach flight data to response
        if flights:
            result["flights"] = flights
        result["data_enhanced"] = True

        return result


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

mystes_ai = MystesAI()
