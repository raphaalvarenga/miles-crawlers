# Miles Crawlers — Smiles worker

Minimal Python worker that consumes crawl jobs for the `smiles` provider from RabbitMQ,
executes a headless crawl using Camoufox and persists results to Postgres.

Environment variables:

- `RABBIT_URL` (e.g. `amqp://guest:guest@localhost/`)
- `QUEUE_NAME` (default `crawl.smiles`)
- `DATABASE_URL` (Postgres DSN, e.g. `postgresql://user:pass@host:5432/db`)
- `PREFETCH_COUNT` (int; optional)

Run:

```
python run_worker.py
```
