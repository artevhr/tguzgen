"""
Username generators.

Styles:   random | readable
Filters:  standard | no_digits | letters_only
"""

import random
import string

_LETTERS    = string.ascii_lowercase
_DIGITS     = string.digits
_CHARS_STD  = _LETTERS + _DIGITS + "_"   # standard
_CHARS_ND   = _LETTERS + "_"             # no digits
_CHARS_LO   = _LETTERS                   # letters only

_VOWELS     = list("aeiou")
_CONSONANTS = list("bcdfghjklmnprstvwz")

_TECH_PARTS = [
    "nft", "ton", "eth", "btc", "sol", "dao", "dev",
    "web", "ai",  "io",  "hub", "lab", "bit", "net",
    "meta", "nova", "node", "coin", "pay", "app", "pro",
    "crypt", "block", "chain", "dapp", "swap", "lend",
    "stake", "cloud", "edge", "data", "code", "api",
    "sdk", "bot", "flow", "sync", "mesh", "p2p", "vpn",
    "byte", "hash", "key", "wallet", "token", "node2",
    "stack", "repo", "git", "url", "dns", "cdn", "app2",
    "web3", "zero", "proof", "zksync", "bridge",
]
_NATURE_PARTS = [
    "sky", "sun", "moon", "star", "gal", "orb", "arc",
    "bay", "fox", "oak", "ray", "zen", "fly", "ace",
    "claw", "fang", "peak", "glow", "frost", "moss",
    "fern", "stone", "cave", "wave", "tide", "storm",
    "flare", "spark", "blaze", "shard", "thorn", "root",
    "leaf", "petal", "ash", "ember", "cinder", "dune",
    "cliff", "ridge", "vale", "brook", "creek", "pine",
    "birch", "raven", "hawk", "wolf", "lynx", "fawn",
    "buck", "stag", "willow", "ivy",
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _pool(filter_: str) -> str:
    if filter_ == "letters_only":
        return _CHARS_LO
    if filter_ == "no_digits":
        return _CHARS_ND
    return _CHARS_STD


def _safe_pool(filter_: str, after_underscore: bool = False) -> str:
    """Pool to use when previous char was underscore (can't be another _ or digit start)."""
    if after_underscore or filter_ in ("letters_only", "no_digits"):
        return _CHARS_LO  # always safe: just letters
    return _LETTERS + _DIGITS


def _cv_syllable(long: bool = False) -> str:
    c = random.choice(_CONSONANTS)
    v = random.choice(_VOWELS)
    return (c + v + random.choice(_CONSONANTS)) if long else (c + v)


# ─── Random style ─────────────────────────────────────────────────────────────

def generate_username(length: int, filter_: str = "standard") -> str:
    length = max(2, min(32, length))
    pool = _pool(filter_)
    chars = [random.choice(_LETTERS)]  # always start with letter
    for _ in range(length - 1):
        prev = chars[-1]
        p = _safe_pool(filter_, after_underscore=(prev == "_")) if prev == "_" else pool
        chars.append(random.choice(p))
    # no trailing underscore
    while chars[-1] == "_":
        chars[-1] = random.choice(_LETTERS + (_DIGITS if filter_ == "standard" else ""))
    return "".join(chars)


def generate_batch(length: int, count: int, filter_: str = "standard") -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    attempts = 0
    while len(results) < count and attempts < count * 25:
        u = generate_username(length, filter_)
        if u not in seen:
            seen.add(u)
            results.append(u)
        attempts += 1
    return results


# ─── Readable / Branded style ─────────────────────────────────────────────────

def _readable_word(length: int) -> str:
    """Pure syllable-chain word (letters only by nature)."""
    length = max(4, min(32, length))

    if random.random() < 0.35:
        stem = random.choice(_TECH_PARTS + _NATURE_PARTS)
        if len(stem) >= length:
            return stem[:length]
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
        if word and not word[0].isalpha():
            word = random.choice(_LETTERS) + word[1:]
        return word[:length]

    word = ""
    while len(word) < length:
        word += _cv_syllable(long=random.random() < 0.3)
    word = word[:length]
    if word and not word[0].isalpha():
        word = random.choice(_LETTERS) + word[1:]
    return word


def generate_readable_username(length: int, filter_: str = "standard") -> str:
    length = max(4, min(32, length))
    word = _readable_word(length)

    if filter_ == "standard":
        # ~20% digit
        if len(word) > 4 and random.random() < 0.20:
            pos = random.randint(len(word) // 2, len(word) - 1)
            word = word[:pos] + str(random.randint(0, 9)) + word[pos + 1:]
        # ~10% underscore
        if len(word) > 6 and random.random() < 0.10:
            pos = random.randint(3, len(word) - 3)
            word = word[:pos] + "_" + word[pos + 1:]
            if word[-1] == "_":
                word = word[:-1] + random.choice(_LETTERS)

    elif filter_ == "no_digits":
        # ~10% underscore only, no digits
        if len(word) > 6 and random.random() < 0.10:
            pos = random.randint(3, len(word) - 3)
            word = word[:pos] + "_" + word[pos + 1:]
            if word[-1] == "_":
                word = word[:-1] + random.choice(_LETTERS)

    # letters_only: _readable_word is already pure letters, nothing to add

    return word[:length]


def generate_readable_batch(length: int, count: int, filter_: str = "standard") -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    attempts = 0
    while len(results) < count and attempts < count * 30:
        u = generate_readable_username(length, filter_)
        if u not in seen:
            seen.add(u)
            results.append(u)
        attempts += 1
    return results


# ─── Unified dispatch ─────────────────────────────────────────────────────────

def gen_one(style: str, length: int, filter_: str) -> str:
    if style == "readable":
        return generate_readable_username(length, filter_)
    return generate_username(length, filter_)


def gen_batch(style: str, length: int, count: int, filter_: str) -> list[str]:
    if style == "readable":
        return generate_readable_batch(length, count, filter_)
    return generate_batch(length, count, filter_)
