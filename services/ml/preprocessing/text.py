"""Light clean-up of note text before the sentiment model sees it.

Only whitespace and length (the vectoriser lowercases). Training applies the same function, so
the model sees text shaped the same way in both. Nothing here is logged.
"""

import re
from typing import Final

MAX_NOTE_CHARS: Final = 2000
_SPACE: Final = re.compile(r"\s+")


def clean(text: str) -> str:
    return _SPACE.sub(" ", text).strip()[:MAX_NOTE_CHARS]
