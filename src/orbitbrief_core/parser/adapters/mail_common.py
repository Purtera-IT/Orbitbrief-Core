from __future__ import annotations

import email
import re
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser, Parser
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, Mapping, Sequence

_HEADER_LINE_RE = re.compile(r"(?im)^(from|to|cc|bcc|subject|date):\s+.*$")
_QUOTED_LINE_RE = re.compile(r"(?m)^>.*$")
_ON_WROTE_RE = re.compile(r"(?im)^On .+ wrote:\s*$")
_FORWARD_RE = re.compile(r"(?im)^[- ]*Forwarded message[- ]*$|^Begin forwarded message:\s*$")
_SIGNATURE_RE = re.compile(r"(?im)^(--\s*$|thanks[,!]?\s*$|best[,!]?\s*$|regards[,!]?\s*$)")
_DISCLAIMER_RE = re.compile(
    r"(?is)(confidential|intended solely|unauthorized|privileged communication|virus disclaimer|opinions expressed)"
)


@dataclass(frozen=True, slots=True)
class MessageBoundaryCandidate:
    message_boundary_id: str
    start_char: int
    end_char: int
    header_fields: Mapping[str, str]
    body_text: str
    confidence: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QuotedBlockCandidate:
    block_id: str
    start_char: int
    end_char: int
    text: str
    confidence: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ForwardedBlockCandidate:
    block_id: str
    start_char: int
    end_char: int
    text: str
    confidence: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SignatureBlockCandidate:
    block_id: str
    start_char: int
    end_char: int
    text: str
    confidence: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DisclaimerBlockCandidate:
    block_id: str
    start_char: int
    end_char: int
    text: str
    confidence: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmailMessageCandidate:
    message_id: str
    headers: Mapping[str, str]
    subject: str | None
    sender: str | None
    sender_name: str | None
    recipient_emails: tuple[str, ...]
    cc_emails: tuple[str, ...]
    date_text: str | None
    date_iso: str | None
    start_char: int
    end_char: int
    body_text: str
    current_text: str
    quoted_blocks: tuple[QuotedBlockCandidate, ...]
    forwarded_blocks: tuple[ForwardedBlockCandidate, ...]
    signature_blocks: tuple[SignatureBlockCandidate, ...]
    disclaimer_blocks: tuple[DisclaimerBlockCandidate, ...]
    confidence: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmailParseResult:
    messages: tuple[EmailMessageCandidate, ...]
    diagnostics: tuple[str, ...] = ()


def _decode_text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def _body_from_message(message: email.message.EmailMessage) -> str:
    if message.is_multipart():
        plain_parts: list[str] = []
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_subtype() != "plain":
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                plain_parts.append(payload.decode(charset, errors="replace"))
            except LookupError:
                plain_parts.append(_decode_text(payload))
        return "\n\n".join(part for part in plain_parts if part.strip())
    payload = message.get_payload(decode=True)
    if payload is None:
        value = message.get_payload()
        return value if isinstance(value, str) else ""
    charset = message.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return _decode_text(payload)


def _normalize_headers(mapping: Mapping[str, str]) -> dict[str, str]:
    return {str(k).lower(): str(v).strip() for k, v in mapping.items() if str(v).strip()}


def _extract_addresses(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for _, email_addr in getaddresses([value]):
        email_addr = email_addr.strip().lower()
        if not email_addr or email_addr in seen:
            continue
        seen.add(email_addr)
        out.append(email_addr)
    return tuple(out)


def _parse_date(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    try:
        dt = parsedate_to_datetime(value)
    except Exception:
        return value, None
    try:
        return value, dt.isoformat()
    except Exception:
        return value, None


def parse_rfc822(raw_bytes: bytes | None = None, text: str | None = None) -> EmailParseResult | None:
    if raw_bytes is None and text is None:
        return None
    try:
        if raw_bytes is not None:
            msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
        else:
            msg = Parser(policy=policy.default).parsestr(text or "")
    except Exception:
        return None
    headers = _normalize_headers(dict(msg.items()))
    if not headers:
        return None
    body_text = _body_from_message(msg)
    message_candidate = build_message_candidate(
        message_id="email_message:000001",
        headers=headers,
        body_text=body_text,
        start_char=0,
        end_char=len(body_text),
        confidence=0.98,
        metadata={"source": "rfc822"},
    )
    return EmailParseResult(messages=(message_candidate,), diagnostics=())


def split_exported_messages(text: str) -> tuple[MessageBoundaryCandidate, ...]:
    boundaries: list[tuple[int, int]] = []
    header_matches = list(_HEADER_LINE_RE.finditer(text))
    candidate_starts: list[int] = []
    for match in header_matches:
        if match.group(1).lower() != "from":
            continue
        candidate_starts.append(match.start())
    if not candidate_starts:
        return (
            MessageBoundaryCandidate(
                message_boundary_id="message_boundary:000001",
                start_char=0,
                end_char=len(text),
                header_fields={},
                body_text=text,
                confidence=0.55,
                metadata={"source": "single_body_fallback"},
            ),
        )
    for index, start in enumerate(candidate_starts):
        end = candidate_starts[index + 1] if index + 1 < len(candidate_starts) else len(text)
        boundaries.append((start, end))
    out: list[MessageBoundaryCandidate] = []
    for idx, (start, end) in enumerate(boundaries, start=1):
        segment = text[start:end].strip()
        header_fields: dict[str, str] = {}
        body_start = 0
        header_lines: list[str] = []
        lines = segment.splitlines()
        for line_idx, line in enumerate(lines):
            if not line.strip():
                body_start = line_idx + 1
                break
            header_match = re.match(r"(?i)^(from|to|cc|bcc|subject|date):\s+(.*)$", line)
            if not header_match:
                break
            header_fields[header_match.group(1).lower()] = header_match.group(2).strip()
            header_lines.append(line)
        body_text = "\n".join(lines[body_start:]).strip() if body_start else segment
        confidence = 0.85 if header_fields else 0.55
        out.append(
            MessageBoundaryCandidate(
                message_boundary_id=f"message_boundary:{idx:06d}",
                start_char=start,
                end_char=end,
                header_fields=header_fields,
                body_text=body_text,
                confidence=confidence,
                metadata={"header_lines": tuple(header_lines)},
            )
        )
    return tuple(out)


def detect_quoted_blocks(text: str, *, char_offset: int = 0) -> tuple[QuotedBlockCandidate, ...]:
    blocks: list[QuotedBlockCandidate] = []
    for idx, match in enumerate(_QUOTED_LINE_RE.finditer(text), start=1):
        line = match.group(0).rstrip()
        blocks.append(
            QuotedBlockCandidate(
                block_id=f"quoted:{idx:06d}",
                start_char=char_offset + match.start(),
                end_char=char_offset + match.end(),
                text=line,
                confidence=0.92,
                metadata={"source": "quoted_line"},
            )
        )
    for idx, match in enumerate(_ON_WROTE_RE.finditer(text), start=len(blocks) + 1):
        start = match.start()
        end = len(text)
        following = text[start:]
        next_blank = re.search(r"\n\n", following)
        if next_blank:
            end = start + next_blank.end()
        blocks.append(
            QuotedBlockCandidate(
                block_id=f"quoted:{idx:06d}",
                start_char=char_offset + start,
                end_char=char_offset + end,
                text=text[start:end].strip(),
                confidence=0.88,
                metadata={"source": "on_wrote"},
            )
        )
    return tuple(blocks)


def detect_forwarded_blocks(text: str, *, char_offset: int = 0) -> tuple[ForwardedBlockCandidate, ...]:
    blocks: list[ForwardedBlockCandidate] = []
    for idx, match in enumerate(_FORWARD_RE.finditer(text), start=1):
        start = match.start()
        block_text = text[start:].strip()
        blocks.append(
            ForwardedBlockCandidate(
                block_id=f"forwarded:{idx:06d}",
                start_char=char_offset + start,
                end_char=char_offset + len(text),
                text=block_text,
                confidence=0.9,
                metadata={"source": "forwarded_marker"},
            )
        )
    return tuple(blocks)


def detect_signature_blocks(text: str, *, char_offset: int = 0) -> tuple[SignatureBlockCandidate, ...]:
    blocks: list[SignatureBlockCandidate] = []
    match = _SIGNATURE_RE.search(text)
    if match:
        blocks.append(
            SignatureBlockCandidate(
                block_id="signature:000001",
                start_char=char_offset + match.start(),
                end_char=char_offset + len(text),
                text=text[match.start():].strip(),
                confidence=0.8,
                metadata={"source": "signature_regex"},
            )
        )
    return tuple(blocks)


def detect_disclaimer_blocks(text: str, *, char_offset: int = 0) -> tuple[DisclaimerBlockCandidate, ...]:
    blocks: list[DisclaimerBlockCandidate] = []
    match = _DISCLAIMER_RE.search(text)
    if match:
        blocks.append(
            DisclaimerBlockCandidate(
                block_id="disclaimer:000001",
                start_char=char_offset + match.start(),
                end_char=char_offset + len(text),
                text=text[match.start():].strip(),
                confidence=0.78,
                metadata={"source": "disclaimer_regex"},
            )
        )
    return tuple(blocks)


def strip_non_authored_context(
    body_text: str,
    quoted_blocks: Sequence[QuotedBlockCandidate],
    forwarded_blocks: Sequence[ForwardedBlockCandidate],
    signature_blocks: Sequence[SignatureBlockCandidate],
    disclaimer_blocks: Sequence[DisclaimerBlockCandidate],
) -> str:
    intervals: list[tuple[int, int]] = []
    for block in (*quoted_blocks, *forwarded_blocks, *signature_blocks, *disclaimer_blocks):
        intervals.append((block.start_char, block.end_char))
    if not intervals:
        return body_text.strip()
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    cursor = 0
    chunks: list[str] = []
    for start, end in merged:
        local_start = max(0, start)
        local_end = max(local_start, end)
        if local_start > cursor:
            chunks.append(body_text[cursor:local_start])
        cursor = max(cursor, local_end)
    if cursor < len(body_text):
        chunks.append(body_text[cursor:])
    return "\n".join(chunk.strip() for chunk in chunks if chunk.strip()).strip()


def build_message_candidate(
    *,
    message_id: str,
    headers: Mapping[str, str],
    body_text: str,
    start_char: int,
    end_char: int,
    confidence: float,
    metadata: Mapping[str, Any] | None = None,
) -> EmailMessageCandidate:
    normalized_headers = _normalize_headers(headers)
    sender_line = normalized_headers.get("from")
    sender_name = None
    sender_email = None
    if sender_line:
        addresses = getaddresses([sender_line])
        if addresses:
            sender_name, sender_email = addresses[0]
            sender_name = sender_name.strip() or None
            sender_email = sender_email.strip().lower() or None
    recipient_emails = _extract_addresses(normalized_headers.get("to"))
    cc_emails = _extract_addresses(normalized_headers.get("cc"))
    date_text, date_iso = _parse_date(normalized_headers.get("date"))

    quoted = detect_quoted_blocks(body_text, char_offset=0)
    forwarded = detect_forwarded_blocks(body_text, char_offset=0)
    signature = detect_signature_blocks(body_text, char_offset=0)
    disclaimer = detect_disclaimer_blocks(body_text, char_offset=0)
    current_text = strip_non_authored_context(body_text, quoted, forwarded, signature, disclaimer)

    return EmailMessageCandidate(
        message_id=message_id,
        headers=normalized_headers,
        subject=normalized_headers.get("subject"),
        sender=sender_email,
        sender_name=sender_name,
        recipient_emails=recipient_emails,
        cc_emails=cc_emails,
        date_text=date_text,
        date_iso=date_iso,
        start_char=start_char,
        end_char=end_char,
        body_text=body_text,
        current_text=current_text,
        quoted_blocks=quoted,
        forwarded_blocks=forwarded,
        signature_blocks=signature,
        disclaimer_blocks=disclaimer,
        confidence=confidence,
        metadata=dict(metadata or {}),
    )


def parse_email_artifact(text: str, *, raw_bytes: bytes | None = None) -> EmailParseResult:
    diagnostics: list[str] = []
    rfc822_result = parse_rfc822(raw_bytes=raw_bytes, text=text)
    if rfc822_result is not None:
        diagnostics.append("parsed_via_rfc822")
        return EmailParseResult(messages=rfc822_result.messages, diagnostics=tuple(diagnostics))

    boundaries = split_exported_messages(text)
    messages: list[EmailMessageCandidate] = []
    for index, boundary in enumerate(boundaries, start=1):
        messages.append(
            build_message_candidate(
                message_id=f"email_message:{index:06d}",
                headers=boundary.header_fields,
                body_text=boundary.body_text,
                start_char=boundary.start_char,
                end_char=boundary.end_char,
                confidence=boundary.confidence,
                metadata={"boundary_id": boundary.message_boundary_id, **dict(boundary.metadata)},
            )
        )
    if len(messages) > 1:
        diagnostics.append("parsed_as_exported_thread")
    else:
        diagnostics.append("single_message_fallback")
    return EmailParseResult(messages=tuple(messages), diagnostics=tuple(diagnostics))
