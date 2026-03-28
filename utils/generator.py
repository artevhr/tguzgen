import random
import string

_LETTERS = string.ascii_lowercase
_CHARS = string.ascii_lowercase + string.digits + "_"


def generate_username(length: int) -> str:
    """Generate a random Telegram-style username of given length."""
    length = max(2, min(32, length))
    # Must start with a letter
    chars = [random.choice(_LETTERS)]
    for _ in range(length - 1):
        # Avoid consecutive underscores
        if chars[-1] == "_":
            chars.append(random.choice(_LETTERS + string.digits))
        else:
            chars.append(random.choice(_CHARS))
    # No trailing underscore
    while chars and chars[-1] == "_":
        chars[-1] = random.choice(_LETTERS + string.digits)
    return "".join(chars)


def generate_batch(length: int, count: int) -> list[str]:
    """Generate a batch of unique usernames."""
    seen: set[str] = set()
    results: list[str] = []
    attempts = 0
    max_attempts = count * 20
    while len(results) < count and attempts < max_attempts:
        u = generate_username(length)
        if u not in seen:
            seen.add(u)
            results.append(u)
        attempts += 1
    return results
