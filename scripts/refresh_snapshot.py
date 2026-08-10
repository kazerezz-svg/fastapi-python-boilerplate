"""Fetch the deployed API and write a deterministic analysis snapshot."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx


def refresh(api_base_url: str, output_path: Path) -> None:
    base = api_base_url.rstrip("/")
    with httpx.Client(timeout=120.0) as client:
        league_map = client.get(f"{base}/league-map")
        league_map.raise_for_status()
        history = client.get(f"{base}/history")
        history.raise_for_status()
        external_context = client.get(f"{base}/external-context")
        external_context.raise_for_status()

    payload = {
        "snapshot_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_api": base,
        "league_map": league_map.json(),
        "history": history.json(),
        "external_context": external_context.json(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--output", default="snapshots/latest.json")
    args = parser.parse_args()
    refresh(args.api_base_url, Path(args.output))

