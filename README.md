# DF-Skynet (DF Engine)

The backend behind **DF Engine** — Dfactory Visual's in-house tool for generating images and videos with AI.

## What it does

Instead of a designer manually creating every visual from scratch, DF Engine lets people describe what they want in plain text and get an AI-generated image or video back. It's built to support show visuals, storyboards, and other creative content production at Dfactory Visual — for example, generating LED show content for an event, or previewing scenes before a full production.

Behind the scenes, requests are routed through [OpenRouter](https://openrouter.ai), a service that connects to many different AI providers. That means DF Engine can switch between AI models without being locked into a single vendor, and admins can pick which models are actually available to use.

## What people can do with it

- **Generate images and videos** from a text description ("prompt").
- **Build storyboards** — a sequence of scenes, each broken into shots — instead of generating one-off images with no story behind them.
- **Reuse ready-made prompts.** Admins can save "Prompt Templates" (pre-written, tested prompts) so everyday users don't have to write a good prompt from scratch every time.
- **Browse a shared Library** of everything that's been generated, with admins able to see either just their own work or everyone's.
- **Personalize their experience** — theme, language, default video/image size, and a spending confirmation threshold before an action that costs credits goes through.

## What admins can control

- **Menus & Features** — the building blocks of the DF Engine app's navigation. A "Feature" is a capability (like "Enhance prompt"), and a set of Features is grouped into a "Menu." Admins can add, rename, or reorganize these without needing a code change or a new deployment.
- **Which AI models are available**, synced automatically from OpenRouter, with one model set as the default for each type (text, image, video).
- **Spending and usage limits** — a daily credit ceiling for the whole team or per person, and a cap on how many generations someone can start per minute, so nobody accidentally runs up a large bill.
- **Storyboard limits** — how long a scene description can be, and how many scenes/shots a storyboard can hold.
- **API keys** used to talk to OpenRouter, tied to a specific Project Manager or Assistant Project Manager, rotated automatically on a schedule, with every attempt logged for accountability.
- **A full history of setting changes**, so any adjustment to the rules above can be traced back to who made it and when.

## How it fits into the wider Dfactory Visual system

DF Engine isn't a separate product with its own accounts — it shares the same login as the rest of the Dfactory Visual ERP. Signing in once gets you into both.

## Project Structure

```
erp-engine/
├── apps/
│   ├── main.py                   # FastAPI app init, middleware, controller registration
│   ├── secret.py                 # Loads .env into typed config constants
│   ├── controller/               # API endpoint definitions (one file per module)
│   │   ├── core.py               # Base controller classes (auth+DB deps vs. plain/public deps)
│   │   ├── common.py             # Root route + Scalar API docs page
│   │   ├── feature_management.py # CRUD for Features, linked to Prompt Templates
│   │   ├── menu_management.py    # CRUD for Menus, linked to Features
│   │   ├── prompt_template.py    # CRUD for reusable Prompt Templates
│   │   ├── model_management.py   # OpenRouter model sync, enable/disable, set-main
│   │   ├── setting.py            # Admin settings (limits, models) + change-log history
│   │   ├── api_key_management.py # OpenRouter API key issue/rotate, tied to a PM/APM
│   │   └── user_preference.py    # Per-user theme/language/size/spend-confirm settings
│   └── dependency/               # DI components (auth, roles, rate limit)
│       ├── auth.py               # JWT verification, current-user resolution
│       ├── permission.py         # Permission-check dependency (not yet enforced)
│       ├── rate_limitter.py      # Per-route request throttling
│       └── role.py               # Role-check dependency
│
├── services/                     # Business logic & I/O
│   ├── mysql/                    # SQLAlchemy/SQLModel models, sessions, query builder
│   │   ├── model/                # One file per DB table (df_engine_* + shared ERP tables)
│   │   └── factory/              # factory_boy test-data factories, one per df_engine_* table
│   ├── api_caller.py             # Shared async HTTP client wrapper
│   └── openrouter.py             # OpenRouter API integration
│
├── schemas/                      # Pydantic request/response models
│   ├── response.py               # Common Response / PaginationResponse envelopes
│   └── payload/                  # One request-payload file per module
│
├── middlewares/                  # FastAPI middleware
│   ├── language.py               # Resolves request locale
│   └── lang/                     # Translation lookup + en/id message files
│
├── error/                        # Custom exceptions + FastAPI exception handler registration
├── utils/                        # Pure helper functions (formatting, serialization, time)
├── config/                       # App-level config (OpenAPI/Scalar docs setup)
├── cronjob/                      # Scheduled scripts (API key rotation, OpenRouter model sync)
├── migrations/                   # Alembic DB migrations
│   └── versions/                 # One file per migration
├── seeder/                       # Seed/demo data scripts (WIP)
├── script/                       # Shell entrypoints (setup, run server, run tests, run cronjob)
├── docs/                         # DBML schema diagram + module notes
│   ├── db/
│   └── e2e/
├── static/                       # Static HTML error pages (404, 500, restricted)
├── storages/                     # Local file storage (e.g. generated images)
├── env/                          # Per-environment .env files (development, staging)
├── example/                      # .env.examples template
├── log/                          # Runtime log files (per environment)
├── tests/                        # Test suite
│   ├── api/                      # Single-endpoint contract tests
│   ├── e2e/                      # Multi-step journeys chaining several endpoints
│   ├── unit/                     # Pure-logic tests, minimal DB/HTTP touch
│   ├── conftest.py               # Shared pytest fixtures (auth client, db session, mocks)
│   └── helpers.py                # Shared test helpers
├── .github/workflows/            # CI (PR server-boot check)
├── alembic.ini                   # Alembic config
└── pyproject.toml                # Project metadata & dependencies
```

---

## Running it locally

```bash
sh script/setup.sh                  # installs dependencies
sh script/run_server.sh --env dev   # starts the server on http://localhost:10000
```
