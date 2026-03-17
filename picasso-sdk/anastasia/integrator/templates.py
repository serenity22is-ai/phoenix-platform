"""
Integration Templates — Pre-built integration patterns for top tech stacks.

Each template defines the complete integration blueprint for a specific
language + framework combination: files to create, directory structure,
dependencies to install, environment variables needed, and setup commands.

These templates drive the CodeGenerator and give agencies a clear picture
of what ANASTASiA will create in their codebase.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List, Optional

from ..core.types import TechStack

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Template definitions
#
# Each template is keyed by (language, framework) and contains:
#   - name: Human-readable name
#   - description: What this template covers
#   - files_to_create: List of files ANASTASiA will generate
#   - file_structure: Recommended directory layout
#   - dependencies_to_add: Packages to install
#   - env_vars_needed: Environment variables to configure
#   - setup_commands: Shell commands to run after file generation
#   - notes: Any special considerations
# ---------------------------------------------------------------------------

TEMPLATES: Dict[tuple, dict] = {

    # -----------------------------------------------------------------
    # Python + Flask — Complete reference implementation (our own stack)
    # -----------------------------------------------------------------
    ("python", "flask"): {
        "name": "Python + Flask",
        "description": (
            "Complete ANASTASiA integration for Flask applications. "
            "Includes API client, payment adapter (Stripe), Blueprint-based "
            "routes, and configuration. This is our reference implementation — "
            "MYSTES itself runs Flask."
        ),
        "files_to_create": [
            "anastasia/__init__.py",
            "anastasia/client.py",
            "anastasia/payment_adapter.py",
            "anastasia/routes.py",
            "anastasia/config.py",
        ],
        "file_structure": {
            "anastasia/": "ANASTASiA integration package",
            "anastasia/__init__.py": "Package init + Flask extension setup",
            "anastasia/client.py": "API client with retry logic",
            "anastasia/payment_adapter.py": "Stripe <-> ANASTASiA fee bridge",
            "anastasia/routes.py": "Flask Blueprint with search/book endpoints",
            "anastasia/config.py": "Configuration from environment variables",
        },
        "dependencies_to_add": [
            "requests>=2.28.0",
            "anastasia-sdk>=1.0.0",
        ],
        "env_vars_needed": [
            "ANASTASIA_API_KEY",
            "ANASTASIA_AGENCY_ID",
            "ANASTASIA_BASE_URL",
            "ANASTASIA_FLIGHTS=true",
            "ANASTASIA_HOTELS=false",
        ],
        "setup_commands": [
            "pip install requests anastasia-sdk",
            "# Add to your app.py: from anastasia.routes import anastasia_bp",
            "# Then: app.register_blueprint(anastasia_bp)",
        ],
        "notes": (
            "Flask Blueprint registers under /anastasia prefix. "
            "Modify url_prefix in routes.py if needed. "
            "Payment adapter assumes Stripe — swap _charge method for other processors."
        ),
    },

    # -----------------------------------------------------------------
    # Python + Django
    # -----------------------------------------------------------------
    ("python", "django"): {
        "name": "Python + Django",
        "description": (
            "Django integration with class-based views, URL routing, "
            "and Django REST Framework serializers for the booking API."
        ),
        "files_to_create": [
            "anastasia/__init__.py",
            "anastasia/apps.py",
            "anastasia/client.py",
            "anastasia/views.py",
            "anastasia/urls.py",
            "anastasia/serializers.py",
            "anastasia/payment_adapter.py",
            "anastasia/config.py",
        ],
        "file_structure": {
            "anastasia/": "Django app for ANASTASiA integration",
            "anastasia/apps.py": "Django AppConfig",
            "anastasia/views.py": "Class-based views for search + booking",
            "anastasia/urls.py": "URL patterns (include in project urls.py)",
            "anastasia/serializers.py": "DRF serializers for request/response",
            "anastasia/payment_adapter.py": "Payment processor bridge",
            "anastasia/config.py": "Django settings integration",
        },
        "dependencies_to_add": [
            "requests>=2.28.0",
            "djangorestframework>=3.14.0",
            "anastasia-sdk>=1.0.0",
        ],
        "env_vars_needed": [
            "ANASTASIA_API_KEY",
            "ANASTASIA_AGENCY_ID",
            "ANASTASIA_BASE_URL",
            "ANASTASIA_FLIGHTS=true",
            "ANASTASIA_HOTELS=false",
        ],
        "setup_commands": [
            "pip install requests djangorestframework anastasia-sdk",
            "# Add 'anastasia' to INSTALLED_APPS in settings.py",
            "# Add to urls.py: path('anastasia/', include('anastasia.urls'))",
        ],
        "notes": (
            "Uses Django REST Framework for serialization. "
            "Authentication handled by your existing DRF auth classes."
        ),
    },

    # -----------------------------------------------------------------
    # JavaScript + Express
    # -----------------------------------------------------------------
    ("javascript", "express"): {
        "name": "JavaScript + Express",
        "description": (
            "Express.js integration with router middleware, async handlers, "
            "and Axios-based API client."
        ),
        "files_to_create": [
            "anastasia/index.js",
            "anastasia/client.js",
            "anastasia/paymentAdapter.js",
            "anastasia/routes.js",
            "anastasia/config.js",
        ],
        "file_structure": {
            "anastasia/": "ANASTASiA integration module",
            "anastasia/index.js": "Module entry point + Express middleware setup",
            "anastasia/client.js": "Axios-based API client",
            "anastasia/paymentAdapter.js": "Payment processor bridge",
            "anastasia/routes.js": "Express router with search/book endpoints",
            "anastasia/config.js": "Configuration from process.env",
        },
        "dependencies_to_add": [
            "axios@^1.6.0",
            "anastasia-sdk@^1.0.0",
        ],
        "env_vars_needed": [
            "ANASTASIA_API_KEY",
            "ANASTASIA_AGENCY_ID",
            "ANASTASIA_BASE_URL",
            "ANASTASIA_FLIGHTS=true",
            "ANASTASIA_HOTELS=false",
        ],
        "setup_commands": [
            "npm install axios anastasia-sdk",
            "// Add to app.js: const anastasiaRoutes = require('./anastasia/routes');",
            "// Then: app.use('/anastasia', anastasiaRoutes);",
        ],
        "notes": (
            "Uses async/await with Express error handling middleware. "
            "Compatible with Express 4.x and 5.x."
        ),
    },

    # -----------------------------------------------------------------
    # JavaScript + Next.js
    # -----------------------------------------------------------------
    ("javascript", "nextjs"): {
        "name": "JavaScript + Next.js",
        "description": (
            "Next.js integration with App Router API routes, React search "
            "component, and server-side API client."
        ),
        "files_to_create": [
            "lib/anastasia/client.js",
            "lib/anastasia/config.js",
            "app/api/anastasia/search/route.js",
            "app/api/anastasia/book/route.js",
            "app/api/anastasia/deals/[dealId]/route.js",
            "components/ANASTASiASearch.jsx",
            "components/DealCard.jsx",
        ],
        "file_structure": {
            "lib/anastasia/": "Server-side ANASTASiA client and config",
            "app/api/anastasia/": "API route handlers (App Router)",
            "components/": "React components for search UI",
        },
        "dependencies_to_add": [
            "axios@^1.6.0",
            "anastasia-sdk@^1.0.0",
        ],
        "env_vars_needed": [
            "ANASTASIA_API_KEY",
            "ANASTASIA_AGENCY_ID",
            "ANASTASIA_BASE_URL",
            "NEXT_PUBLIC_ANASTASIA_FLIGHTS=true",
            "NEXT_PUBLIC_ANASTASIA_HOTELS=false",
        ],
        "setup_commands": [
            "npm install axios anastasia-sdk",
            "# Components are ready to import in your pages",
            "# API routes are auto-registered by Next.js App Router",
        ],
        "notes": (
            "Uses Next.js App Router conventions. API key is server-side only "
            "(not NEXT_PUBLIC_). Search component uses client-side fetch to "
            "your own API routes, which proxy to ANASTASiA."
        ),
    },

    # -----------------------------------------------------------------
    # PHP + Laravel
    # -----------------------------------------------------------------
    ("php", "laravel"): {
        "name": "PHP + Laravel",
        "description": (
            "Laravel integration with service provider, Facade, controller, "
            "and Blade component for the search UI."
        ),
        "files_to_create": [
            "app/Services/ANASTASiA/Client.php",
            "app/Services/ANASTASiA/PaymentAdapter.php",
            "app/Http/Controllers/ANASTASiAController.php",
            "app/Providers/ANASTASiAServiceProvider.php",
            "config/anastasia.php",
            "routes/anastasia.php",
            "resources/views/components/anastasia-search.blade.php",
        ],
        "file_structure": {
            "app/Services/ANASTASiA/": "API client and payment adapter",
            "app/Http/Controllers/": "Controller for search + booking",
            "app/Providers/": "Service provider for DI container",
            "config/": "Configuration file",
            "routes/": "Route definitions",
            "resources/views/components/": "Blade search component",
        },
        "dependencies_to_add": [
            "guzzlehttp/guzzle:^7.0",
            "anastasia/sdk:^1.0",
        ],
        "env_vars_needed": [
            "ANASTASIA_API_KEY",
            "ANASTASIA_AGENCY_ID",
            "ANASTASIA_BASE_URL",
            "ANASTASIA_FLIGHTS=true",
            "ANASTASIA_HOTELS=false",
        ],
        "setup_commands": [
            "composer require guzzlehttp/guzzle anastasia/sdk",
            "php artisan vendor:publish --tag=anastasia-config",
            "# Add ANASTASiAServiceProvider to config/app.php providers array",
            "# Add route include in routes/web.php: require __DIR__.'/anastasia.php';",
        ],
        "notes": (
            "Uses Laravel's service container for dependency injection. "
            "The Facade provides static access: ANASTASiA::searchFlights(...)."
        ),
    },

    # -----------------------------------------------------------------
    # Java + Spring Boot
    # -----------------------------------------------------------------
    ("java", "spring"): {
        "name": "Java + Spring Boot",
        "description": (
            "Spring Boot integration with auto-configuration, REST controller, "
            "and reactive WebClient for the API client."
        ),
        "files_to_create": [
            "src/main/java/com/anastasia/client/ANASTASiAClient.java",
            "src/main/java/com/anastasia/client/ANASTASiAProperties.java",
            "src/main/java/com/anastasia/client/ANASTASiAAutoConfiguration.java",
            "src/main/java/com/anastasia/controller/ANASTASiAController.java",
            "src/main/java/com/anastasia/service/PaymentAdapterService.java",
            "src/main/resources/application-anastasia.yml",
        ],
        "file_structure": {
            "src/main/java/com/anastasia/client/": "API client + config properties",
            "src/main/java/com/anastasia/controller/": "REST controller",
            "src/main/java/com/anastasia/service/": "Payment adapter service",
            "src/main/resources/": "YAML configuration",
        },
        "dependencies_to_add": [
            "com.anastasia:anastasia-spring-boot-starter:1.0.0",
            "org.springframework.boot:spring-boot-starter-webflux",
        ],
        "env_vars_needed": [
            "ANASTASIA_API_KEY",
            "ANASTASIA_AGENCY_ID",
            "ANASTASIA_BASE_URL",
        ],
        "setup_commands": [
            "# Add dependency to pom.xml or build.gradle",
            "# Spring auto-configuration handles the rest",
            "# Configure in application.yml under 'anastasia:' prefix",
        ],
        "notes": (
            "Uses Spring WebClient (reactive) for non-blocking API calls. "
            "Auto-configuration registers beans when anastasia-starter is on classpath. "
            "@ConfigurationProperties binds anastasia.* properties."
        ),
    },

    # -----------------------------------------------------------------
    # Ruby + Rails
    # -----------------------------------------------------------------
    ("ruby", "rails"): {
        "name": "Ruby + Rails",
        "description": (
            "Rails integration with engine, controller, model concerns, "
            "and Turbo-compatible view partials."
        ),
        "files_to_create": [
            "lib/anastasia/client.rb",
            "lib/anastasia/payment_adapter.rb",
            "lib/anastasia/configuration.rb",
            "app/controllers/anastasia_controller.rb",
            "config/routes/anastasia.rb",
            "config/initializers/anastasia.rb",
            "app/views/anastasia/_search.html.erb",
        ],
        "file_structure": {
            "lib/anastasia/": "API client, config, payment adapter",
            "app/controllers/": "Rails controller with actions",
            "config/routes/": "Route definitions (draw from routes.rb)",
            "config/initializers/": "Configuration initializer",
            "app/views/anastasia/": "ERB partials for search UI",
        },
        "dependencies_to_add": [
            "faraday (~> 2.0)",
            "anastasia-sdk (~> 1.0)",
        ],
        "env_vars_needed": [
            "ANASTASIA_API_KEY",
            "ANASTASIA_AGENCY_ID",
            "ANASTASIA_BASE_URL",
            "ANASTASIA_FLIGHTS=true",
            "ANASTASIA_HOTELS=false",
        ],
        "setup_commands": [
            "bundle add faraday anastasia-sdk",
            "# Add to config/routes.rb: draw(:anastasia)",
            "# Or: Rails.application.routes.draw { resources :anastasia, only: [:index, :create] }",
        ],
        "notes": (
            "Uses Faraday for HTTP (swappable adapter). "
            "Turbo-compatible partials for Hotwire projects. "
            "Credentials stored in Rails encrypted credentials or ENV."
        ),
    },

    # -----------------------------------------------------------------
    # Go + Gin
    # -----------------------------------------------------------------
    ("go", "gin"): {
        "name": "Go + Gin",
        "description": (
            "Gin integration with handler functions, middleware, and "
            "strongly-typed API client."
        ),
        "files_to_create": [
            "internal/anastasia/client.go",
            "internal/anastasia/config.go",
            "internal/anastasia/handlers.go",
            "internal/anastasia/payment_adapter.go",
            "internal/anastasia/middleware.go",
        ],
        "file_structure": {
            "internal/anastasia/": "ANASTASiA integration package",
            "internal/anastasia/client.go": "HTTP client with context + retries",
            "internal/anastasia/config.go": "Configuration from env vars",
            "internal/anastasia/handlers.go": "Gin handler functions",
            "internal/anastasia/payment_adapter.go": "Payment bridge",
            "internal/anastasia/middleware.go": "Auth middleware for booking routes",
        },
        "dependencies_to_add": [
            "github.com/anastasia/go-sdk v1.0.0",
        ],
        "env_vars_needed": [
            "ANASTASIA_API_KEY",
            "ANASTASIA_AGENCY_ID",
            "ANASTASIA_BASE_URL",
        ],
        "setup_commands": [
            "go get github.com/anastasia/go-sdk",
            "// Add to main.go: anastasia.RegisterRoutes(router.Group(\"/anastasia\"))",
        ],
        "notes": (
            "Uses net/http with context propagation. "
            "Structured logging with zerolog or slog. "
            "Compile-time type safety for all API request/response types."
        ),
    },

    # -----------------------------------------------------------------
    # TypeScript + NestJS
    # -----------------------------------------------------------------
    ("typescript", "nestjs"): {
        "name": "TypeScript + NestJS",
        "description": (
            "NestJS integration with module, service, controller, DTOs, "
            "and injectable API client."
        ),
        "files_to_create": [
            "src/anastasia/anastasia.module.ts",
            "src/anastasia/anastasia.service.ts",
            "src/anastasia/anastasia.controller.ts",
            "src/anastasia/dto/search.dto.ts",
            "src/anastasia/dto/booking.dto.ts",
            "src/anastasia/payment-adapter.service.ts",
            "src/anastasia/anastasia.config.ts",
        ],
        "file_structure": {
            "src/anastasia/": "NestJS module for ANASTASiA",
            "src/anastasia/dto/": "Data transfer objects with class-validator",
            "src/anastasia/anastasia.module.ts": "Module declaration",
            "src/anastasia/anastasia.service.ts": "Injectable API client",
            "src/anastasia/anastasia.controller.ts": "REST controller with decorators",
        },
        "dependencies_to_add": [
            "axios@^1.6.0",
            "@nestjs/config@^3.0.0",
            "class-validator@^0.14.0",
            "class-transformer@^0.5.0",
            "anastasia-sdk@^1.0.0",
        ],
        "env_vars_needed": [
            "ANASTASIA_API_KEY",
            "ANASTASIA_AGENCY_ID",
            "ANASTASIA_BASE_URL",
        ],
        "setup_commands": [
            "npm install axios @nestjs/config class-validator class-transformer anastasia-sdk",
            "// Add ANASTASiAModule to app.module.ts imports array",
        ],
        "notes": (
            "Full NestJS conventions: dependency injection, decorators, pipes. "
            "DTOs use class-validator for automatic request validation. "
            "ConfigService handles environment variable access."
        ),
    },

    # -----------------------------------------------------------------
    # Python + FastAPI
    # -----------------------------------------------------------------
    ("python", "fastapi"): {
        "name": "Python + FastAPI",
        "description": (
            "FastAPI integration with Pydantic models, async client, "
            "dependency injection, and auto-generated OpenAPI docs."
        ),
        "files_to_create": [
            "anastasia/__init__.py",
            "anastasia/client.py",
            "anastasia/schemas.py",
            "anastasia/router.py",
            "anastasia/payment_adapter.py",
            "anastasia/config.py",
            "anastasia/dependencies.py",
        ],
        "file_structure": {
            "anastasia/": "ANASTASiA integration package",
            "anastasia/client.py": "Async API client (httpx)",
            "anastasia/schemas.py": "Pydantic models for request/response",
            "anastasia/router.py": "APIRouter with typed endpoints",
            "anastasia/dependencies.py": "FastAPI Depends() for DI",
            "anastasia/config.py": "Pydantic BaseSettings configuration",
        },
        "dependencies_to_add": [
            "httpx>=0.24.0",
            "anastasia-sdk>=1.0.0",
        ],
        "env_vars_needed": [
            "ANASTASIA_API_KEY",
            "ANASTASIA_AGENCY_ID",
            "ANASTASIA_BASE_URL",
            "ANASTASIA_FLIGHTS=true",
            "ANASTASIA_HOTELS=false",
        ],
        "setup_commands": [
            "pip install httpx anastasia-sdk",
            "# Add to main.py: from anastasia.router import router as anastasia_router",
            "# Then: app.include_router(anastasia_router, prefix='/anastasia')",
        ],
        "notes": (
            "Uses httpx for async HTTP (not requests). "
            "Pydantic models give you auto-generated OpenAPI/Swagger docs. "
            "FastAPI Depends() handles client lifecycle and auth."
        ),
    },
}


class IntegrationTemplates:
    """
    Registry of pre-built integration templates for supported tech stacks.

    Provides lookup by (language, framework) tuple or auto-selection based
    on a detected TechStack. Templates define everything needed to generate
    a complete integration: files, dependencies, config, and setup steps.

    Usage:
        templates = IntegrationTemplates()
        template = templates.get_template("python", "flask")
        all_templates = templates.list_templates()
        best_match = templates.get_template_for_stack(tech_stack)
    """

    def get_template(self, language: str, framework: str) -> dict:
        """
        Get the integration template for a specific language + framework.

        Args:
            language: Programming language (e.g., "python", "javascript").
            framework: Web framework (e.g., "flask", "express").

        Returns:
            Template dictionary with files, dependencies, setup commands.
            Returns an empty dict if no template exists for this combination.
        """
        key = (language.lower(), framework.lower())
        template = TEMPLATES.get(key)

        if not template:
            logger.debug(
                "No template found for %s/%s — checking aliases", language, framework
            )
            # Try common aliases
            template = self._try_aliases(language, framework)

        if not template:
            logger.warning("No integration template for %s/%s", language, framework)
            return {}

        return dict(template)  # Return a copy

    def list_templates(self) -> List[dict]:
        """
        List all available integration templates.

        Returns:
            List of template summaries with name, language, framework,
            and file count.
        """
        result = []
        for (language, framework), template in TEMPLATES.items():
            result.append({
                "name": template["name"],
                "language": language,
                "framework": framework,
                "description": template["description"],
                "file_count": len(template["files_to_create"]),
                "dependency_count": len(template["dependencies_to_add"]),
            })
        return result

    def get_template_for_stack(self, tech_stack: TechStack) -> dict:
        """
        Find the best matching template for a detected TechStack.

        Tries exact match first, then falls back to language-only match,
        then returns empty dict if nothing matches.

        Args:
            tech_stack: Detected technology stack.

        Returns:
            Best matching template dictionary, or empty dict.
        """
        language = tech_stack.language.lower() if tech_stack.language else ""
        framework = tech_stack.framework.lower() if tech_stack.framework else ""

        # Try exact match
        if language and framework:
            template = self.get_template(language, framework)
            if template:
                return template

        # Try language with any framework
        if language:
            for (lang, fw), template in TEMPLATES.items():
                if lang == language:
                    logger.info(
                        "No exact match for %s/%s — using %s/%s template",
                        language, framework, lang, fw,
                    )
                    return dict(template)

        # No match
        logger.warning(
            "No template match for stack: %s/%s", language, framework
        )
        return {}

    def _try_aliases(self, language: str, framework: str) -> Optional[dict]:
        """
        Try common framework name aliases.

        Handles cases like "next" -> "nextjs", "nest" -> "nestjs", etc.
        """
        aliases = {
            "next": "nextjs",
            "next.js": "nextjs",
            "nest": "nestjs",
            "nest.js": "nestjs",
            "springboot": "spring",
            "spring-boot": "spring",
            "spring boot": "spring",
            "ror": "rails",
            "ruby on rails": "rails",
            "expressjs": "express",
            "express.js": "express",
            "ginweb": "gin",
            "gin-gonic": "gin",
            "net/http": "gin",  # Default Go to Gin template
        }

        resolved_framework = aliases.get(framework.lower(), framework.lower())
        key = (language.lower(), resolved_framework)
        return TEMPLATES.get(key)
