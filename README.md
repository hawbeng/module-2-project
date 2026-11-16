# Module 2 Project: Olist Customer Value & Payments Pipeline

NTU PaCE SCTP Advanced Professional Certificate in Data Science & AI — Module 2 team project.

**Business question:** Who are Olist's valuable customers, why don't they come back, and do instalment payment options help?
(Themes B — customer value and retention, and D — payments and instalments.)

## Architecture

```
Olist CSVs ──► Meltano (tap-csv → target-bigquery) ──► BigQuery olist_raw
          ──► dbt staging (olist_staging) ──► dbt marts (olist_marts, star schema)
          ──► dbt tests / Great Expectations ──► pandas + SQLAlchemy notebooks
Dagster orchestrates and schedules the pipeline; GitHub Actions runs dbt build on pull requests.
```

## Repository layout

| Folder | Contents |
|---|---|
| `ingestion/` | Meltano project that loads the raw CSVs into BigQuery |
| `dbt/olist/` | dbt project: staging models, star schema marts, tests |
| `orchestration/` | Dagster definitions and schedules |
| `notebooks/` | Analysis notebooks (pandas + SQLAlchemy) |
| `docs/` | Architecture diagrams, report, slide deck |
| `data/` | Raw Olist CSVs (gitignored — see `data/README.md`) |
| `.github/workflows/` | CI (dbt build on pull requests) |

## Setup

1. **Data:** download the Olist dataset into `data/` (see `data/README.md`).
2. **Environment:** use the course `elt` conda environment (`conda activate elt`); `dagster` env for orchestration.
3. **GCP:** get the team service-account key from the platform owner (never commit it), then
   `cp .env.example .env` and fill in the values.
4. **dbt:** `cd dbt/olist && cp profiles.yml.example profiles.yml`, then `dbt deps && dbt debug`.

## Team

| Role | Owner |
|---|---|
| Ingestion & platform | TBC |
| Data modelling | TBC |
| Quality & orchestration | TBC |
| Analysis & storytelling | TBC |

## Working agreement

- `main` is the submission branch; work on feature branches and open pull requests.
- No secrets or raw data in Git.
