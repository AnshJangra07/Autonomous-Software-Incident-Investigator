
from collections import defaultdict


def analyze_incidents(events):

    grouped = defaultdict(list)

    # Group errors by failure type
    for event in events:

        failure_type = event.get(
            "failure_type",
            "unknown"
        )

        grouped[failure_type].append(event)

    summaries = []

    for failure_type, failures in grouped.items():

        latest_event = failures[-1]

        summaries.append({
            "failure_type": failure_type,
            "total_occurrences": len(failures),
            "status_codes": list({
                event.get("status_code")
                for event in failures
            }),
            "affected_endpoints": list({
                event.get("endpoint")
                for event in failures
            }),
            "latest_timestamp": latest_event.get(
                "timestamp"
            ),
            "latest_request_id": latest_event.get(
                "request_id"
            ),
            "messages": list({
                event.get("message")
                for event in failures
            })
        })

    return summaries
