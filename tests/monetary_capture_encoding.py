"""Private raw-capture encoding; independent of financial snapshot budgets."""

import json

MAX_CAPTURE_BYTES = 4 * 1024 * 1024
MAX_PACKET_BYTES = 64 * 1024 * 1024


def encode_monetary_capture(value: object, *, packet: bool = False) -> bytes:
    """Encode deterministic UTF-8 JSON with its final newline inside the budget."""
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    maximum = MAX_PACKET_BYTES if packet else MAX_CAPTURE_BYTES
    if len(encoded) > maximum:
        raise ValueError("Private monetary capture exceeds its declared raw JSON budget.")
    return encoded
