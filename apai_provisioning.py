"""
APAi Turnkey Instance Provisioning — Build #189

Provisions MYSTES OTA template instances on Render for APAi subscribers.
Each APAi customer gets their own deployed copy of the MYSTES codebase
with custom branding, their own database, and credential routing through
the MYSTES parent network.

Flow:
    1. Customer requests deployment via /api/business/deployment/request
    2. Celery task calls APAiProvisioner.provision()
    3. Provisioner creates Render PostgreSQL database
    4. Provisioner creates Render web service from MYSTES Docker image
    5. Sets env vars (branding, credential key, tier config)
    6. Triggers deploy
    7. Updates TemplateDeployment record with service ID + URL

Requires: RENDER_API_KEY environment variable.

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

RENDER_API_BASE = "https://api.render.com/v1"
MYSTES_DOCKER_IMAGE = os.getenv("MYSTES_DOCKER_IMAGE", "mystes-web")
MYSTES_PARENT_URL = os.getenv("MYSTES_PARENT_URL", "https://mystes.app")


class APAiProvisioner:
    """
    Provisions turnkey MYSTES OTA instances on Render.

    Each APAi deployment gets:
    - Its own Render web service (from MYSTES Docker image)
    - Its own PostgreSQL database
    - Branding configuration via env vars
    - Credential routing key for the MYSTES network
    """

    def __init__(self, render_api_key: str = None):
        self.api_key = render_api_key or os.getenv("RENDER_API_KEY", "")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @property
    def available(self) -> bool:
        """Check if Render API key is configured."""
        return bool(self.api_key)

    def provision(self, deployment, db_session) -> Dict[str, Any]:
        """
        Full provisioning flow for an APAi turnkey instance.

        Args:
            deployment: TemplateDeployment model instance
            db_session: SQLAlchemy session for status updates

        Returns:
            dict with status, render_service_id, url, or error
        """
        if not self.available:
            return self._manual_fallback(deployment, db_session)

        try:
            deployment.status = "provisioning"
            deployment.status_message = "Creating your database..."
            db_session.commit()

            # Step 1: Create PostgreSQL database
            db_result = self._create_database(deployment)
            if not db_result.get("success"):
                return self._handle_error(deployment, db_session, db_result.get("error", "Database creation failed"))

            deployment.status_message = "Setting up your OTA instance..."
            db_session.commit()

            # Step 2: Generate APAi instance key for credential routing
            instance_key = self._generate_instance_key(deployment, db_session)

            # Step 3: Create web service
            config = self._parse_config(deployment)
            env_vars = self._build_env_vars(deployment, db_result, instance_key, config)
            service_result = self._create_service(deployment, env_vars)
            if not service_result.get("success"):
                return self._handle_error(deployment, db_session, service_result.get("error", "Service creation failed"))

            # Step 4: Update deployment record
            deployment.render_service_id = service_result.get("service_id")
            deployment.render_deploy_url = service_result.get("url")
            deployment.subdomain = service_result.get("url", "").replace("https://", "")
            deployment.status = "active"
            deployment.status_message = "Your OTA is live!"
            deployment.provisioned_at = datetime.now(timezone.utc)
            deployment.activated_at = datetime.now(timezone.utc)
            db_session.commit()

            logger.info("APAi instance provisioned: %s -> %s",
                        deployment.deployment_id, service_result.get("url"))

            return {
                "success": True,
                "deployment_id": deployment.deployment_id,
                "service_id": service_result.get("service_id"),
                "url": service_result.get("url"),
                "status": "active",
            }

        except Exception as exc:
            return self._handle_error(deployment, db_session, str(exc))

    def check_status(self, deployment) -> Dict[str, Any]:
        """Check the status of a deployed Render service."""
        if not deployment.render_service_id or not self.available:
            return {"status": deployment.status, "render_status": "unknown"}

        try:
            resp = requests.get(
                f"{RENDER_API_BASE}/services/{deployment.render_service_id}",
                headers=self.headers,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "status": deployment.status,
                    "render_status": data.get("suspended", "unknown"),
                    "url": data.get("serviceDetails", {}).get("url"),
                    "updated_at": data.get("updatedAt"),
                }
            return {"status": deployment.status, "render_status": "api_error"}
        except Exception as e:
            return {"status": deployment.status, "render_status": f"error: {e}"}

    def suspend(self, deployment, db_session) -> Dict[str, Any]:
        """Suspend a running APAi instance (e.g., subscription lapsed)."""
        if deployment.render_service_id and self.available:
            try:
                resp = requests.post(
                    f"{RENDER_API_BASE}/services/{deployment.render_service_id}/suspend",
                    headers=self.headers,
                    timeout=15,
                )
                if resp.status_code not in (200, 202):
                    logger.warning("Render suspend API returned %d", resp.status_code)
            except Exception as e:
                logger.error("Failed to suspend Render service: %s", e)

        deployment.status = "suspended"
        deployment.status_message = "Instance suspended — subscription inactive."
        deployment.suspended_at = datetime.now(timezone.utc)
        db_session.commit()

        return {"success": True, "status": "suspended"}

    def terminate(self, deployment, db_session) -> Dict[str, Any]:
        """Permanently remove an APAi instance and its database."""
        if deployment.render_service_id and self.available:
            try:
                # Delete web service
                requests.delete(
                    f"{RENDER_API_BASE}/services/{deployment.render_service_id}",
                    headers=self.headers,
                    timeout=15,
                )
            except Exception as e:
                logger.error("Failed to delete Render service: %s", e)

        deployment.status = "terminated"
        deployment.status_message = "Instance permanently removed."
        db_session.commit()

        return {"success": True, "status": "terminated"}

    # --- Internal helpers ---

    def _create_database(self, deployment) -> Dict[str, Any]:
        """Create a PostgreSQL database on Render for this instance."""
        db_name = deployment.instance_name.replace("-", "_")[:30]
        try:
            resp = requests.post(
                f"{RENDER_API_BASE}/postgres",
                headers=self.headers,
                json={
                    "name": f"apai-{db_name}-db",
                    "databaseName": f"apai_{db_name}",
                    "databaseUser": "apai",
                    "plan": "starter",
                    "region": "oregon",
                },
                timeout=30,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                return {
                    "success": True,
                    "database_id": data.get("id"),
                    "connection_uri": data.get("connectionInfo", {}).get("internalConnectionString")
                                     or data.get("connectionInfo", {}).get("externalConnectionString", ""),
                }
            return {"success": False, "error": f"Render API returned {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _create_service(self, deployment, env_vars: list) -> Dict[str, Any]:
        """Create a web service on Render."""
        service_name = f"apai-{deployment.instance_name}"[:40]
        try:
            resp = requests.post(
                f"{RENDER_API_BASE}/services",
                headers=self.headers,
                json={
                    "type": "web_service",
                    "name": service_name,
                    "runtime": "docker",
                    "plan": "starter",
                    "region": "oregon",
                    "envVars": env_vars,
                    "autoDeploy": "yes",
                    "dockerDetails": {
                        "dockerfilePath": "./Dockerfile",
                    },
                },
                timeout=30,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                service_id = data.get("service", {}).get("id") or data.get("id")
                url = data.get("service", {}).get("serviceDetails", {}).get("url", "")
                if not url:
                    url = f"https://{service_name}.onrender.com"
                return {"success": True, "service_id": service_id, "url": url}
            return {"success": False, "error": f"Render API returned {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _build_env_vars(self, deployment, db_result, instance_key, config) -> list:
        """Build the environment variable list for the Render service."""
        return [
            {"key": "FLASK_ENV", "value": "production"},
            {"key": "SECRET_KEY", "value": secrets.token_hex(32)},
            {"key": "DATABASE_URL", "value": db_result.get("connection_uri", "")},
            {"key": "MYSTES_TEMPLATE_MODE", "value": "apai"},
            {"key": "APAI_PARENT_URL", "value": MYSTES_PARENT_URL},
            {"key": "APAI_INSTANCE_KEY", "value": instance_key},
            {"key": "APAI_TIER", "value": config.get("tier", "starter")},
            {"key": "BRAND_NAME", "value": deployment.brand_name or deployment.instance_name},
            {"key": "BRAND_COLOR_PRIMARY", "value": deployment.brand_color_primary or "#7c3aed"},
            {"key": "BRAND_COLOR_SECONDARY", "value": deployment.brand_color_secondary or "#a855f7"},
            {"key": "LOGO_URL", "value": deployment.logo_url or ""},
            {"key": "AGENCY_NAME", "value": config.get("agency_name", deployment.brand_name or "")},
            {"key": "GUNICORN_WORKERS", "value": "2"},
        ]

    def _generate_instance_key(self, deployment, db_session) -> str:
        """Generate and store an API key for this APAi instance."""
        from models import APAiInstanceKey

        raw_key = f"apai_{secrets.token_hex(24)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_id = f"apk_{secrets.token_hex(8)}"

        config = self._parse_config(deployment)

        instance_key = APAiInstanceKey(
            key_id=key_id,
            api_key_hash=key_hash,
            deployment_id=deployment.id,
            tier_id=config.get("tier", "starter"),
            is_active=True,
        )
        db_session.add(instance_key)
        db_session.commit()

        logger.info("APAi instance key generated: %s for deployment %s", key_id, deployment.deployment_id)
        return raw_key

    def _parse_config(self, deployment) -> dict:
        """Parse the config_json from a TemplateDeployment."""
        try:
            return json.loads(deployment.config_json) if deployment.config_json else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def _manual_fallback(self, deployment, db_session) -> Dict[str, Any]:
        """When Render API key is not set, queue for manual provisioning."""
        subdomain = deployment.instance_name.lower().replace(" ", "-").replace("_", "-")
        subdomain = "".join(c for c in subdomain if c.isalnum() or c == "-")
        deployment.subdomain = f"{subdomain}.mystes.app"
        deployment.status = "requested"
        deployment.status_message = (
            "Your deployment request is queued. "
            "Our team will provision your OTA instance within 24 hours."
        )
        db_session.commit()

        logger.info("Deployment %s queued for manual provisioning (no Render API key)",
                     deployment.deployment_id)
        return {"success": True, "status": "queued", "manual": True}

    def _handle_error(self, deployment, db_session, error_msg) -> Dict[str, Any]:
        """Handle provisioning failure."""
        deployment.status = "failed"
        deployment.status_message = f"Provisioning error: {error_msg[:200]}"
        db_session.commit()
        logger.error("APAi provisioning failed for %s: %s", deployment.deployment_id, error_msg)
        return {"success": False, "error": error_msg}


def verify_instance_key(raw_key: str) -> Optional[Any]:
    """
    Verify an APAi instance API key and return the APAiInstanceKey record.

    Args:
        raw_key: The raw API key string (e.g., "apai_abc123...")

    Returns:
        APAiInstanceKey model instance if valid and active, else None
    """
    if not raw_key or not raw_key.startswith("apai_"):
        return None

    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    try:
        from models import APAiInstanceKey
        instance_key = APAiInstanceKey.query.filter_by(
            api_key_hash=key_hash, is_active=True
        ).first()

        if instance_key:
            instance_key.last_used_at = datetime.now(timezone.utc)
            instance_key.usage_count = (instance_key.usage_count or 0) + 1
            from models import db
            db.session.commit()

        return instance_key
    except Exception as e:
        logger.error("Error verifying instance key: %s", e)
        return None
