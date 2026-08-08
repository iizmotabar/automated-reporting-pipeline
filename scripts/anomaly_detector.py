"""
Compares each watched metric's latest value against its trailing seven day average
and sends a Slack alert if it falls outside the configured threshold. Reads the list
of watched metrics and their sensitivity from config/alert_rules.yaml.
"""

import logging

import requests
import yaml
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("anomaly_detector")

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/REPLACE_WITH_REAL_WEBHOOK"


def load_rules(path: str = "config/alert_rules.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def get_metric_values(bq_client: bigquery.Client, metric_table: str, metric_column: str) -> tuple[float, float]:
    """Returns (latest_value, trailing_7d_average) for the given metric."""
    query = f"""
        select
          {metric_column} as latest_value,
          (
            select avg({metric_column})
            from `{metric_table}`
            where date between date_sub(current_date(), interval 8 day)
                          and date_sub(current_date(), interval 1 day)
          ) as trailing_avg
        from `{metric_table}`
        where date = current_date()
    """
    result = list(bq_client.query(query).result())
    if not result:
        return None, None
    return result[0].latest_value, result[0].trailing_avg


def send_slack_alert(metric_name: str, latest: float, expected: float, threshold_pct: float) -> None:
    deviation_pct = abs(latest - expected) / expected * 100 if expected else 0
    message = {
        "text": (
            f":rotating_light: *Anomaly detected: {metric_name}*\n"
            f"Today's value: `{latest:.2f}`\n"
            f"Expected (7d avg): `{expected:.2f}`\n"
            f"Deviation: `{deviation_pct:.1f}%` (threshold: `{threshold_pct}%`)"
        )
    }
    requests.post(SLACK_WEBHOOK_URL, json=message, timeout=10)


def main() -> None:
    rules = load_rules()
    bq_client = bigquery.Client()

    for metric in rules["watched_metrics"]:
        latest, expected = get_metric_values(bq_client, metric["table"], metric["column"])
        if latest is None or expected is None:
            logger.warning(f"Skipping {metric['name']}, no data available")
            continue

        deviation_pct = abs(latest - expected) / expected * 100 if expected else 0
        if deviation_pct > metric["threshold_pct"]:
            logger.info(f"Anomaly found in {metric['name']}: {deviation_pct:.1f}% deviation")
            send_slack_alert(metric["name"], latest, expected, metric["threshold_pct"])
        else:
            logger.info(f"{metric['name']} within normal range ({deviation_pct:.1f}% deviation)")


if __name__ == "__main__":
    main()
