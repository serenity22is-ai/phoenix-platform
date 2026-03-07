# Live Services — MYSTES KYRIOS LLC
## As of March 6, 2026

### Service 1: MYSTES Consumer OTA
| Field | Value |
|-------|-------|
| URL | https://phoenix-web-nj67.onrender.com |
| Health | https://phoenix-web-nj67.onrender.com/health |
| Service ID | srv-d61a6f24d50c739nvb40 |
| Dashboard | https://dashboard.render.com/web/srv-d61a6f24d50c739nvb40 |
| Runtime | Docker, free tier, Oregon |
| Database | phoenix-db (PostgreSQL Pro 4GB) |
| Redis | phoenix-redis (free) |
| Routes | 118 (Phase 1: flights, search, booking, payments, admin) |
| Stack | Flask, SQLAlchemy, Stripe, Picasso/Redbox |
| Repo | https://github.com/serenity22is-ai/phoenix-platform (root) |

### Service 2: ANASTASiA B2B API
| Field | Value |
|-------|-------|
| URL | https://anastasia-api.onrender.com |
| Health | https://anastasia-api.onrender.com/api/v1/health |
| Signup | https://anastasia-api.onrender.com/signup |
| Service ID | srv-d6lop4ua2pns73coc5q0 |
| Dashboard | https://dashboard.render.com/web/srv-d6lop4ua2pns73coc5q0 |
| Runtime | Docker, starter tier, Oregon |
| Routes | 44 (AI chat, search, booking, billing, admin, analytics) |
| Stack | Flask, Claude Opus 4.6, Stripe, Picasso/Redbox SDK |
| Repo | https://github.com/serenity22is-ai/phoenix-platform (rootDir: picasso-sdk) |
| Master Key | ana_65f9bf80de4e5e55c96676d479bb0d9097e2b038cfccaef6 |
| AI Model | claude-opus-4-6 |
| Auto Deploy | Off (manual deploys only) |

### Environment Variables — ANASTASiA
| Key | Description |
|-----|-------------|
| ANTHROPIC_API_KEY | Claude API key for AI agent |
| ANASTASIA_MASTER_KEY | Master admin key (auto-generated: ana_65f9...) |
| AGENT_MODEL | claude-opus-4-6 |
| CONFIG_DIR | /app/.agency_configs |
| GUNICORN_WORKERS | 2 |
| GUNICORN_THREADS | 4 |
| LOG_LEVEL | INFO |

### Render Account
| Field | Value |
|-------|-------|
| Owner | Zack Snyder (serenity22is@gmail.com) |
| Workspace | Zack's workspace (tea-d619u0p4tr6s73c5hlpg) |
| Region | Oregon |
