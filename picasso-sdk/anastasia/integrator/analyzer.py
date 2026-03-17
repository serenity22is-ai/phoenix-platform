"""
Codebase Analyzer — Tech stack detection for customer platforms.

Scans a customer's file manifest (filename -> content mapping) and detects
their complete technology stack: language, framework, database, payment
processor, auth system, UI framework, and key file locations.

This is the first step in ANASTASiA's integration pipeline: analyze the
customer's codebase, then generate native integration code in their language
using their patterns.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from ..core.events import EventBus, Event, EventType
from ..core.types import TechStack

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Detection pattern definitions
# ---------------------------------------------------------------------------

# Language detection by file extension
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".swift": "swift",
    ".scala": "scala",
    ".ex": "elixir",
    ".exs": "elixir",
}

# Framework detection patterns: (content_pattern, framework_name)
FRAMEWORK_PATTERNS = {
    "python": [
        (r"from\s+flask\s+import|import\s+flask", "flask"),
        (r"from\s+django\b|django\.conf\.settings|DJANGO_SETTINGS_MODULE", "django"),
        (r"from\s+fastapi\s+import|import\s+fastapi", "fastapi"),
        (r"from\s+starlette\b|import\s+starlette", "starlette"),
        (r"from\s+tornado\b|import\s+tornado", "tornado"),
        (r"from\s+pyramid\b|import\s+pyramid", "pyramid"),
        (r"from\s+bottle\s+import|import\s+bottle", "bottle"),
        (r"from\s+sanic\b|import\s+sanic", "sanic"),
        (r"from\s+aiohttp\b|import\s+aiohttp", "aiohttp"),
    ],
    "javascript": [
        (r"require\(['\"]express['\"]\)|from\s+['\"]express['\"]", "express"),
        (r"next\.config|from\s+['\"]next[/'\"]|@next/", "nextjs"),
        (r"nuxt\.config|from\s+['\"]nuxt['\"]", "nuxt"),
        (r"require\(['\"]koa['\"]\)|from\s+['\"]koa['\"]", "koa"),
        (r"require\(['\"]hapi['\"]\)|from\s+['\"]@hapi/", "hapi"),
        (r"require\(['\"]fastify['\"]\)|from\s+['\"]fastify['\"]", "fastify"),
        (r"gatsby-config|from\s+['\"]gatsby['\"]", "gatsby"),
        (r"remix\.config|from\s+['\"]@remix-run", "remix"),
    ],
    "typescript": [
        (r"@nestjs/|from\s+['\"]@nestjs/", "nestjs"),
        (r"require\(['\"]express['\"]\)|from\s+['\"]express['\"]", "express"),
        (r"next\.config|from\s+['\"]next[/'\"]|@next/", "nextjs"),
        (r"nuxt\.config|from\s+['\"]nuxt['\"]", "nuxt"),
        (r"require\(['\"]fastify['\"]\)|from\s+['\"]fastify['\"]", "fastify"),
    ],
    "java": [
        (r"org\.springframework|@SpringBoot|spring-boot", "spring"),
        (r"io\.quarkus|@QuarkusTest|quarkus", "quarkus"),
        (r"io\.micronaut|@MicronautTest|micronaut", "micronaut"),
        (r"javax\.ws\.rs|jakarta\.ws\.rs|@Path\(", "jaxrs"),
        (r"io\.dropwizard|dropwizard", "dropwizard"),
    ],
    "ruby": [
        (r"Rails\.application|config\.routes\.draw|ActiveRecord", "rails"),
        (r"require\s+['\"]sinatra['\"]|Sinatra::Base", "sinatra"),
        (r"require\s+['\"]hanami['\"]|Hanami\.app", "hanami"),
    ],
    "php": [
        (r"Illuminate\\|use\s+App\\|artisan|laravel", "laravel"),
        (r"Symfony\\|symfony/|use\s+Symfony\\", "symfony"),
        (r"Slim\\App|use\s+Slim\\", "slim"),
        (r"CakePHP|use\s+Cake\\", "cakephp"),
        (r"CodeIgniter|use\s+CodeIgniter\\", "codeigniter"),
    ],
    "go": [
        (r"github\.com/gin-gonic/gin|gin\.Default\(\)|gin\.New\(\)", "gin"),
        (r"github\.com/labstack/echo|echo\.New\(\)", "echo"),
        (r"github\.com/gofiber/fiber|fiber\.New\(\)", "fiber"),
        (r"net/http|http\.ListenAndServe", "net/http"),
        (r"github\.com/gorilla/mux|mux\.NewRouter\(\)", "gorilla"),
    ],
    "kotlin": [
        (r"org\.springframework|@SpringBoot", "spring"),
        (r"io\.ktor|ktor\.", "ktor"),
    ],
    "csharp": [
        (r"Microsoft\.AspNetCore|WebApplication\.Create", "aspnet"),
    ],
    "elixir": [
        (r"Phoenix\.Router|use\s+Phoenix", "phoenix"),
    ],
    "rust": [
        (r"actix_web|actix-web", "actix"),
        (r"rocket::|#\[rocket", "rocket"),
        (r"axum::|use\s+axum", "axum"),
    ],
    "scala": [
        (r"play\.api|PlaySpec|play\.mvc", "playframework"),
        (r"akka\.http|AkkaHttpServer", "akka-http"),
    ],
}

# Database detection patterns
DATABASE_PATTERNS = [
    (r"psycopg2|postgresql|postgres://|asyncpg|pg_connect", "postgresql"),
    (r"pymysql|mysql\.connector|mysql://|mysql2|mysqli", "mysql"),
    (r"pymongo|mongodb://|mongoose|MongoClient", "mongodb"),
    (r"sqlite3|\.sqlite|SQLite", "sqlite"),
    (r"sqlalchemy|SQLAlchemy|create_engine", "sqlalchemy"),
    (r"from\s+prisma|@prisma/client|prisma\.schema", "prisma"),
    (r"sequelize|Sequelize", "sequelize"),
    (r"typeorm|TypeORM|createConnection", "typeorm"),
    (r"redis\.Redis|ioredis|redis://|RedisClient", "redis"),
    (r"elasticsearch|@elastic/elasticsearch", "elasticsearch"),
    (r"dynamodb|DynamoDB|aws-sdk.*dynamodb", "dynamodb"),
    (r"cassandra|CassandraClient|datastax", "cassandra"),
    (r"neo4j|neo4j-driver", "neo4j"),
    (r"firebase-admin|firestore|Firestore", "firestore"),
    (r"CouchDB|couchdb|nano\(", "couchdb"),
    (r"ActiveRecord::Base|activerecord", "activerecord"),
    (r"GORM|gorm\.io", "gorm"),
    (r"Hibernate|@Entity|javax\.persistence", "hibernate"),
]

# Payment detection patterns
PAYMENT_PATTERNS = [
    (r"stripe\.api_key|require\(['\"]stripe['\"]\)|from\s+stripe\b|Stripe\(|@stripe/", "stripe"),
    (r"adyen|Adyen\(|adyen-api|AdyenClient", "adyen"),
    (r"square|Square\(|squareup|SquareClient", "square"),
    (r"paypal|PayPal|paypal-rest-sdk|@paypal/", "paypal"),
    (r"braintree|Braintree\(|braintree-web", "braintree"),
    (r"worldpay|Worldpay", "worldpay"),
    (r"checkout\.com|CheckoutSdk|checkout-sdk", "checkout_com"),
    (r"razorpay|Razorpay\(", "razorpay"),
    (r"mollie|Mollie\(|@mollie/", "mollie"),
    (r"authorize\.net|AuthorizeNet", "authorize_net"),
    (r"2checkout|TwoCheckout", "2checkout"),
]

# Auth detection patterns
AUTH_PATTERNS = [
    (r"passport\.|require\(['\"]passport['\"]\)|passport-", "passport"),
    (r"django-allauth|allauth\.account", "django-allauth"),
    (r"devise|Devise", "devise"),
    (r"spring-security|@EnableWebSecurity|SecurityConfig", "spring-security"),
    (r"Auth0|auth0|@auth0/", "auth0"),
    (r"firebase\.auth|FirebaseAuth|firebase/auth", "firebase-auth"),
    (r"cognito|CognitoIdentityProvider|aws-amplify.*auth", "aws-cognito"),
    (r"oauth2|OAuth2|from\s+oauthlib|passport-oauth", "oauth2"),
    (r"jsonwebtoken|jwt\.encode|jwt\.decode|PyJWT|jose", "jwt"),
    (r"session\.|express-session|flask\.session|SessionMiddleware", "session"),
    (r"keycloak|Keycloak", "keycloak"),
    (r"okta|Okta", "okta"),
    (r"supabase.*auth|@supabase/auth", "supabase-auth"),
    (r"clerk|@clerk/", "clerk"),
    (r"bcrypt|argon2|scrypt", "password-hash"),
]

# UI framework detection patterns
UI_FRAMEWORK_PATTERNS = [
    (r"from\s+['\"]react['\"]|import\s+React|ReactDOM|jsx|createElement", "react"),
    (r"from\s+['\"]vue['\"]|Vue\.createApp|createApp|\.vue\b", "vue"),
    (r"@angular/core|NgModule|@Component|angular\.json", "angular"),
    (r"from\s+['\"]svelte['\"]|svelte\.config|\.svelte\b", "svelte"),
    (r"from\s+['\"]solid-js['\"]|createSignal|SolidJS", "solid"),
    (r"jQuery|\$\(document\)|require\(['\"]jquery['\"]\)", "jquery"),
    (r"htmx|hx-get|hx-post|htmx\.org", "htmx"),
    (r"alpine|x-data|x-show|Alpine\.start", "alpine"),
    (r"ember|Ember\.Application", "ember"),
    (r"backbone|Backbone\.Model", "backbone"),
]

# CSS framework detection patterns
CSS_FRAMEWORK_PATTERNS = [
    (r"tailwindcss|tailwind\.config|@tailwind\s|class=\".*(?:flex|grid|p-|m-|text-|bg-)", "tailwind"),
    (r"bootstrap|Bootstrap|getbootstrap\.com", "bootstrap"),
    (r"@mui/|material-ui|MaterialUI", "material-ui"),
    (r"@chakra-ui/|ChakraProvider", "chakra-ui"),
    (r"ant-design|antd|@ant-design", "antd"),
    (r"bulma|Bulma", "bulma"),
    (r"foundation|Foundation\.css", "foundation"),
    (r"styled-components|createGlobalStyle|css`", "styled-components"),
    (r"emotion|@emotion/|css\(", "emotion"),
]

# Package manager detection by filename
PACKAGE_MANAGER_FILES = {
    "requirements.txt": "pip",
    "Pipfile": "pipenv",
    "pyproject.toml": "pip",
    "setup.py": "pip",
    "poetry.lock": "poetry",
    "package.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "bun.lockb": "bun",
    "composer.json": "composer",
    "Gemfile": "bundler",
    "go.mod": "go-modules",
    "Cargo.toml": "cargo",
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "mix.exs": "mix",
    "Package.swift": "spm",
}

# CI/CD detection by filename
CI_CD_FILES = {
    ".github/workflows": "github-actions",
    ".gitlab-ci.yml": "gitlab-ci",
    "Jenkinsfile": "jenkins",
    ".circleci/config.yml": "circleci",
    ".travis.yml": "travis-ci",
    "bitbucket-pipelines.yml": "bitbucket-pipelines",
    "azure-pipelines.yml": "azure-devops",
    "buildspec.yml": "aws-codebuild",
    ".drone.yml": "drone",
    "Procfile": "heroku",
    "render.yaml": "render",
    "vercel.json": "vercel",
    "netlify.toml": "netlify",
    "fly.toml": "fly-io",
    "railway.toml": "railway",
    "app.yaml": "gcp-app-engine",
}

# Hosting detection patterns (in content)
HOSTING_PATTERNS = [
    (r"amazonaws\.com|aws-sdk|boto3|import\s+boto", "aws"),
    (r"googleapis\.com|google-cloud|@google-cloud", "gcp"),
    (r"azure\.com|@azure/|Microsoft\.Azure", "azure"),
    (r"vercel\.com|VERCEL_|@vercel/", "vercel"),
    (r"heroku\.com|HEROKU_|heroku-postbuild", "heroku"),
    (r"render\.com|RENDER_|render\.yaml", "render"),
    (r"netlify\.com|NETLIFY_|netlify\.toml", "netlify"),
    (r"fly\.io|fly\.toml|FLY_", "fly-io"),
    (r"railway\.app|RAILWAY_", "railway"),
    (r"digitalocean\.com|DIGITALOCEAN_", "digitalocean"),
]

# Route file patterns by language
ROUTE_FILE_PATTERNS = {
    "python": [
        r"@app\.route|@blueprint\.route|@router\.",
        r"urlpatterns\s*=|path\(|re_path\(",
        r"@app\.(get|post|put|delete|patch)\(",
    ],
    "javascript": [
        r"router\.(get|post|put|delete|patch)\(",
        r"app\.(get|post|put|delete|patch)\(",
        r"export\s+default\s+function\s+handler",
        r"export\s+(async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH)",
        r"pages/api/",
    ],
    "typescript": [
        r"@Controller|@Get\(|@Post\(|@Put\(|@Delete\(",
        r"router\.(get|post|put|delete|patch)\(",
        r"app\.(get|post|put|delete|patch)\(",
    ],
    "java": [
        r"@RequestMapping|@GetMapping|@PostMapping|@PutMapping|@DeleteMapping",
        r"@Path\(|@GET|@POST|@PUT|@DELETE",
    ],
    "ruby": [
        r"resources?\s+:|get\s+['\"]|post\s+['\"]|put\s+['\"]|delete\s+['\"]",
        r"config/routes\.rb",
    ],
    "php": [
        r"Route::(get|post|put|delete|patch)\(",
        r"->add\((GET|POST|PUT|DELETE)",
    ],
    "go": [
        r"\.(GET|POST|PUT|DELETE|PATCH)\(|HandleFunc\(|Handle\(",
        r"r\.(Get|Post|Put|Delete|Patch)\(",
    ],
}

# Model file patterns by language
MODEL_FILE_PATTERNS = {
    "python": [
        r"class\s+\w+\(.*(?:db\.Model|models\.Model|Base|DeclarativeBase)\)",
        r"Column\(|ForeignKey\(|relationship\(",
        r"class\s+Meta:|class\s+\w+\(models\.Model\)",
    ],
    "javascript": [
        r"Schema\(|mongoose\.model\(",
        r"sequelize\.define\(|Model\.init\(",
        r"model\(|prisma\.",
    ],
    "typescript": [
        r"@Entity\(|@Column\(|@PrimaryGeneratedColumn",
        r"Schema\(|mongoose\.model\(",
        r"model\(|prisma\.",
    ],
    "java": [
        r"@Entity|@Table|@Column|@Id|@ManyToOne|@OneToMany",
    ],
    "ruby": [
        r"class\s+\w+\s*<\s*(?:ApplicationRecord|ActiveRecord::Base)",
        r"has_many|belongs_to|has_one|has_and_belongs_to_many",
    ],
    "php": [
        r"class\s+\w+\s+extends\s+Model",
        r"protected\s+\$table|protected\s+\$fillable",
    ],
    "go": [
        r"gorm\.Model|type\s+\w+\s+struct\s*{",
    ],
}

# Config file patterns by name
CONFIG_FILE_NAMES = [
    ".env", ".env.example", ".env.local", ".env.production",
    "config.py", "config.js", "config.ts", "config.json", "config.yaml", "config.yml",
    "settings.py", "settings.json",
    "application.properties", "application.yml", "application.yaml",
    ".eslintrc", ".prettierrc", "tsconfig.json",
    "webpack.config.js", "vite.config.js", "vite.config.ts",
    "next.config.js", "next.config.mjs", "next.config.ts",
    "nuxt.config.js", "nuxt.config.ts",
    "tailwind.config.js", "tailwind.config.ts",
    "docker-compose.yml", "docker-compose.yaml", "Dockerfile",
    ".dockerignore", ".gitignore",
    "nginx.conf", "apache.conf",
]


class CodebaseAnalyzer:
    """
    Analyzes a customer's codebase to detect their complete technology stack.

    Takes a file manifest (filename -> content) and uses pattern matching to
    identify the primary language, web framework, database, payment system,
    auth method, UI framework, and key file locations.

    This detection drives ANASTASiA's code generation: once we know the stack,
    we generate native integration code that fits seamlessly into their project.

    Usage:
        analyzer = CodebaseAnalyzer(event_bus)
        tech_stack = analyzer.analyze_codebase(file_manifest)
        report = analyzer.generate_report(tech_stack)
    """

    def __init__(self, event_bus: EventBus):
        """
        Initialize the analyzer.

        Args:
            event_bus: Shared event bus for publishing analysis events.
        """
        self._event_bus = event_bus

    def analyze_codebase(self, file_manifest: Dict[str, str]) -> TechStack:
        """
        Perform full codebase analysis and return a detected TechStack.

        Runs all detection methods against the file manifest and assembles
        a complete TechStack profile with confidence scoring.

        Args:
            file_manifest: Mapping of filename -> file content.

        Returns:
            TechStack with all detected technologies populated.
        """
        if not file_manifest:
            logger.warning("Empty file manifest provided for analysis")
            return TechStack(confidence=0.0)

        language = self.detect_language(file_manifest)
        framework = self.detect_framework(file_manifest, language)
        database = self.detect_database(file_manifest)
        payment = self.detect_payment_system(file_manifest)
        auth = self.detect_auth_system(file_manifest)
        ui = self.detect_ui_framework(file_manifest)
        css = self._detect_css_framework(file_manifest)
        pkg_manager = self._detect_package_manager(file_manifest)
        containerized = self._detect_containerization(file_manifest)
        ci_cd = self._detect_ci_cd(file_manifest)
        hosting = self._detect_hosting(file_manifest)
        cache = self._detect_cache(file_manifest)

        # Build detected_files map
        detected_files = {}
        for filename in self.find_route_files(file_manifest):
            detected_files[filename] = "route_definition"
        for filename in self.find_model_files(file_manifest):
            detected_files[filename] = "model_definition"
        for filename in self.find_config_files(file_manifest):
            detected_files[filename] = "configuration"

        # Calculate confidence based on how many fields we detected
        fields_detected = sum(1 for val in [
            language, framework, database, payment, auth, ui
        ] if val)
        confidence = min(1.0, fields_detected / 6.0 * 0.8 + 0.2)  # 0.2 base

        tech_stack = TechStack(
            language=language,
            framework=framework,
            database=database,
            cache=cache,
            ui_framework=ui,
            css_framework=css,
            package_manager=pkg_manager,
            containerized=containerized,
            ci_cd=ci_cd,
            hosting=hosting,
            detected_files=detected_files,
            confidence=confidence,
        )

        # Publish analysis complete event
        self._event_bus.publish(Event(
            type=EventType.SYSTEM_DISCOVERED,
            source="integrator.analyzer",
            data={
                "action": "codebase_analyzed",
                "tech_stack": tech_stack.to_dict(),
                "file_count": len(file_manifest),
            },
        ))

        logger.info(
            "Codebase analysis complete: %s/%s (confidence: %.0f%%)",
            language, framework, confidence * 100,
        )

        return tech_stack

    def detect_language(self, files: Dict[str, str]) -> str:
        """
        Detect the primary programming language from file extensions and content.

        Counts file extensions, weighted by file size, and returns the
        dominant language. Ignores config/data files.

        Args:
            files: Mapping of filename -> content.

        Returns:
            Primary language string (e.g., "python", "javascript").
        """
        extension_counts: Counter = Counter()

        for filename, content in files.items():
            _, ext = os.path.splitext(filename.lower())
            if ext in EXTENSION_TO_LANGUAGE:
                lang = EXTENSION_TO_LANGUAGE[ext]
                # Weight by content length (larger files count more)
                weight = max(1, len(content) // 500)
                extension_counts[lang] += weight

        if not extension_counts:
            return ""

        # Return the most common language
        primary = extension_counts.most_common(1)[0][0]
        return primary

    def detect_framework(self, files: Dict[str, str], language: str) -> str:
        """
        Detect the web framework used, given the primary language.

        Scans file contents for framework-specific import patterns,
        configuration files, and decorators.

        Args:
            files: Mapping of filename -> content.
            language: Primary language detected by detect_language().

        Returns:
            Framework name string (e.g., "flask", "express", "spring").
        """
        if not language:
            return ""

        patterns = FRAMEWORK_PATTERNS.get(language, [])
        if not patterns:
            return ""

        framework_hits: Counter = Counter()
        all_content = "\n".join(files.values())

        for pattern, framework_name in patterns:
            matches = re.findall(pattern, all_content)
            if matches:
                framework_hits[framework_name] += len(matches)

        # Also check filenames for framework-specific config files
        filenames_lower = {f.lower() for f in files.keys()}
        filename_framework_map = {
            "manage.py": "django",
            "settings.py": "django",
            "wsgi.py": "django",
            "next.config.js": "nextjs",
            "next.config.mjs": "nextjs",
            "next.config.ts": "nextjs",
            "nuxt.config.js": "nuxt",
            "nuxt.config.ts": "nuxt",
            "angular.json": "angular",
            "artisan": "laravel",
            "nest-cli.json": "nestjs",
            "remix.config.js": "remix",
            "gatsby-config.js": "gatsby",
            "svelte.config.js": "svelte",
        }

        for config_file, fw_name in filename_framework_map.items():
            # Check if any filename ends with or matches the config file
            for fname in filenames_lower:
                if fname.endswith(config_file) or fname == config_file:
                    framework_hits[fw_name] += 5  # Strong signal

        if not framework_hits:
            return ""

        return framework_hits.most_common(1)[0][0]

    def detect_database(self, files: Dict[str, str]) -> str:
        """
        Detect the database system from config files, imports, and connection strings.

        Scans for database driver imports, ORM configurations, connection
        URL patterns, and database-specific configuration files.

        Args:
            files: Mapping of filename -> content.

        Returns:
            Database name string (e.g., "postgresql", "mongodb").
        """
        all_content = "\n".join(files.values())
        db_hits: Counter = Counter()

        for pattern, db_name in DATABASE_PATTERNS:
            matches = re.findall(pattern, all_content, re.IGNORECASE)
            if matches:
                db_hits[db_name] += len(matches)

        if not db_hits:
            return ""

        # Prefer actual databases over ORMs when both are detected
        # If we see sqlalchemy AND postgresql, return postgresql
        actual_dbs = {"postgresql", "mysql", "mongodb", "sqlite", "redis",
                      "elasticsearch", "dynamodb", "cassandra", "neo4j",
                      "firestore", "couchdb"}
        orm_names = {"sqlalchemy", "prisma", "sequelize", "typeorm",
                     "activerecord", "gorm", "hibernate"}

        top_hits = db_hits.most_common()
        has_actual_db = any(name in actual_dbs for name, _ in top_hits)

        if has_actual_db:
            # Return the top actual database
            for name, count in top_hits:
                if name in actual_dbs:
                    return name

        # Fall back to ORM name
        return top_hits[0][0]

    def detect_payment_system(self, files: Dict[str, str]) -> str:
        """
        Detect the payment processor from SDK imports and configuration.

        Looks for payment SDK imports, API key patterns, and
        payment-specific configuration.

        Args:
            files: Mapping of filename -> content.

        Returns:
            Payment processor name (e.g., "stripe", "paypal").
        """
        all_content = "\n".join(files.values())
        payment_hits: Counter = Counter()

        for pattern, processor in PAYMENT_PATTERNS:
            matches = re.findall(pattern, all_content, re.IGNORECASE)
            if matches:
                payment_hits[processor] += len(matches)

        if not payment_hits:
            return ""

        return payment_hits.most_common(1)[0][0]

    def detect_auth_system(self, files: Dict[str, str]) -> str:
        """
        Detect the authentication method from imports and middleware config.

        Identifies OAuth2, JWT, session-based auth, and specific auth
        providers like Auth0, Firebase Auth, Passport.js, etc.

        Args:
            files: Mapping of filename -> content.

        Returns:
            Auth system name (e.g., "jwt", "passport", "auth0").
        """
        all_content = "\n".join(files.values())
        auth_hits: Counter = Counter()

        for pattern, auth_name in AUTH_PATTERNS:
            matches = re.findall(pattern, all_content, re.IGNORECASE)
            if matches:
                auth_hits[auth_name] += len(matches)

        if not auth_hits:
            return ""

        # Prefer specific providers over generic methods
        providers = {"auth0", "firebase-auth", "aws-cognito", "keycloak",
                     "okta", "supabase-auth", "clerk", "passport",
                     "django-allauth", "devise", "spring-security"}
        top_hits = auth_hits.most_common()
        has_provider = any(name in providers for name, _ in top_hits)

        if has_provider:
            for name, count in top_hits:
                if name in providers:
                    return name

        return top_hits[0][0]

    def detect_ui_framework(self, files: Dict[str, str]) -> str:
        """
        Detect the frontend UI framework from imports and component patterns.

        Args:
            files: Mapping of filename -> content.

        Returns:
            UI framework name (e.g., "react", "vue", "angular").
        """
        all_content = "\n".join(files.values())
        ui_hits: Counter = Counter()

        for pattern, ui_name in UI_FRAMEWORK_PATTERNS:
            matches = re.findall(pattern, all_content, re.IGNORECASE)
            if matches:
                ui_hits[ui_name] += len(matches)

        if not ui_hits:
            return ""

        return ui_hits.most_common(1)[0][0]

    def find_route_files(self, files: Dict[str, str]) -> List[str]:
        """
        Find files that define API routes or URL patterns.

        Args:
            files: Mapping of filename -> content.

        Returns:
            List of filenames containing route definitions.
        """
        route_files = []

        for filename, content in files.items():
            # Check all language patterns (we scan broadly)
            for lang_patterns in ROUTE_FILE_PATTERNS.values():
                for pattern in lang_patterns:
                    if re.search(pattern, content):
                        if filename not in route_files:
                            route_files.append(filename)
                        break

            # Also match by conventional filenames
            basename = os.path.basename(filename).lower()
            if any(keyword in basename for keyword in [
                "route", "router", "urls", "endpoint", "controller", "api",
            ]):
                if filename not in route_files:
                    route_files.append(filename)

        return sorted(route_files)

    def find_model_files(self, files: Dict[str, str]) -> List[str]:
        """
        Find files containing database model definitions.

        Args:
            files: Mapping of filename -> content.

        Returns:
            List of filenames containing model definitions.
        """
        model_files = []

        for filename, content in files.items():
            for lang_patterns in MODEL_FILE_PATTERNS.values():
                for pattern in lang_patterns:
                    if re.search(pattern, content):
                        if filename not in model_files:
                            model_files.append(filename)
                        break

            # Match by conventional filenames
            basename = os.path.basename(filename).lower()
            if any(keyword in basename for keyword in [
                "model", "schema", "entity", "migration",
            ]):
                if filename not in model_files:
                    model_files.append(filename)

        return sorted(model_files)

    def find_config_files(self, files: Dict[str, str]) -> List[str]:
        """
        Find configuration files in the codebase.

        Args:
            files: Mapping of filename -> content.

        Returns:
            List of filenames that are configuration files.
        """
        config_files = []

        for filename in files.keys():
            basename = os.path.basename(filename).lower()
            if basename in [c.lower() for c in CONFIG_FILE_NAMES]:
                config_files.append(filename)
            elif basename.startswith(".env"):
                config_files.append(filename)
            elif any(keyword in basename for keyword in [
                "config", "settings", "environment",
            ]):
                config_files.append(filename)

        return sorted(config_files)

    def generate_report(self, tech_stack: TechStack) -> dict:
        """
        Generate a human-readable analysis report from a TechStack.

        Args:
            tech_stack: Detected technology stack.

        Returns:
            Dictionary with summary, details, and recommendations.
        """
        summary_parts = []
        if tech_stack.language:
            summary_parts.append(tech_stack.language.capitalize())
        if tech_stack.framework:
            summary_parts.append(tech_stack.framework.capitalize())
        if tech_stack.database:
            summary_parts.append(tech_stack.database.upper())

        summary = " + ".join(summary_parts) if summary_parts else "Unknown Stack"

        details = {}
        if tech_stack.language:
            details["language"] = tech_stack.language
        if tech_stack.framework:
            details["framework"] = tech_stack.framework
        if tech_stack.database:
            details["database"] = tech_stack.database
        if tech_stack.cache:
            details["cache"] = tech_stack.cache
        if tech_stack.ui_framework:
            details["ui_framework"] = tech_stack.ui_framework
        if tech_stack.css_framework:
            details["css_framework"] = tech_stack.css_framework
        if tech_stack.package_manager:
            details["package_manager"] = tech_stack.package_manager
        if tech_stack.containerized:
            details["containerized"] = True
        if tech_stack.ci_cd:
            details["ci_cd"] = tech_stack.ci_cd
        if tech_stack.hosting:
            details["hosting"] = tech_stack.hosting

        # Generate integration recommendations
        recommendations = []
        if tech_stack.language and tech_stack.framework:
            recommendations.append(
                f"Generate native {tech_stack.language}/{tech_stack.framework} "
                f"integration code"
            )
        if tech_stack.database:
            recommendations.append(
                f"Create {tech_stack.database} migration for ANASTASiA tables"
            )
        if tech_stack.ui_framework:
            recommendations.append(
                f"Generate {tech_stack.ui_framework} search component"
            )

        # Identify missing pieces
        warnings = []
        if not tech_stack.language:
            warnings.append("Could not detect primary language")
        if not tech_stack.framework:
            warnings.append("Could not detect web framework")
        if not tech_stack.database:
            warnings.append("No database detected — integration may need manual setup")

        return {
            "summary": summary,
            "confidence": tech_stack.confidence,
            "confidence_label": (
                "high" if tech_stack.confidence >= 0.7
                else "medium" if tech_stack.confidence >= 0.4
                else "low"
            ),
            "details": details,
            "detected_files": tech_stack.detected_files,
            "recommendations": recommendations,
            "warnings": warnings,
        }

    # -------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------

    def _detect_css_framework(self, files: Dict[str, str]) -> str:
        """Detect CSS/styling framework."""
        all_content = "\n".join(files.values())
        hits: Counter = Counter()

        for pattern, name in CSS_FRAMEWORK_PATTERNS:
            matches = re.findall(pattern, all_content, re.IGNORECASE)
            if matches:
                hits[name] += len(matches)

        return hits.most_common(1)[0][0] if hits else ""

    def _detect_package_manager(self, files: Dict[str, str]) -> str:
        """Detect package manager from lock files and manifests."""
        for filename in files.keys():
            basename = os.path.basename(filename).lower()
            if basename in PACKAGE_MANAGER_FILES:
                return PACKAGE_MANAGER_FILES[basename]
        return ""

    def _detect_containerization(self, files: Dict[str, str]) -> bool:
        """Check if the project uses Docker/containers."""
        for filename in files.keys():
            basename = os.path.basename(filename).lower()
            if basename in ("dockerfile", "docker-compose.yml",
                            "docker-compose.yaml", ".dockerignore"):
                return True
        return False

    def _detect_ci_cd(self, files: Dict[str, str]) -> str:
        """Detect CI/CD system from config files."""
        for filename in files.keys():
            normalized = filename.lower().replace("\\", "/")
            for ci_pattern, ci_name in CI_CD_FILES.items():
                if normalized.endswith(ci_pattern.lower()) or \
                   ci_pattern.lower() in normalized:
                    return ci_name
        return ""

    def _detect_hosting(self, files: Dict[str, str]) -> str:
        """Detect hosting platform from config and content patterns."""
        # Check filenames first (strongest signal)
        for filename in files.keys():
            basename = os.path.basename(filename).lower()
            hosting_files = {
                "vercel.json": "vercel",
                "netlify.toml": "netlify",
                "fly.toml": "fly-io",
                "render.yaml": "render",
                "railway.toml": "railway",
                "Procfile": "heroku",
                "app.yaml": "gcp-app-engine",
            }
            if basename in hosting_files:
                return hosting_files[basename]

        # Fall back to content patterns
        all_content = "\n".join(files.values())
        hits: Counter = Counter()
        for pattern, name in HOSTING_PATTERNS:
            matches = re.findall(pattern, all_content, re.IGNORECASE)
            if matches:
                hits[name] += len(matches)

        return hits.most_common(1)[0][0] if hits else ""

    def _detect_cache(self, files: Dict[str, str]) -> str:
        """Detect caching system."""
        all_content = "\n".join(files.values())
        cache_patterns = [
            (r"redis\.Redis|ioredis|redis://|RedisClient|REDIS_URL", "redis"),
            (r"memcached|pylibmc|Memcached", "memcached"),
            (r"@Cacheable|CacheManager|spring\.cache", "spring-cache"),
            (r"django\.core\.cache|CACHES\s*=", "django-cache"),
        ]

        hits: Counter = Counter()
        for pattern, name in cache_patterns:
            matches = re.findall(pattern, all_content, re.IGNORECASE)
            if matches:
                hits[name] += len(matches)

        return hits.most_common(1)[0][0] if hits else ""
