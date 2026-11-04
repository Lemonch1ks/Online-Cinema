# Online Cinema API

A REST API for an online cinema: users browse a movie catalog, put movies in a cart, place orders and pay for them with Stripe; moderators manage the catalog, admins manage users and see carts, orders and payments.

Built with FastAPI and async SQLAlchemy on PostgreSQL, with Celery for emails and periodic jobs, MinIO for avatars, and Stripe Checkout for payments. Everything runs with one `docker compose` command.

## Stack

| Area | Tools |
|---|---|
| API | Python 3.14, FastAPI, Pydantic v2 |
| Database | PostgreSQL 17, SQLAlchemy 2.0 (async, asyncpg), Alembic |
| Background jobs | Celery + Redis (worker and beat) |
| Files | MinIO (S3 API, aioboto3) |
| Email | aiosmtplib + Jinja2 templates; Mailpit catches emails locally |
| Payments | Stripe Checkout + webhooks |
| Auth | JWT access/refresh tokens (PyJWT), Argon2 password hashes |
| Quality | pytest (+ xdist, coverage), flake8, ruff format, mypy |
| Delivery | Docker, Docker Compose, GitHub Actions, AWS EC2 |

## Features

**Accounts and access**
- Registration by email with an activation link valid for 24 hours; a new link can be requested. Celery beat deletes expired activation tokens every night.
- Login with a pair of JWT tokens, refresh, logout that revokes the refresh token.
- Password change (with the old password) and reset by email, with password complexity rules.
- Groups: user, moderator, admin. Admins change groups and activate accounts manually.
- Profile with an avatar stored in MinIO.

**Movies**
- Catalog with pagination, filters (year, IMDb rating and more), sorting (price, release date, popularity) and search by title, description, actor or director.
- Likes and dislikes, 10-point ratings, comments with replies; authors get an email when their comment is replied to or liked.
- Favorites with the same search, filters and sorting.
- Genres with the number of movies in each.
- Moderators manage movies, genres, actors and directors. A movie that is in any order cannot be deleted; a movie in users' carts is deleted only with `force=true`.

**Cart and orders**
- Add, remove, list (title, price, genres, year) and clear. A movie can be in the cart once; purchased movies cannot be added again.
- An order is placed from the whole cart; movies already purchased or waiting in another pending order are left out and listed in the response.
- Orders are pending, paid or canceled. A pending order can be canceled; a paid one only refunded.
- Admins see any user's cart and all orders with filters by user, status and dates.

**Payments (Stripe)**
- `POST /orders/{id}/pay` re-checks prices first: if a price has changed, the order is updated and the user is asked to confirm the new total. Then it opens a Stripe Checkout page and returns its url.
- The webhook verifies the Stripe signature, saves the payment and marks the order paid, and emails a confirmation. Repeated events are ignored. Money that comes for an order that cannot take it (canceled, already paid, another amount) is refunded automatically.
- A declined or expired payment emails a suggestion to try a different payment method; `GET /payments/checkout/{session_id}` gives the result for the page Stripe redirects to.
- Payment history for users, all payments with filters for admins, the list of purchased movies, and refunds.

**API documentation**
- Swagger UI at `/api/v1/docs` and ReDoc at `/api/v1/redoc`, open only to active users (HTTP Basic with the account email and password).

## Project structure

```
src/
├── main.py            # FastAPI app, routers
├── tasks.py           # Celery app and periodic tasks
├── core/              # settings, database, protected docs
├── auth/              # users, groups, tokens, profiles
├── movies/            # catalog, genres, stars, directors, favorites, reactions, comments
├── cart/              # shopping cart
├── orders/            # orders, pay, cancel, refund
├── payments/          # Stripe gateway, payments, webhook, purchases
├── notifications/     # emails (templates, SMTP sender, Celery queue)
├── storage/           # S3 / MinIO storage
└── tests/             # pytest suite, one folder per module
alembic/versions/      # database migrations
```

Each module keeps its models, schemas, services and routers together. External services (SMTP, S3, Stripe) are behind small classes that are replaced with fakes in tests.

## Running locally

Requirements: Docker with Compose; for running tests and tools on the host, Python 3.14 and Poetry.

```bash
cp .env.sample .env          # then fill in SECRET_KEY and the Stripe keys
docker compose up -d --build
```

This starts PostgreSQL, Redis, MinIO, Mailpit, the migrations job, the API, the Celery worker and Celery beat. After a code, dependency or migration change run the same command again to rebuild the image.

| Service | Address |
|---|---|
| API | http://localhost:8000/api/v1 |
| Swagger UI | http://localhost:8000/api/v1/docs (log in with an active account) |
| Mailpit (emails) | http://localhost:8025 |
| MinIO console | http://localhost:9001 (`minioadmin` / `minioadmin`) |

To get a first account: register through `POST /api/v1/users/register` and open the activation link from Mailpit.

### Payments locally

1. Take the test keys in the Stripe Dashboard → Developers → API keys and put the secret key in `STRIPE_SECRET_KEY`.
2. Forward Stripe events to the local API with the [Stripe CLI](https://docs.stripe.com/stripe-cli):
   ```bash
   stripe listen --forward-to localhost:8000/api/v1/payments/webhook
   ```
   Put the printed `whsec_...` secret in `STRIPE_WEBHOOK_SECRET` and restart the app.
3. Place an order, call `POST /api/v1/orders/{id}/pay` and open `checkout_url`. Test cards: `4242 4242 4242 4242` succeeds, `4000 0000 0000 0002` is declined (any future date, any CVC).
4. The order becomes paid when the webhook arrives; `stripe listen` shows it with `[200]`.

`STRIPE_SUCCESS_URL` and `STRIPE_CANCEL_URL` point to the frontend; its result page calls `GET /api/v1/payments/checkout/{session_id}`.

## Tests and code quality

Tests need PostgreSQL (`docker compose up -d db`). Each pytest worker creates and drops its own database, and the schema comes from the real migrations.

```bash
poetry install
poetry run pytest -n 4 --cov --cov-report=term-missing
poetry run flake8 .
poetry run ruff format --check .
poetry run mypy
```

The suite covers endpoints and error responses, validation and business rules, unit tests of utilities, gateways and email rendering, migrations (upgrade, downgrade, no drift from the models), and an end-to-end scenario: registration → activation → login → catalog filter → cart → order → payment → webhook → purchases → refund (`src/tests/test_e2e.py`). Coverage is 100%. Stripe, SMTP and S3 are replaced with fakes that raise the same errors as the real clients.

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`) runs on pull requests and pushes to `develop` and `main`:

- **lint**: flake8, `ruff format --check`, mypy;
- **tests**: pytest with coverage against a PostgreSQL service;
- **docker**: checks the compose file and builds the image;
- **deploy**: after a merge into `main`, once all checks pass, connects to the EC2 server over SSH, pulls `main`, runs `docker compose up -d --build` (the migrations job applies new migrations) and waits until the API answers.

### Deploying to AWS EC2

One-time setup:

1. Launch an EC2 instance (Ubuntu), install Docker with the Compose plugin and git, and clone the repository into `~/Online-Cinema`.
2. Security group: open 22 (SSH) and 8000 (API) only; PostgreSQL, Redis and MinIO stay closed.
3. Create `.env` on the server from `.env.sample` with real secrets.
4. In the Stripe Dashboard → Developers → Webhooks add the endpoint `http://<server>:8000/api/v1/payments/webhook` with the events `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed` and `checkout.session.expired`; put its signing secret in `STRIPE_WEBHOOK_SECRET` on the server.
5. In GitHub → Settings → Secrets and variables → Actions add the secrets `EC2_HOST`, `EC2_USER` and `EC2_SSH_KEY` (a private key allowed to log in). The variable `EC2_APP_DIR` is optional (default `Online-Cinema`, relative to the user's home).

Until the secrets are set, the deploy job is skipped with a warning.

## Requirements

The original task description is in [TZ.md](TZ.md).
