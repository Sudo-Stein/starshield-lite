import hashlib
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_DIR


class ImmutableLog:
    """SteinRig-style append-only log with a simple tamper-evident hash."""

    def __init__(self, log_file: str = "starshield.log"):
        self.log_path = DATA_DIR / log_file
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: dict) -> str:
        timestamp = datetime.now(timezone.utc).isoformat()
        entry_str = f"{timestamp} | {entry}\n"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(entry_str)

        # Simple tamper-evident hash of the full log so far
        with open(self.log_path, "rb") as f:
            hash_val = hashlib.sha256(f.read()).hexdigest()[:16]
        print(f"Logged [hash: {hash_val}]")
        return hash_val
