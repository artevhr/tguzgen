"""
Username generators.

Two styles:
  random   — fully random alphanumeric+underscore (original behaviour)
  readable — pronounceable / "branded" names inspired by Durov, Galaxy, NFT etc.
"""

import random
import string

# ─── Random style ────────────────────────────────────────────────────────────

_LETTERS = string.ascii_lowercase
_CHARS   = string.ascii_lowercase + string.digits + "_"


def generate_username(length: int) -> str:
    """Fully random username of exact `length`."""
    length = max(2, min(32, length))
    chars = [random.choice(_LETTERS)]
    for _ in range(length - 1):
        pool = _LETTERS + string.digits if chars[-1] == "_" else _CHARS
        chars.append(random.choice(pool))
    while chars and chars[-1] == "_":
        chars[-1] = random.choice(_LETTERS + string.digits)
    return "".join(chars)


def generate_batch(length: int, count: int) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    attempts = 0
    while len(results) < count and attempts < count * 20:
        u = generate_username(length)
        if u not in seen:
            seen.add(u)
            results.append(u)
        attempts += 1
    return results


# ─── Readable / Branded style ────────────────────────────────────────────────

_VOWELS     = list("aeiou")
_CONSONANTS = list("bcdfghjklmnprstvwz")

# Crypto / tech / web3 suffixes and prefixes that feel modern
_TECH_PARTS = [
    "nft", "ton", "eth", "btc", "sol", "dao", "dev",
    "web", "ai",  "io",  "hub", "lab", "bit", "net",
    "meta", "nova", "node", "coin", "pay",
]

# Short nature / space words that sound cool
_NATURE_PARTS = [
    "sky", "sun", "moon", "star", "gal", "orb", "arc",
    "bay", "fox", "oak", "ray", "zen",
]

# Classic melodic syllables (CV or CVC patterns)
def _cv_syllable(long: bool = False) -> str:
    c = random.choice(_CONSONANTS)
    v = random.choice(_VOWELS)
    if long:
        c2 = random.choice(_CONSONANTS)
        return c + v + c2
    return c + v


def _readable_word(length: int) -> str:
    """
    Build a pronounceable word of approximately `length` characters.
    Occasionally anchors around a tech/nature stem.
    """
    length = max(4, min(32, length))

    # 35% chance: use a known stem and pad with syllables
    if random.random() < 0.35:
        stem = random.choice(_TECH_PARTS + _NATURE_PARTS)
        if len(stem) >= length:
            return stem[:length]
        # Pad with CV syllables on either side
        remaining = length - len(stem)
        prefix_len = random.randint(0, remaining)
        suffix_len = remaining - prefix_len
        prefix = ""
        while len(prefix) < prefix_len:
            prefix += _cv_syllable()
        prefix = prefix[:prefix_len]
        suffix = ""
        while len(suffix) < suffix_len:
            suffix += _cv_syllable()
        suffix = suffix[:suffix_len]
        word = prefix + stem + suffix
        # Ensure starts with a letter
        if word and not word[0].isalpha():
            word = random.choice(_LETTERS) + word[1:]
        return word[:length]

    # Pure CV syllable chain
    word = ""
    while len(word) < length:
        use_long = random.random() < 0.3
        word += _cv_syllable(long=use_long)

    word = word[:length]
    # Guarantee starts with a letter
    if word and not word[0].isalpha():
        word = random.choice(_LETTERS) + word[1:]
    return word


def generate_readable_username(length: int) -> str:
    """
    Generate one pronounceable / branded-style username.
    Length 4–32. Occasionally inserts a digit or underscore for variety.
    """
    length = max(4, min(32, length))
    word = _readable_word(length)

    # ~20% chance: replace one non-first character with a digit (e.g. "nova7")
    if len(word) > 4 and random.random() < 0.20:
        pos = random.randint(len(word) // 2, len(word) - 1)
        word = word[:pos] + str(random.randint(0, 9)) + word[pos + 1:]

    # ~10% chance: insert underscore before last segment (e.g. "gal_nova")
    if len(word) > 6 and random.random() < 0.10:
        pos = random.randint(3, len(word) - 3)
        word = word[:pos] + "_" + word[pos + 1:]
        # No trailing underscore
        if word[-1] == "_":
            word = word[:-1] + random.choice(_LETTERS)

    return word[:length]


def generate_readable_batch(length: int, count: int) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    attempts = 0
    while len(results) < count and attempts < count * 30:
        u = generate_readable_username(length)
        if u not in seen:
            seen.add(u)
            results.append(u)
        attempts += 1
    return results
