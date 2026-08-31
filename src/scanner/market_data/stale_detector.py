"""Track WebSocket topic silence without coupling transport to storage policy."""

import time


class StaleStreamDetector:
    """Detect subscribed kline topics that have exceeded a silence threshold."""

    def __init__(self, max_silence_seconds: int = 70) -> None:
        """Create a detector with the configured maximum message silence period."""
        if max_silence_seconds <= 0:
            raise ValueError("max_silence_seconds must be greater than zero")
        self._max_silence_seconds = max_silence_seconds
        self._last_seen: dict[str, float] = {}

    def watch_topic(self, symbol: str, interval: str) -> None:
        """Begin monitoring a topic from the time it is subscribed."""
        self._last_seen.setdefault(self._topic(symbol, interval), time.monotonic())

    def remove_topic(self, symbol: str, interval: str) -> None:
        """Stop monitoring an unsubscribed kline topic."""
        self._last_seen.pop(self._topic(symbol, interval), None)

    def record_message(self, symbol: str, interval: str) -> None:
        """Record a received message for a kline topic."""
        self._last_seen[self._topic(symbol, interval)] = time.monotonic()

    def get_stale_topics(self) -> list[str]:
        """Return topics whose latest message exceeds the silence threshold."""
        now = time.monotonic()
        return sorted(
            topic
            for topic, last_seen in self._last_seen.items()
            if now - last_seen > self._max_silence_seconds
        )

    def is_stale(self, symbol: str, interval: str) -> bool:
        """Return whether a monitored topic has exceeded its silence threshold."""
        topic = self._topic(symbol, interval)
        last_seen = self._last_seen.get(topic)
        return (
            last_seen is None
            or time.monotonic() - last_seen > self._max_silence_seconds
        )

    @staticmethod
    def _topic(symbol: str, interval: str) -> str:
        """Format a Bybit public kline topic name."""
        return f"kline.{interval}.{symbol}"
