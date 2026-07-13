#!/usr/bin/env python3
"""Pre-commit gate: block files containing private vocabulary.

The blocklist is stored as salted SHA-256 digests, not plaintext — a
tracked guard file that enumerates the very terms it suppresses would
itself be a leak. Each candidate token in a scanned file is hashed the
same way and compared against the digest set.

Exit 1 (with file:line and a masked preview) on any hit; exit 0 clean.
Usage: vocab_scrub.py FILE [FILE ...]   (pre-commit passes filenames)
"""
from __future__ import annotations

import hashlib
import re
import sys

_SALT = "patrick-agent-vocab-v1"

# sha256(salt + lowercased_token) for each blocked term. These are
# one-way digests of the blocklist, not credentials.
_BLOCKED_DIGESTS = {
    "0d9e579e6ac39abfdc40fec0c0918e0ca2dfcfe2d06e8b995f220cc68e049665",  # pragma: allowlist secret
    "ba76d96640b54c745ddbfb299b395847c23ae1f80ad935aeaa212098fc622544",  # pragma: allowlist secret
    "5a06af1d0b1da14eff2051c3f2955352494a624e050ae885650fa2335bf7d1d4",  # pragma: allowlist secret
    "823803997da3632ac03a1271d7fded15f83eb99ff2e3981005d9e53928a7a659",  # pragma: allowlist secret
    "c43d50a234bc74005b3a7d28f4a26191d396d902e554d5acd600b4f9dbf398a1",  # pragma: allowlist secret
    "2a0701f2cf1586213683569bcc0ea6c3a282156dd2f80ec017c6fd0027c103af",  # pragma: allowlist secret
}

_SCAN_SUFFIXES = (
    ".py", ".md", ".yaml", ".yml", ".toml", ".json", ".jsonl",
    ".sh", ".txt", ".cfg", ".ini",
)

# Words are runs of letters/digits — "com.benai.foo" and "BenAi_local"
# both tokenize so the parts are checked individually.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _digest(token: str) -> str:
    return hashlib.sha256((_SALT + token.lower()).encode()).hexdigest()


def _mask(token: str) -> str:
    return token[0] + "*" * (len(token) - 1)


def scan_file(path: str) -> list[str]:
    hits: list[str] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                for token in _TOKEN_RE.findall(line):
                    if _digest(token) in _BLOCKED_DIGESTS:
                        hits.append(f"{path}:{lineno}: blocked term {_mask(token)}")
    except OSError as exc:
        hits.append(f"{path}: unreadable ({exc})")
    return hits


def main(argv: list[str]) -> int:
    hits: list[str] = []
    for path in argv:
        if path.endswith(_SCAN_SUFFIXES) and not path.endswith("vocab_scrub.py"):
            hits.extend(scan_file(path))
    if hits:
        print("Private vocabulary found:")
        print("\n".join(hits))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
