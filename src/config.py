"""
Configuration management for the ascension Discord scraper.
Loads settings from a JSON file and exposes them as typed fields.
"""

from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import List


_DEFAULT_PROFILE = Path(".playwright-profile")


@dataclass
class ServerConfig:
    name: str
    channels: List[str]  # channel IDs to scrape


@dataclass
class Config:
    profile_path: Path
    servers: List[ServerConfig]
    wait_for_auth_seconds: int = 120

    @classmethod
    def from_file(cls, path: Path) -> "Config":
        with open(path) as file:
            data = json.load(file)

        profile_path = Path(data.get("profile_path", str(_DEFAULT_PROFILE)))
        profile_path = profile_path.expanduser()

        servers = [
            ServerConfig(
                name=server["name"],
                channels=server["channels"],
            )
            for server in data.get("servers", [])
        ]

        return cls(
            profile_path=profile_path,
            servers=servers,
            wait_for_auth_seconds=data.get("wait_for_auth_seconds", 120),
        )
