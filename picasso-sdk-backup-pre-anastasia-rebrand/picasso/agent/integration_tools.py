"""
Integration Tool Definitions — Claude function calling schemas for code operations.

These tools enable the unified assistant to:
1. Read/write files in the customer's project (CLI mode only)
2. Search code for patterns
3. Run commands (tests, installs, etc.)
4. Diagnose errors from stack traces
5. Generate framework-specific integration code
6. Update agency configuration through conversation

MYSTES KYRIOS LLC — Confidential.
"""

INTEGRATION_TOOL_DEFINITIONS = [
    # ================================================================
    # FILE OPERATIONS (CLI mode only — disabled in web chat)
    # ================================================================
    {
        "name": "read_file",
        "description": "Read the contents of a file in the customer's project. Use this to understand their code before suggesting changes. Only reads files within the declared project root. Returns the file content with line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path from project root (e.g., 'app.py', 'src/routes/flights.py')"
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start reading from this line number (1-indexed). Omit to read from beginning."
                },
                "end_line": {
                    "type": "integer",
                    "description": "Stop reading at this line number. Omit to read to end."
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file in the customer's project. Use this to create new files or replace entire file contents. For partial edits, use edit_file instead. Requires user confirmation before executing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path from project root"
                },
                "content": {
                    "type": "string",
                    "description": "The complete file content to write"
                },
                "description": {
                    "type": "string",
                    "description": "Brief description of what this file does (shown to user for confirmation)"
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": "Make a targeted edit to an existing file by replacing a specific string. Use this for surgical changes rather than rewriting the whole file. The old_string must be unique in the file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path from project root"
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact string to find and replace (must be unique in the file)"
                },
                "new_string": {
                    "type": "string",
                    "description": "The replacement string"
                }
            },
            "required": ["path", "old_string", "new_string"]
        }
    },
    {
        "name": "search_code",
        "description": "Search for a pattern across all files in the project. Returns matching lines with file paths and line numbers. Use this to find where SDK imports, API calls, or specific patterns are used.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (regex supported, e.g., 'import.*picasso', 'API_KEY', 'def search')"
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g., '*.py', '*.js', 'src/**/*.tsx'). Default: all files."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 30)",
                    "default": 30
                }
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "list_files",
        "description": "List files and directories in the project. Use this to understand the project structure before making changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative directory path from project root (default: root)",
                    "default": "."
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter (e.g., '*.py', '**/*.js')"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum directory depth to traverse (default: 3)",
                    "default": 3
                }
            }
        }
    },
    {
        "name": "run_command",
        "description": "Execute a shell command in the project directory. Use this for: running tests, installing packages, checking versions, starting/stopping the server. Commands execute with a 60-second timeout. Requires user confirmation for destructive commands.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute (e.g., 'pip install picasso-redbox-sdk', 'python -m pytest', 'npm test')"
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description of what this command does (shown to user)"
                }
            },
            "required": ["command"]
        }
    },

    # ================================================================
    # DIAGNOSTICS (available in both web and CLI modes)
    # ================================================================
    {
        "name": "diagnose_error",
        "description": "Analyze an error message or stack trace and provide a diagnosis with fix. Use this when the admin pastes an error. Returns structured diagnosis: what went wrong, why, and how to fix it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "error_text": {
                    "type": "string",
                    "description": "The full error message, stack trace, or log output"
                },
                "context": {
                    "type": "string",
                    "description": "Additional context: what they were trying to do, what code triggered it"
                }
            },
            "required": ["error_text"]
        }
    },
    {
        "name": "generate_integration_code",
        "description": "Generate complete, working integration code for a specific framework and use case. Returns ready-to-use code with instructions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "framework": {
                    "type": "string",
                    "enum": ["flask", "django", "express", "nextjs", "react", "vue", "html", "python_script"],
                    "description": "Target framework for the integration code"
                },
                "feature": {
                    "type": "string",
                    "enum": ["search_widget", "booking_flow", "ai_chat", "full_integration", "api_proxy", "webhook_handler"],
                    "description": "Which feature to generate code for"
                },
                "api_base": {
                    "type": "string",
                    "description": "The API base URL to use in generated code (e.g., 'https://flights.example.com')"
                },
                "options": {
                    "type": "object",
                    "description": "Additional options: {typescript: true, tailwind: true, include_styles: true}"
                }
            },
            "required": ["framework", "feature"]
        }
    },
    {
        "name": "check_integration_health",
        "description": "Run a comprehensive health check on the SDK integration. Tests: API connectivity, authentication, search capability, config validity. Returns a status report.",
        "input_schema": {
            "type": "object",
            "properties": {
                "api_base": {
                    "type": "string",
                    "description": "The API base URL to test against"
                },
                "api_key": {
                    "type": "string",
                    "description": "The API key to test with"
                },
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["connectivity", "auth", "search", "booking", "config", "all"]
                    },
                    "description": "Which checks to run (default: all)"
                }
            }
        }
    },

    # ================================================================
    # ADMIN CONFIGURATION (available in both modes)
    # ================================================================
    {
        "name": "update_agency_config",
        "description": "Update the agency's configuration. Use this when the admin asks to change pricing, display settings, branding, or feature flags through conversation. Changes take effect immediately.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": ["pricing", "display", "branding", "features"],
                    "description": "Which config section to update"
                },
                "updates": {
                    "type": "object",
                    "description": "Key-value pairs to update. Only include fields that are changing."
                }
            },
            "required": ["section", "updates"]
        }
    },
    {
        "name": "get_agency_config",
        "description": "Retrieve the current agency configuration. Use this to show the admin their current settings before making changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": ["pricing", "display", "branding", "features", "all"],
                    "description": "Which config section to retrieve (default: all)"
                }
            }
        }
    },
    {
        "name": "get_sdk_version",
        "description": "Get information about the current SDK version and available updates.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
]
