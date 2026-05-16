"""
Traffic sniffer: launches the browser and dumps every Discord API request
and response so we can reverse-engineer the exact headers/params the web
client uses. Run this, navigate to a channel, and the full request/response
trace gets written to output/traffic.jsonl.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

from src.config import Config
from src.browser import launch_authenticated_context


OUTPUT_DIR = Path("output")


async def run(config_path: Path) -> None:
    config = Config.from_file(config_path)

    traffic_path = OUTPUT_DIR / "traffic.jsonl"
    traffic_path.parent.mkdir(parents=True, exist_ok=True)
    print("[ascension] launching browser...")

    context, page, token, super_properties = await launch_authenticated_context(
        profile_path=config.profile_path,
        headless=False,
        wait_for_auth_seconds=config.wait_for_auth_seconds,
    )

    print("[ascension] traffic sniffer active. Navigate to a channel in Discord.")
    print("[ascension] all /api/* requests will be logged.")
    print("[ascension] close the browser window when done (Ctrl+C in terminal).")

    try:
        with open(traffic_path, "a") as traffic_file:
            async def _log_request(request):
                url = request.url
                if "/api/" not in url:
                    return
                headers = await request.all_headers()
                safe_headers = {k: "<redacted>" if k.lower() == "authorization" else v for k, v in headers.items()}
                post_data = request.post_data

                entry = {
                    "type": "request",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "method": request.method,
                    "url": url,
                    "headers": safe_headers,
                    "post_data": post_data,
                }
                traffic_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
                traffic_file.flush()
                print(f"  -> {request.method} {url}")

            async def _log_response(response):
                url = response.url
                if "/api/" not in url:
                    return
                try:
                    body = await response.text()
                except Exception:
                    body = "<unreadable>"

                response_headers = await response.all_headers()
                safe_response_headers = {k: "<redacted>" if k.lower() == "authorization" else v for k, v in response_headers.items()}

                entry = {
                    "type": "response",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": response.status,
                    "url": url,
                    "headers": safe_response_headers,
                    "body": body[:2000],
                }
                traffic_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
                traffic_file.flush()
                print(f"  <- {response.status} {url}")

            context.on("request", _log_request)
            context.on("response", _log_response)

            # Keep alive until user closes the browser or hits Ctrl+C
            while True:
                await asyncio.sleep(1)
                alive_pages = [p for p in context.pages if not p.is_closed()]
                if not alive_pages:
                    print("[ascension] browser closed, exiting")
                    break
    except KeyboardInterrupt:
        print("\n[ascension] interrupted")
    finally:
        await context.close()
        print(f"[ascension] traffic log written to {traffic_path}")


def main() -> None:
    if len(sys.argv) < 2:
        config_path = Path("config.json")
    else:
        config_path = Path(sys.argv[1])

    if not config_path.exists():
        print(f"[ascension] config not found: {config_path}")
        print("[ascension] copy config.json.template to config.json and edit it")
        sys.exit(1)

    asyncio.run(run(config_path))


if __name__ == "__main__":
    main()
