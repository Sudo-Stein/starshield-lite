"""Future Meshtastic / external alert hooks.

This module is a stub for later integration with Meshtastic or other
notification channels (email, webhook, etc.).
"""


def send_alert(message: str, channel: str = "console") -> None:
    """Dispatch an alert. Currently prints to console only."""
    print(f"[ALERT:{channel}] {message}")
