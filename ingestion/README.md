# Ingestion (Meltano)

Loads the 9 Olist CSVs from `data/` into BigQuery dataset `olist_raw`
using `tap-csv` → `target-bigquery` (pattern from lesson 2.6).

TODO: `meltano init`, add extractor/loader, configure from `.env`.
Note: tap-csv loads every column as STRING — cast types in dbt staging.
