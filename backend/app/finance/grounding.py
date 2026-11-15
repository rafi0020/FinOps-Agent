"""Checks that the numbers in a report exist in the evidence.

A language model can state a figure it never retrieved. Telling it not to is not a guarantee, so the report
is checked after it is written: every number in the summary and the findings must match a value in a stored
query result or calculation. A sentence containing a number with no source is removed from the report and
listed for the reader as unsupported.

This is a safety net with known limits: it proves a number exists in the evidence, not that the sentence
around it describes that number correctly. Small common values can match by coincidence.
"""

import re
from bisect import bisect_left
from dataclasses import dataclass, field

from app.models.runs import HANDLE_PATTERN

HANDLE = re.compile(rf"\b{HANDLE_PATTERN}\b")
DATE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")
QUARTER = re.compile(r"\b(?:\d{4}[- ]?Q[1-4]|Q[1-4][- ]?\d{4}|Q[1-4]|[HF]Y?\d{2,4}|H[12])\b", re.IGNORECASE)
ORDINAL = re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.IGNORECASE)
NUMBER = re.compile(
    r"""(?<![\w.])                                   # not inside a word or another number
        (?P<sign>[-−+])?\s?(?P<currency>[$€£])?\s?
        (?P<digits>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)
        \s?(?P<suffix>%|percent\b|percentage\ points?|pp\b|points?\b|bps\b|[KkMmBb]n?\b|thousand\b|million\b|billion\b|days?\b)?
    """,
    re.VERBOSE,
)
SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
RANGE = re.compile(r"(\d(?:[\d,]*\d)?(?:\.\d+)?)(\s?(?:-|–|to)\s?)(\d(?:[\d,]*\d)?(?:\.\d+)?\s?%)")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9$(\[])")
RELATIVE_TOLERANCE = 0.005


@dataclass
class NumberRef:
    text: str
    value: float
    handle: str


@dataclass
class GroundingResult:
    supported: list[NumberRef] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)  # sentences that were removed
    cleaned: str = ""


@dataclass
class Mention:
    text: str
    candidates: list[tuple[float, float]]  # (magnitude, absolute tolerance from the printed precision)
    sign: int = 0  # -1 or +1 when written with a sign that is a sign (not a hyphen between numbers), else 0


def _is_sign(text: str, position: int) -> bool:
    """A minus is a sign when it starts the text or follows a space or bracket: '-5%', 'fell (-5%)'.
    After a digit or letter it is a range or a hyphen: '20-25 days', 'Q3-2026'."""
    return position == 0 or not (text[position - 1].isalnum() or text[position - 1] in ".%)")


def extract_numbers(text: str) -> list[Mention]:
    """Numbers a reader would take as facts. Years, dates, quarters, ordinals and small bare counts are skipped."""
    blanked = text
    for pattern in (HANDLE, DATE, QUARTER, ORDINAL):
        blanked = pattern.sub(lambda m: " " * len(m.group()), blanked)
    blanked = RANGE.sub(r"\1% \3", blanked)  # "30.8-31.0%" states two percentages
    mentions = []
    for m in NUMBER.finditer(blanked):
        digits, suffix, currency = m.group("digits"), (m.group("suffix") or "").lower(), m.group("currency")
        value = float(digits.replace(",", ""))
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        half_unit = 0.5 * 10**-decimals
        bare = not suffix and not currency
        if bare and decimals == 0 and "," not in digits:
            if 1900 <= value <= 2100 or value <= 31:  # a year, or a small count such as "3 regions"
                continue
            if digits.startswith("0"):  # part of a name or code, such as "Customer 0179"
                continue
        if suffix in ("%", "percent", "pp", "bps") or suffix.startswith(("percentage", "point")):
            divisor = 10_000 if suffix == "bps" else 100
            candidates = [(value / divisor, half_unit / divisor), (value, half_unit)]
        elif suffix in SCALE:
            candidates = [(value * SCALE[suffix], half_unit * SCALE[suffix])]
        else:
            candidates = [(value, half_unit)]
        sign = 0
        if m.group("sign") and _is_sign(blanked, m.start("sign")):
            sign = -1 if m.group("sign") in "-−" else 1
        mentions.append(Mention(m.group().strip(), candidates, sign))
    return mentions


class EvidencePool:
    """Every numeric value in the evidence, searchable by magnitude and sign."""

    def __init__(self, evidence: list[tuple[str, dict]]):
        self._entries = list(evidence)
        self._restricted: dict[frozenset, EvidencePool] = {}
        found: list[tuple[float, str, bool]] = []  # (magnitude, handle, negative)
        self._text: list[str] = []
        for handle, payload in evidence:
            self._collect(payload, handle, found)
        found.sort()
        self._values = [v for v, _, _ in found]
        self._handles = [h for _, h, _ in found]
        self._negative = [n for _, _, n in found]

    def restricted(self, handles: set[str]) -> "EvidencePool":
        """The same evidence, limited to the given handles (what a sentence that cites them may be checked against)."""
        key = frozenset(handles)
        if key not in self._restricted:
            self._restricted[key] = EvidencePool([(h, p) for h, p in self._entries if h in key])
        return self._restricted[key]

    def _collect(self, node, handle: str, found: list) -> None:
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, str):
            self._text.append(node)
        elif isinstance(node, int | float):
            if node == node and abs(node) != float("inf"):
                found.append((abs(float(node)), handle, node < 0))
        elif isinstance(node, dict):
            for value in node.values():
                self._collect(value, handle, found)
        elif isinstance(node, list | tuple):
            for value in node:
                self._collect(value, handle, found)

    def names(self, digits: str) -> bool:
        """True when a bare whole number is part of a text value in the evidence, e.g. the 4410 in "SKU 4410"."""
        return any(digits in text for text in self._text)

    def find(self, value: float, tolerance: float, sign: int = 0) -> str | None:
        """The handle of a stored value with this magnitude (within tolerance) and, when sign is set, this sign.

        A figure written with an explicit minus must match a negative value; one written with a plus must match a
        value that is not negative; an unsigned figure matches either, because prose states changes as magnitudes.
        """
        target = abs(value)
        slack = max(tolerance, RELATIVE_TOLERANCE * target) + 1e-12
        i = bisect_left(self._values, target - slack)
        while i < len(self._values) and self._values[i] <= target + slack:
            negative = self._negative[i]
            if sign == 0 or (sign < 0) == negative:
                return self._handles[i]
            i += 1
        return None


def check_text(text: str, pool: EvidencePool, scope: EvidencePool | None = None) -> GroundingResult:
    """Remove sentences that state a number the evidence does not contain.

    A sentence that cites handles (ev_...) is checked only against the results it cites, looked up in `scope`
    (every result of the run) or else in `pool`. A sentence without a handle is checked against the whole pool.
    """
    result = GroundingResult()
    kept = []
    for sentence in (s for s in SENTENCE_END.split(text.strip()) if s):
        cited = set(HANDLE.findall(sentence))
        if cited:
            checked_against = (scope or pool).restricted(cited)
        else:
            checked_against = pool
        refs, missing = [], False
        for mention in extract_numbers(sentence):
            handle = next((h for v, t in mention.candidates if (h := checked_against.find(v, t, mention.sign))), None)
            if handle is None and mention.text.isdigit() and pool.names(mention.text):
                continue  # digits inside a name the evidence contains are not a figure
            if handle is None:
                missing = True
                break
            refs.append(NumberRef(mention.text, mention.candidates[0][0], handle))
        if missing:
            result.unsupported.append(sentence)
        else:
            kept.append(sentence)
            result.supported.extend(refs)
    result.cleaned = " ".join(kept)
    return result
