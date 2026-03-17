"""
Dev Mode Tool Definitions — Claude function calling schemas for developer tools.

These tools are ADDITIVE to the standard CLI tools. When AssistAgent runs in
dev mode, it gets all booking + CLI tools PLUS these dev-specific tools for
module scaffolding, auditing, publishing, and marketplace interaction.

MYSTES KYRIOS LLC — Confidential.
"""

DEV_TOOL_DEFINITIONS = [
    {
        "name": "scaffold_module",
        "description": (
            "Create a new ANASTASiA module from a template. Generates the project "
            "structure with anastasia-module.json manifest, entry point, tests, "
            "README, and .gitignore. The module is created in the current workspace."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Module name — lowercase, hyphens allowed, no spaces. "
                        "3-64 chars. Example: 'loyalty-points', 'seat-selector'"
                    ),
                },
                "module_type": {
                    "type": "string",
                    "enum": ["extension", "integration", "vertical", "tool"],
                    "description": (
                        "Module type: 'extension' (adds features to core), "
                        "'integration' (connects external service), "
                        "'vertical' (new booking vertical), "
                        "'tool' (utility/library)"
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Short description of what the module does (max 500 chars)",
                },
            },
            "required": ["name", "module_type"],
        },
    },
    {
        "name": "run_audit",
        "description": (
            "Submit a module for the 3-stage audit pipeline: safety scan "
            "(AST analysis for dangerous patterns), compliance check "
            "(manifest validation, license, API permissions), and compatibility "
            "validation (entry point, dependencies, tests). Required before publishing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "module_name": {
                    "type": "string",
                    "description": (
                        "Name of the module to audit. Must exist in the workspace. "
                        "If omitted, uses the currently active module."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "publish_module",
        "description": (
            "Publish a module to the ANASTASiA marketplace after a passing audit. "
            "The module must have been audited first. Published modules are "
            "discoverable by other developers. Private modules are only visible "
            "to the author."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "module_name": {
                    "type": "string",
                    "description": "Module name to publish. If omitted, uses active module.",
                },
                "visibility": {
                    "type": "string",
                    "enum": ["private", "published"],
                    "description": (
                        "'private' = only you can see/install it. "
                        "'published' = visible in the marketplace for all developers."
                    ),
                    "default": "private",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_marketplace",
        "description": (
            "Search the ANASTASiA module marketplace for published modules. "
            "Returns a list of available modules with their descriptions, "
            "versions, and download counts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text search in module names and descriptions",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by tags (e.g., ['flights', 'loyalty'])",
                },
                "module_type": {
                    "type": "string",
                    "enum": ["extension", "integration", "vertical", "tool"],
                    "description": "Filter by module type",
                },
            },
            "required": [],
        },
    },
    {
        "name": "install_module",
        "description": (
            "Install a module from the ANASTASiA marketplace into the current "
            "workspace. Downloads the module files and places them in the workspace."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "module_name": {
                    "type": "string",
                    "description": "Name of the marketplace module to install",
                },
                "version": {
                    "type": "string",
                    "description": "Specific version to install (default: latest)",
                },
            },
            "required": ["module_name"],
        },
    },
    {
        "name": "dev_session_info",
        "description": (
            "Get information about the current dev session: workspace path, "
            "AI usage statistics, active module, and estimated costs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# Dev mode system prompt addition
DEV_MODE_SYSTEM_PROMPT = """

## DEV MODE — Module Development Environment

You are operating in ANASTASiA Dev Mode. In addition to standard booking and
file operations, you have access to module development tools:

- **scaffold_module**: Create new modules from templates
- **run_audit**: Run the 3-stage audit pipeline (safety, compliance, compatibility)
- **publish_module**: Publish audited modules to the marketplace
- **search_marketplace**: Browse available modules
- **install_module**: Install marketplace modules to the workspace
- **dev_session_info**: Check session status and AI usage

### Module Development Workflow
1. Use scaffold_module to create a new module project
2. Write code using read_file, write_file, edit_file
3. Test with run_command (pytest, npm test, etc.)
4. Run run_audit to check for issues
5. Fix any audit issues
6. Use publish_module when ready

### Module Types
- **extension**: Adds features to existing ANASTASiA verticals
- **integration**: Connects an external service/API to ANASTASiA
- **vertical**: New booking vertical (e.g., car rentals, cruises)
- **tool**: Utility library for other modules

### Important Rules
- All code runs within the ANASTASiA platform sandbox
- Modules communicate through the ANASTASiA API only
- No eval(), exec(), or __import__() — these will fail audit
- No accessing system paths (/etc, ~/.ssh, etc.)
- The core is immutable — modules build ON TOP, never inside
"""


def get_dev_tools() -> list:
    """Return the dev tool definitions list for AssistAgent."""
    return DEV_TOOL_DEFINITIONS
