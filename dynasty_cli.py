"""Small CLI for durable Codex/ChatGPT access to the deployed API."""
import argparse
import json
import os

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["league", "young-wr", "picks", "player", "trade"])
    parser.add_argument("id", nargs="?")
    parser.add_argument("--api", default=os.getenv("API_BASE_URL"))
    args = parser.parse_args()
    if not args.api:
        parser.error("--api or API_BASE_URL is required")
    paths = {
        "league": "/analysis/league", "young-wr": "/scan/young-targets?position=WR",
        "picks": "/pick-outlook", "player": f"/analysis/player/{args.id}",
        "trade": f"/recommendation/player/{args.id}",
    }
    response = httpx.get(args.api.rstrip("/") + paths[args.command], timeout=120.0)
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2))


if __name__ == "__main__":
    main()

