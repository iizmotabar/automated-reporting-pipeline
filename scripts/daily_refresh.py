"""
Orchestrates the daily data refresh: extract from source APIs, load into BigQuery,
run dbt, then hand off to the anomaly detector. Meant to run as a scheduled Cloud
Function or Cloud Run job triggered by Cloud Scheduler each morning.
"""

import logging
import subprocess
import sys
from datetime import datetime

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("daily_refresh")


def extract_and_load(source: str, bq_client: bigquery.Client) -> None:
    """Pulls from a source API and loads the raw response into its BigQuery landing table."""
    logger.info(f"Extracting from {source}")
    # Each source has its own extractor module, e.g. extractors.google_ads, extractors.meta_ads
    module = __import__(f"extractors.{source}", fromlist=["run"])
    rows = module.run()

    table_id = f"project.raw.{source}"
    errors = bq_client.insert_rows_json(table_id, rows)
    if errors:
        raise RuntimeError(f"Failed to load {source}: {errors}")
    logger.info(f"Loaded {len(rows)} rows into {table_id}")


def run_dbt() -> None:
    """Runs the dbt project to refresh staging and mart models."""
    logger.info("Running dbt models")
    result = subprocess.run(["dbt", "run", "--project-dir", "./dbt"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"dbt run failed:\n{result.stderr}")
    logger.info("dbt run completed successfully")


def main() -> None:
    bq_client = bigquery.Client()
    sources = ["google_ads", "meta_ads", "ga4", "crm"]

    for source in sources:
        try:
            extract_and_load(source, bq_client)
        except Exception as e:
            logger.error(f"Extraction failed for {source}: {e}")
            sys.exit(1)

    run_dbt()

    logger.info(f"Daily refresh completed at {datetime.utcnow().isoformat()}")

    # Hand off to anomaly detection
    subprocess.run([sys.executable, "scripts/anomaly_detector.py"], check=True)


if __name__ == "__main__":
    main()
