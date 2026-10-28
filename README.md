# DF-Skynet (DF Engine)

The backend behind **DF Engine** — Dfactory Visual's in-house tool for generating images and videos with AI.

## What it does

Instead of a designer manually creating every visual from scratch, DF Engine lets people describe what they want in plain text and get an AI-generated image or video back. It's built to support show visuals, storyboards, and other creative content production at Dfactory Visual — for example, generating LED show content for an event, or previewing scenes before a full production.

Behind the scenes, requests are routed through [OpenRouter](https://openrouter.ai), a service that connects to many different AI providers. That means DF Engine can switch between AI models without being locked into a single vendor, and admins can pick which models are actually available to use.

## What people can do with it

- **Generate images and videos** from a text description ("prompt").
- **Build storyboards** — a sequence of scenes, each broken into shots — instead of generating one-off images with no story behind them.
- **Edit and enhance.** Edit an existing image, or have the AI rewrite a rough prompt into a better one before generating.
- **Organize results** into folders per task, favourite or archive them, pick a main result, and pull in earlier uploads or generations as references.
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

## How a generation works

Generating an image or video takes a while and calls paid external services, so the API never does the work inline:

1. The API validates the request, records it, and returns immediately.
2. A Celery worker picks the job up from Redis, sends it to OpenRouter, then uploads the finished file to the Udin file service.
3. The browser is told when it's done through Pusher (real-time push), so the page doesn't have to poll.

Jobs are idempotent and survive worker crashes and provider outages; a periodic sweep (every 5 minutes) retries stuck uploads. Full design: [docs/e2e/GENERATION_QUEUE.md](docs/e2e/GENERATION_QUEUE.md).

## How it fits into the wider Dfactory Visual system

DF Engine isn't a separate product with its own accounts — it shares the same login as the rest of the Dfactory Visual ERP. Signing in once gets you into both. Laravel issues RS256 JWTs; this service only verifies them with the public key (`JWT_PUBLIC_KEY`, or `secrets/oauth/public.key`) and never issues tokens.

## Tech stack

FastAPI + [fastapi-controller](https://pypi.org/project/fastapi-controller/) · SQLModel/SQLAlchemy (async, MySQL) · Alembic · Celery + Redis · Pusher · pydantic-ai/OpenRouter · Scalar API docs · pytest · uv · ruff. Python 3.11+ (see `.python-version`).

All routes are served under `/api` (e.g. `GET /api/menu-management`). Interactive API docs (Scalar) come from [apps/controller/common.py](apps/controller/common.py) and [config/openapi.py](config/openapi.py).

## API modules

| Module | Routes | What it does |
|---|---|---|
| Generations | `/generations/*`, `/generation-*-results/*` | Create image/video jobs, enhance a prompt, edit an image, fetch results |
| Files | `/files/*`, `/uploaded-files/*`, `/user-galleries/*`, `/references-picker/*` | Per-task files, folders, favourite/archive, uploads, downloads, reference picker |
| Menu management | `/menu-management` | CRUD for Menus (name, description, icon, active flag) linked to Features |
| Feature management | `/feature-management` | CRUD for Features, linked to Prompt Templates |
| Prompt templates | `/prompt-management` | CRUD for reusable prompts |
| Models | `/models`, `/models-price/*` | OpenRouter model sync, enable/disable, set default |
| Settings | `/setting`, `/setting/logs` | Spending/storyboard limits and the change history |
| API keys | `/key-management` | Issue/rotate OpenRouter keys per PM/APM |
| User preference | `/user-preference` | Per-user theme, language, sizes, spend-confirm threshold |
| Logs / Pusher | `/logs`, `/pusher/auth` | External API-call log, Pusher channel auth |

Every response uses the `Response` envelope from [schemas/response.py](schemas/response.py). Messages are localized (`en`, `id`) from the request language.

## Project Structure

```
erp-engine/
├── apps/
│   ├── main.py                   # FastAPI app, CORS + language middleware, controller registration
│   ├── secret.py                 # Loads the env file into typed config constants
│   ├── controller/               # One file per API module (see table above)
│   │   ├── core.py               # Base controllers: CoreDependencies (auth + DB + Redis) / PlainDependencies (public)
│   │   └── ...                   # generations, files, *_management, setting, user_preference, pusher, api_logs, common
│   └── dependency/               # auth (JWT), role, permission (not yet enforced), rate_limitter
├── services/                     # Business logic & I/O
│   ├── mysql/                    # model/ (one file per table), factory/ (factory_boy), query helper
│   ├── tasks/                    # Celery tasks: image_generation, video_generation, udin_uploader, udin_sweep
│   ├── celery_app.py             # Celery app, queue routing, beat schedule
│   ├── dto/                      # Typed DTOs (async + sync DB access for workers)
│   ├── redis.py                  # Redis client + cache keys
│   ├── api_caller.py, pusher.py   # shared HTTP client, Pusher client
│   └── <module>.py               # Per-module service logic used by controllers
├── schemas/                      # Pydantic envelopes + payload/ (one request-payload file per module)
├── parser/, validations/         # OpenRouter payload building; model/prompt input validation
├── middlewares/                  # language.py + lang/{en,id}/ message files
├── error/                        # Custom exceptions + handler registration
├── utils/, config/, log/         # Helpers, OpenAPI/Scalar setup, logging
├── cronjob/                      # Standalone scripts: rotate_api_key.py, sync_models.py
├── migrations/versions/          # Alembic migrations (one file each)
├── seeder/                       # Seed scripts (admin settings)
├── script/                       # setup, run_server, run_cronjob, run_test, pre_push_tests
├── docs/                         # See "Docs" below
├── static/html/                  # 404 / 500 / restricted pages
├── storages/                     # Local file storage
├── env/                          # Per-environment env files (gitignored)
├── tests/                        # api/ (single endpoint), e2e/ (multi-step), unit/, conftest.py, helpers.py
├── .github/workflows/            # CI (see below)
├── alembic.ini · pyproject.toml · uv.lock
```

## Configuration

Settings are read from one env file chosen by the run scripts: `env/.env.development` (`dev`), `env/.env.staging` (`stg`), `env/.env.production` (`prod`). Override with `ENV_FILE=/path`. Never commit these.

| Group | Variables |
|---|---|
| Database (MySQL) | `DB_USERNAME`, `DB_PASSWORD`, `DB_NAME`, `DB_HOST`, `DB_PORT` |
| Redis / Celery | `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` |
| Auth | `JWT_PUBLIC_KEY`, `JWT_ISSUER`, `JWT_AUDIENCE`, `LOGIN_URL`, `ERP_EMAIL`, `ERP_PASSWORD` |
| OpenRouter | `OPENROUTER_API_KEY`, `OPENROUTER_MANAGEMENT_KEY`, `OPENROUTER_BASE_URL` |
| Udin (file service) | `UDIN_API_KEY`, `UDIN_BASE_URL` |
| Pusher | `PUSHER_APP_ID`, `PUSHER_APP_KEY`, `PUSHER_APP_SECRET`, `PUSHER_APP_CLUSTER` |
| Web | `CORS_ALLOWED_ORIGINS` (comma-separated exact origins), `BASE_URL` |

[example/.env.examples](example/.env.examples) is a starting template. Check it against [apps/secret.py](apps/secret.py), which is the source of truth for names.

## Running it locally

Needs MySQL and Redis reachable with the values from your env file.

```bash
sh script/setup.sh                  # installs uv + syncs dependencies
alembic upgrade head                # apply DB migrations
sh script/run_server.sh --env dev   # API on http://127.0.0.1:10000 (stg: 11000, prod: 12000)
```

Generation needs the Celery workers too (the API alone will accept jobs but nothing will process them):

```bash
celery -A services.celery_app:celery_app worker -Q image_generation,video_generation -n generation@%h
celery -A services.celery_app:celery_app worker -Q udin_uploads -n udin@%h
celery -A services.celery_app:celery_app beat      # periodic udin_sweep
```

Run the standalone scheduled scripts with `sh script/run_cronjob.sh --env dev --path cronjob/sync_models.py` (also `cronjob/rotate_api_key.py`).

In Docker (dev/staging/prod) the stack, workers, beat and Flower are defined in the workspace's `erp_infra/` repo, not here.

## Database migrations

```bash
alembic revision -m "add_x_to_df_engine_y"   # then edit the new file in migrations/versions/
alembic upgrade head
alembic downgrade -1
```

Name files `YYYY_MM_DD_HHMM-<rev>_<slug>.py`. Update the matching model in `services/mysql/model/`, its factory in `services/mysql/factory/`, and [docs/db/DF_ENGINE.dbml](docs/db/DF_ENGINE.dbml). Ask before running migrations against a shared database.

## Tests

```bash
sh script/run_test.sh --env dev --test all    # unit | api | e2e | all
PYTHONPATH=. .venv/bin/python -m pytest tests/api/test_menu_management_create.py   # one file
```

API and e2e tests run against the real database configured in the env file and create data through factories, so run them against a dev database, not production. Every new endpoint or payload field should come with an `api/` test (and an `e2e/` step if it joins a journey).

### Pre-push hook

`pre-commit` installs a `pre-push` hook that can run the full suite before every push. The suite is slow, so it is **skipped by default** — a normal `git push` prints `all-tests skipped` and pushes immediately.

To run the whole suite before a push (push is aborted if anything fails):

```bash
RUN_TESTS=1 git push
```

The gate lives in `script/pre_push_tests.sh`. `ruff-format` (line length 120) and the file hygiene hooks always run on commit regardless of this flag.

## CI / branches

- [pr-server-boot-check.yml](.github/workflows/pr-server-boot-check.yml) — on PRs into `staging`/`main`, installs deps, boots the server and checks it answers.
- [pr-delete-branch.yml](.github/workflows/pr-delete-branch.yml) — deletes the source branch after a PR into `staging`/`main` is merged (never `main`/`staging`, never fork branches).
- Branches are named like `fix(menu-management)`; commits use conventional prefixes (`feat:`, `fix:`, `chore:`, `refactor:`, `docs:`). `staging` is the integration branch, `main` is production.

## Docs

| File | What's in it |
|---|---|
| [docs/e2e/GENERATION_QUEUE.md](docs/e2e/GENERATION_QUEUE.md) (+ `.mmd` diagram) | Generation pipeline: queues, retries, idempotency, watchdog, troubleshooting |
| [docs/db/DF_ENGINE.dbml](docs/db/DF_ENGINE.dbml) | Database schema (paste into dbdiagram.io) |
| [docs/PROMPT_MAPPING.md](docs/PROMPT_MAPPING.md) | Which prompt-settings file backs which app page |
| [docs/formulas/](docs/formulas/) | The prompt "formulas" (image/video edit, restyle, LED, story, assets, transitions) |

Deployment, Docker and VPS setup live in the workspace's `erp_infra/` (`docs/setup-local.md`, `docs/deploying-changes.md`).
