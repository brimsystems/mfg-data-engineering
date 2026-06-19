# data_pipeline

dbt project for the defects and scrap marts, on DuckDB.

- `models/staging/`: one model per source table (ERP, MES, QMS, Materials, HR), cleaned and typed.
- `models/intermediate/`: work orders joined to inspections and enriched from every system; scrap and rework cost.
- `models/marts/`: the tables the diagnostic report and dashboard read.

Run `dbt build` from this folder. The raw files are read from `../data_source/raw/`.
