from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class RedactionResult:
    redacted_text: str
    vault: dict[str, str]
    counts: dict[str, int]


@dataclass
class _VaultBuilder:
    vault: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    _value_to_token: dict[tuple[str, str], str] = field(default_factory=dict)

    def token(self, pii_type: str, original: str) -> str:
        key = (pii_type, original)
        existing = self._value_to_token.get(key)
        if existing is not None:
            return existing
        n = self.counts.get(pii_type, 0) + 1
        self.counts[pii_type] = n
        tok = f"[{pii_type}_{n}]"
        self.vault[tok] = original
        self._value_to_token[key] = tok
        return tok


_ZIP_LINE_RE = re.compile(
    r"^.+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*$",
    re.IGNORECASE,
)
_ALLCAPS_NAME_RE = re.compile(
    r"^([A-Z][A-Z\-']+),\s+([A-Z][A-Z\-']+(?:\s+[A-Z][A-Z\-']+)*)$"
)
_LABEL_NAME_RE = re.compile(
    r"(?im)^(Petitioner|Beneficiary|Applicant|Client Name|To)\s*:\s*(.+?)\s*$"
)
_A_NUMBER_RE = re.compile(
    r"\bA#\d{8,9}\b"
    r"|\bA\d{8,9}\b"
    r"|\bA[-\s]?\d{3}[-\s]\d{3}[-\s]\d{3}\b",
    re.IGNORECASE,
)
_BARE_A_NUMBER_RE = re.compile(
    r"(?i)(?:Case\s*No\.?\s*:?\s*|FILE\s+A\s+)(\d{3}-\d{3}-\d{3})\b"
)
_SSN_RE = re.compile(r"(?<![\w])\d{3}-\d{2}-\d{4}(?![\w])")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?<![\w])(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}(?![\w])"
)
_PASSPORT_RE = re.compile(r"\b[A-Z]\d{7,8}\b", re.IGNORECASE)
_I94_RE = re.compile(r"(?<![\w])\d{11}(?![\w])")
_DOB_DATE_RE = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
    r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b",
    re.IGNORECASE,
)
_PASSPORT_CONTEXT_RE = re.compile(r"passport", re.IGNORECASE)
_I94_CONTEXT_RE = re.compile(r"I-?\s*94", re.IGNORECASE)
_DOB_CONTEXT_RE = re.compile(r"date\s+of\s+birth|\bDOB\b", re.IGNORECASE)
_ADDRESSY_RE = re.compile(r"\d")


def _title_first_last(last: str, rest: str) -> str:
    return " ".join(part.capitalize() for part in rest.split()) + " " + last.capitalize()


def _find_client_names(text: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        cleaned = name.strip().rstrip(",")
        if not cleaned or cleaned in seen:
            return
        if "[" in cleaned:
            return
        seen.add(cleaned)
        names.append(cleaned)

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "In the Matter of:" not in line:
            continue
        for j in range(i + 1, min(i + 6, len(lines))):
            match = _ALLCAPS_NAME_RE.match(lines[j].strip())
            if match:
                add(lines[j].strip())
                break

    for match in _LABEL_NAME_RE.finditer(text):
        value = match.group(2).strip()
        if _ALLCAPS_NAME_RE.match(value) or re.match(
            r"^[A-Za-z][A-Za-z\-']+(?:\s+[A-Za-z][A-Za-z\-']+)+$", value
        ):
            add(value)

    return names


def _court_header_address_lines(lines: list[str], matter_idx: int) -> list[str]:
    zip_idx = None
    for i in range(matter_idx):
        if _ZIP_LINE_RE.match(lines[i].strip()):
            zip_idx = i
            break
    if zip_idx is None:
        return []
    start = 0
    for i in range(zip_idx):
        if "IMMIGRATION COURT" in lines[i].upper():
            start = i + 1
    return [lines[i].strip() for i in range(start, zip_idx + 1) if lines[i].strip()]


def _find_client_addresses(text: str, client_names: list[str]) -> list[str]:
    lines = text.splitlines()
    matter_idx = next(
        (i for i, line in enumerate(lines) if "In the Matter of:" in line),
        None,
    )
    if matter_idx is None:
        return []

    zip_idx = None
    for i in range(matter_idx):
        if _ZIP_LINE_RE.match(lines[i].strip()):
            zip_idx = i
            break
    if zip_idx is None:
        return []

    recipient = [lines[i].strip() for i in range(zip_idx + 1, matter_idx) if lines[i].strip()]
    if not recipient:
        return []

    client_upper = {name.upper() for name in client_names}
    if recipient[0].upper() not in client_upper:
        return []

    court_lines = {line.upper() for line in _court_header_address_lines(lines, matter_idx)}
    addresses: list[str] = []
    for line in recipient[1:]:
        if line.upper() in court_lines:
            continue
        if _ADDRESSY_RE.search(line) or _ZIP_LINE_RE.match(line):
            addresses.append(line)
    return addresses


def _name_variants(name: str) -> list[str]:
    variants = [name]
    match = _ALLCAPS_NAME_RE.match(name)
    if match:
        last, rest = match.group(1), match.group(2)
        variants.append(_title_first_last(last, rest))
        variants.append(f"{rest} {last}")
    else:
        parts = name.split()
        if len(parts) >= 2:
            last = parts[-1]
            rest = " ".join(parts[:-1])
            variants.append(f"{last.upper()}, {rest.upper()}")
            variants.append(_title_first_last(last, rest))
    # longest first so "FIRST MIDDLE LAST" wins over shorter pieces
    return sorted(set(variants), key=len, reverse=True)


def _replace_ci(text: str, original: str, replacement: str) -> str:
    pattern = re.compile(re.escape(original), re.IGNORECASE)
    return pattern.sub(replacement, text)


def _sub_regex(
    text: str,
    pattern: re.Pattern[str],
    pii_type: str,
    builder: _VaultBuilder,
    *,
    group: int = 0,
) -> str:
    def repl(match: re.Match[str]) -> str:
        original = match.group(group)
        token = builder.token(pii_type, original)
        if group == 0:
            return token
        start, end = match.span(group)
        return match.group(0)[: start - match.start()] + token + match.group(0)[end - match.start() :]

    return pattern.sub(repl, text)


def _sub_near_context(
    text: str,
    context_re: re.Pattern[str],
    value_re: re.Pattern[str],
    pii_type: str,
    builder: _VaultBuilder,
    window: int = 80,
) -> str:
    replacements: list[tuple[int, int, str]] = []
    occupied = [False] * len(text)
    for ctx in context_re.finditer(text):
        left = max(0, ctx.start() - window)
        right = min(len(text), ctx.end() + window)
        for match in value_re.finditer(text[left:right]):
            abs_start = left + match.start()
            abs_end = left + match.end()
            if any(occupied[abs_start:abs_end]):
                continue
            original = text[abs_start:abs_end]
            token = builder.token(pii_type, original)
            replacements.append((abs_start, abs_end, token))
            for i in range(abs_start, abs_end):
                occupied[i] = True
    for start, end, token in sorted(replacements, key=lambda item: item[0], reverse=True):
        text = text[:start] + token + text[end:]
    return text


def _redact_dob(text: str, builder: _VaultBuilder) -> str:
    """Redact dates on the same line, after DOB label, within 20 characters."""
    parts = text.split("\n")
    for i, line in enumerate(parts):
        replacements: list[tuple[int, int, str]] = []
        occupied = [False] * len(line)
        for ctx in _DOB_CONTEXT_RE.finditer(line):
            region_start = ctx.end()
            region_end = min(len(line), region_start + 20)
            region = line[region_start:region_end]
            for match in _DOB_DATE_RE.finditer(region):
                abs_start = region_start + match.start()
                abs_end = region_start + match.end()
                if any(occupied[abs_start:abs_end]):
                    continue
                original = line[abs_start:abs_end]
                token = builder.token("DOB", original)
                replacements.append((abs_start, abs_end, token))
                for j in range(abs_start, abs_end):
                    occupied[j] = True
        for start, end, token in sorted(replacements, key=lambda item: item[0], reverse=True):
            line = line[:start] + token + line[end:]
        parts[i] = line
    return "\n".join(parts)


def redact(text: str) -> RedactionResult:
    builder = _VaultBuilder()
    client_names = _find_client_names(text)
    addresses = _find_client_addresses(text, client_names)

    redacted = text
    redacted = _sub_regex(redacted, _A_NUMBER_RE, "A_NUMBER", builder)
    redacted = _sub_regex(redacted, _BARE_A_NUMBER_RE, "A_NUMBER", builder, group=1)
    redacted = _sub_regex(redacted, _SSN_RE, "SSN", builder)
    redacted = _sub_near_context(
        redacted, _PASSPORT_CONTEXT_RE, _PASSPORT_RE, "PASSPORT", builder
    )
    redacted = _sub_near_context(redacted, _I94_CONTEXT_RE, _I94_RE, "I94", builder)
    redacted = _redact_dob(redacted, builder)
    redacted = _sub_regex(redacted, _EMAIL_RE, "EMAIL", builder)
    redacted = _sub_regex(redacted, _PHONE_RE, "PHONE", builder)

    for name in client_names:
        token = builder.token("CLIENT_NAME", name)
        for variant in _name_variants(name):
            redacted = _replace_ci(redacted, variant, token)

    for address in sorted(addresses, key=len, reverse=True):
        token = builder.token("ADDRESS", address)
        redacted = _replace_ci(redacted, address, token)

    return RedactionResult(
        redacted_text=redacted,
        vault=dict(builder.vault),
        counts=dict(builder.counts),
    )
