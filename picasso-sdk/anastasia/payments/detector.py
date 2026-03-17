"""
Payment System Detector — Identifies what payment processor a customer uses.

ANASTASiA scans customer codebases, config files, and dependency manifests
to detect which payment processor is in use. This detection drives adapter
selection — ANASTASiA NEVER replaces their existing payment system, it
adapts to it.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from ..core.types import PaymentProcessor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Detection patterns: (processor, category, patterns)
#
# Categories:
#   import   — SDK import statements in source code
#   config   — Environment variable names or config keys
#   dep      — Package names in dependency manifests
# ---------------------------------------------------------------------------

_DETECTION_PATTERNS: Dict[PaymentProcessor, Dict[str, List[str]]] = {
    PaymentProcessor.STRIPE: {
        "import": [
            r"stripe\.api_key",
            r"require\s*\(\s*['\"]stripe['\"]\s*\)",
            r"import\s+stripe",
            r"from\s+stripe\s+import",
            r"new\s+Stripe\s*\(",
            r"Stripe\\Stripe::",
            r"stripe\.Charge",
            r"stripe\.PaymentIntent",
            r"stripe\.checkout\.Session",
        ],
        "config": [
            r"STRIPE_SECRET_KEY",
            r"STRIPE_PUBLISHABLE_KEY",
            r"STRIPE_API_KEY",
            r"STRIPE_WEBHOOK_SECRET",
            r"stripe_secret_key",
            r"stripe_publishable_key",
        ],
        "dep": [
            r"\"stripe\"",
            r"'stripe'",
            r"stripe/stripe-php",
            r"stripe-python",
            r"stripe-ruby",
            r"stripe-java",
            r"stripe-go",
            r"stripe-dotnet",
        ],
    },
    PaymentProcessor.ADYEN: {
        "import": [
            r"adyen\.Client",
            r"Adyen\.Client",
            r"require\s*\(\s*['\"]@adyen/api-library['\"]\s*\)",
            r"import\s+Adyen",
            r"from\s+Adyen\s+import",
            r"new\s+Client\s*\(\s*\{",
            r"Adyen\\Client",
        ],
        "config": [
            r"ADYEN_API_KEY",
            r"ADYEN_MERCHANT_ACCOUNT",
            r"ADYEN_CLIENT_KEY",
            r"ADYEN_HMAC_KEY",
            r"ADYEN_LIVE_PREFIX",
            r"adyen_api_key",
        ],
        "dep": [
            r"@adyen/api-library",
            r"Adyen",
            r"adyen-python-api-library",
            r"adyen/php-api-library",
            r"adyen-java-api-library",
            r"adyen-ruby-api-library",
        ],
    },
    PaymentProcessor.SQUARE: {
        "import": [
            r"squareup",
            r"square\.client",
            r"require\s*\(\s*['\"]square['\"]\s*\)",
            r"import\s+square",
            r"from\s+square\.client\s+import",
            r"Square\\SquareClient",
            r"new\s+Client\s*\(",
        ],
        "config": [
            r"SQUARE_ACCESS_TOKEN",
            r"SQUARE_APPLICATION_ID",
            r"SQUARE_LOCATION_ID",
            r"SQUARE_ENVIRONMENT",
            r"square_access_token",
        ],
        "dep": [
            r"squareup",
            r"square",
            r"square/square",
            r"square-connect",
        ],
    },
    PaymentProcessor.PAYPAL: {
        "import": [
            r"paypalrestsdk",
            r"@paypal/checkout-server-sdk",
            r"paypal\.core",
            r"require\s*\(\s*['\"]@paypal",
            r"import\s+paypalrestsdk",
            r"from\s+paypalrestsdk\s+import",
            r"PayPal\\Rest\\ApiContext",
            r"paypal\.Buttons",
        ],
        "config": [
            r"PAYPAL_CLIENT_ID",
            r"PAYPAL_CLIENT_SECRET",
            r"PAYPAL_MODE",
            r"PAYPAL_WEBHOOK_ID",
            r"paypal_client_id",
            r"paypal_client_secret",
        ],
        "dep": [
            r"paypalrestsdk",
            r"paypal-rest-sdk",
            r"@paypal/checkout-server-sdk",
            r"@paypal/paypal-js",
            r"paypal/rest-api-sdk-php",
            r"paypal-server-sdk",
        ],
    },
    PaymentProcessor.BRAINTREE: {
        "import": [
            r"braintree\.BraintreeGateway",
            r"braintree\.Configuration",
            r"require\s*\(\s*['\"]braintree['\"]\s*\)",
            r"import\s+braintree",
            r"from\s+braintree\s+import",
            r"Braintree\\Gateway",
            r"new\s+braintree\.BraintreeGateway",
        ],
        "config": [
            r"BRAINTREE_MERCHANT_ID",
            r"BRAINTREE_PUBLIC_KEY",
            r"BRAINTREE_PRIVATE_KEY",
            r"BRAINTREE_ENVIRONMENT",
            r"braintree_merchant_id",
        ],
        "dep": [
            r"braintree",
            r"braintree-web",
            r"braintree-web-drop-in",
            r"braintree/braintree_php",
            r"braintree-python",
        ],
    },
    PaymentProcessor.WORLDPAY: {
        "import": [
            r"worldpay",
            r"require\s*\(\s*['\"]worldpay['\"]\s*\)",
            r"Worldpay\\Worldpay",
            r"import\s+worldpay",
        ],
        "config": [
            r"WORLDPAY_SERVICE_KEY",
            r"WORLDPAY_CLIENT_KEY",
            r"WORLDPAY_MERCHANT_CODE",
            r"worldpay_service_key",
        ],
        "dep": [
            r"worldpay",
            r"worldpay/worldpay-lib-php",
        ],
    },
    PaymentProcessor.CHECKOUT_COM: {
        "import": [
            r"checkout_sdk",
            r"require\s*\(\s*['\"]checkout-sdk-node['\"]\s*\)",
            r"import\s+checkout_sdk",
            r"from\s+checkout_sdk\s+import",
            r"CheckoutApi",
            r"Checkout\\CheckoutApiException",
        ],
        "config": [
            r"CHECKOUT_SECRET_KEY",
            r"CHECKOUT_PUBLIC_KEY",
            r"CHECKOUT_PROCESSING_CHANNEL",
            r"CKO_SECRET_KEY",
            r"checkout_secret_key",
        ],
        "dep": [
            r"checkout-sdk-python",
            r"checkout-sdk-node",
            r"checkout/checkout-sdk-php",
            r"checkout-sdk-java",
        ],
    },
    PaymentProcessor.RAZORPAY: {
        "import": [
            r"razorpay",
            r"Razorpay\s*\(",
            r"require\s*\(\s*['\"]razorpay['\"]\s*\)",
            r"import\s+razorpay",
            r"from\s+razorpay\s+import",
            r"Razorpay\\Api",
        ],
        "config": [
            r"RAZORPAY_KEY_ID",
            r"RAZORPAY_KEY_SECRET",
            r"razorpay_key_id",
            r"razorpay_key_secret",
        ],
        "dep": [
            r"razorpay",
            r"razorpay-node",
            r"razorpay/razorpay-php",
        ],
    },
    PaymentProcessor.MOLLIE: {
        "import": [
            r"mollie",
            r"MollieClient",
            r"require\s*\(\s*['\"]@mollie/api-client['\"]\s*\)",
            r"import\s+mollie",
            r"from\s+mollie\s+import",
            r"Mollie\\Api\\MollieApiClient",
        ],
        "config": [
            r"MOLLIE_API_KEY",
            r"MOLLIE_PROFILE_ID",
            r"mollie_api_key",
        ],
        "dep": [
            r"mollie-api-python",
            r"@mollie/api-client",
            r"mollie/mollie-api-php",
        ],
    },
}


class PaymentDetector:
    """
    Detects which payment processor a customer's platform uses.

    Scans source code, configuration files, and dependency manifests to
    determine the payment system in use. Returns the processor with the
    highest detection confidence.

    ANASTASiA uses this to select the correct payment adapter — it never
    replaces the customer's existing payment infrastructure.

    Usage:
        detector = PaymentDetector()
        processor = detector.detect_from_code({"server.py": source_code})
        confidence = detector.get_detection_confidence(files)
    """

    def __init__(self):
        self._patterns = _DETECTION_PATTERNS

    def detect_from_code(self, files: Dict[str, str]) -> PaymentProcessor:
        """
        Scan source code files for payment SDK imports and usage.

        Args:
            files: Dict mapping filename -> file content.

        Returns:
            The detected PaymentProcessor, or UNKNOWN if none found.
        """
        scores: Dict[PaymentProcessor, float] = {}

        for filename, content in files.items():
            for processor, categories in self._patterns.items():
                import_patterns = categories.get("import", [])
                for pattern in import_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    if matches:
                        weight = self._file_weight(filename)
                        scores[processor] = scores.get(processor, 0.0) + (
                            len(matches) * weight
                        )

        if not scores:
            logger.info("No payment processor detected from source code")
            return PaymentProcessor.UNKNOWN

        best = max(scores, key=scores.get)
        logger.info(
            "Detected payment processor from code: %s (score=%.1f)",
            best.value, scores[best],
        )
        return best

    def detect_from_config(
        self, config_files: Dict[str, str]
    ) -> PaymentProcessor:
        """
        Check configuration and environment files for payment API keys.

        Args:
            config_files: Dict mapping filename -> file content.
                          Typical files: .env, config.py, settings.json, etc.

        Returns:
            The detected PaymentProcessor, or UNKNOWN if none found.
        """
        scores: Dict[PaymentProcessor, float] = {}

        for filename, content in config_files.items():
            for processor, categories in self._patterns.items():
                config_patterns = categories.get("config", [])
                for pattern in config_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        # Config matches are high-confidence signals
                        scores[processor] = scores.get(processor, 0.0) + 3.0

        if not scores:
            logger.info("No payment processor detected from config files")
            return PaymentProcessor.UNKNOWN

        best = max(scores, key=scores.get)
        logger.info(
            "Detected payment processor from config: %s (score=%.1f)",
            best.value, scores[best],
        )
        return best

    def detect_from_dependencies(
        self, deps_file_content: str
    ) -> PaymentProcessor:
        """
        Check dependency manifest for payment SDK packages.

        Works with package.json, requirements.txt, Pipfile, composer.json,
        Gemfile, build.gradle, pom.xml, go.mod, etc.

        Args:
            deps_file_content: Raw text content of the dependency file.

        Returns:
            The detected PaymentProcessor, or UNKNOWN if none found.
        """
        scores: Dict[PaymentProcessor, float] = {}

        for processor, categories in self._patterns.items():
            dep_patterns = categories.get("dep", [])
            for pattern in dep_patterns:
                if re.search(pattern, deps_file_content, re.IGNORECASE):
                    # Dependency matches are very high-confidence
                    scores[processor] = scores.get(processor, 0.0) + 5.0

        if not scores:
            logger.info("No payment processor detected from dependencies")
            return PaymentProcessor.UNKNOWN

        best = max(scores, key=scores.get)
        logger.info(
            "Detected payment processor from dependencies: %s (score=%.1f)",
            best.value, scores[best],
        )
        return best

    def get_detection_confidence(
        self, files: Dict[str, str]
    ) -> Dict[str, float]:
        """
        Return confidence score per processor across all provided files.

        Runs all three detection methods (code, config, dependencies) and
        aggregates scores into a normalized 0.0-1.0 confidence per processor.

        Args:
            files: Dict mapping filename -> file content. Can include source
                   code, config files, and dependency manifests.

        Returns:
            Dict mapping processor name -> confidence (0.0 to 1.0).
            Only includes processors with confidence > 0.
        """
        raw_scores: Dict[PaymentProcessor, float] = {}

        for filename, content in files.items():
            file_category = self._classify_file(filename)

            for processor, categories in self._patterns.items():
                # Check all pattern categories against this file
                for cat_name, patterns in categories.items():
                    # Weight by how relevant this pattern category is for
                    # this file type
                    relevance = self._category_relevance(
                        cat_name, file_category
                    )
                    for pattern in patterns:
                        matches = re.findall(pattern, content, re.IGNORECASE)
                        if matches:
                            weight = (
                                len(matches)
                                * relevance
                                * self._file_weight(filename)
                            )
                            raw_scores[processor] = (
                                raw_scores.get(processor, 0.0) + weight
                            )

        if not raw_scores:
            return {}

        # Normalize to 0.0-1.0 range
        max_score = max(raw_scores.values())
        if max_score == 0:
            return {}

        confidences = {}
        for processor, score in raw_scores.items():
            normalized = min(score / max(max_score, 15.0), 1.0)
            if normalized > 0.01:  # Filter noise
                confidences[processor.value] = round(normalized, 3)

        # Sort by confidence descending
        return dict(
            sorted(confidences.items(), key=lambda x: x[1], reverse=True)
        )

    def detect_all(
        self, files: Dict[str, str]
    ) -> Tuple[PaymentProcessor, float]:
        """
        Run full detection pipeline and return best match with confidence.

        Combines code scanning, config detection, and dependency analysis
        into a single call. Returns the most likely processor and its
        confidence score.

        Args:
            files: Dict mapping filename -> file content.

        Returns:
            Tuple of (PaymentProcessor, confidence_float).
        """
        confidences = self.get_detection_confidence(files)
        if not confidences:
            return PaymentProcessor.UNKNOWN, 0.0

        best_name = max(confidences, key=confidences.get)
        best_confidence = confidences[best_name]

        # Map string back to enum
        for processor in PaymentProcessor:
            if processor.value == best_name:
                return processor, best_confidence

        return PaymentProcessor.UNKNOWN, 0.0

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _file_weight(filename: str) -> float:
        """
        Weight a file by how likely it is to contain payment logic.

        Payment-related filenames get higher weight.
        """
        name_lower = filename.lower()

        # High-value filenames
        if any(
            kw in name_lower
            for kw in [
                "payment", "billing", "charge", "checkout", "stripe",
                "adyen", "paypal", "braintree", "square", "subscription",
                "invoice",
            ]
        ):
            return 3.0

        # Medium-value: general server / app files
        if any(
            kw in name_lower
            for kw in [
                "server", "app", "main", "routes", "api", "controller",
                "service", "handler", "webhook",
            ]
        ):
            return 1.5

        # Config / env files
        if any(
            kw in name_lower
            for kw in [".env", "config", "settings", "secrets"]
        ):
            return 2.0

        # Dependency manifests
        if name_lower in (
            "package.json", "requirements.txt", "pipfile", "composer.json",
            "gemfile", "build.gradle", "pom.xml", "go.mod", "cargo.toml",
        ):
            return 2.5

        return 1.0

    @staticmethod
    def _classify_file(filename: str) -> str:
        """Classify a file as 'source', 'config', or 'dependency'."""
        name_lower = filename.lower()

        dep_files = {
            "package.json", "requirements.txt", "pipfile", "pipfile.lock",
            "composer.json", "gemfile", "gemfile.lock", "build.gradle",
            "pom.xml", "go.mod", "go.sum", "cargo.toml", "cargo.lock",
            "yarn.lock", "package-lock.json",
        }
        if name_lower in dep_files:
            return "dependency"

        config_indicators = [
            ".env", "config", "settings", "secrets", ".yaml", ".yml",
            ".toml", ".ini", ".cfg",
        ]
        if any(ind in name_lower for ind in config_indicators):
            return "config"

        return "source"

    @staticmethod
    def _category_relevance(
        pattern_category: str, file_category: str
    ) -> float:
        """
        How relevant is a pattern category for a given file category?

        import patterns are most relevant in source files.
        config patterns are most relevant in config files.
        dep patterns are most relevant in dependency manifests.
        """
        relevance_matrix = {
            ("import", "source"): 1.0,
            ("import", "config"): 0.2,
            ("import", "dependency"): 0.1,
            ("config", "source"): 0.5,
            ("config", "config"): 1.0,
            ("config", "dependency"): 0.1,
            ("dep", "source"): 0.1,
            ("dep", "config"): 0.1,
            ("dep", "dependency"): 1.0,
        }
        return relevance_matrix.get((pattern_category, file_category), 0.3)
