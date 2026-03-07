"""Human-friendly labels for note files shown in bot replies."""

from __future__ import annotations

import re
from pathlib import Path

_STAMPED_NOTE_PATTERN = re.compile(
    r"^\d{8}-\d{4}\s*-\s*(.+?)(?:\s+\([A-Z0-9]{8}\))?$",
    re.IGNORECASE,
)


def humanize_note_label(file_name: str) -> str:
    base_name = Path(file_name).name or file_name
    raw_stem = Path(file_name).stem.strip()
    cleaned = raw_stem
    matched_stamped = False

    stamped_match = _STAMPED_NOTE_PATTERN.fullmatch(raw_stem)
    if stamped_match:
        cleaned = stamped_match.group(1).strip()
        matched_stamped = True

    if matched_stamped and re.fullmatch(r"note(?:\s+\S+)?", cleaned, re.IGNORECASE):
        return "Сохранённая заметка"

    lowered = cleaned.lower()
    if lowered.startswith(("http ", "https ", "www ")):
        compact = lowered.replace("https ", "").replace("http ", "").replace("www ", "")
        compact = compact.split()[0].strip("/:-")
        if compact:
            host = compact.split("/")[0].split("?")[0]
            host = host.replace("m.youtube.com", "youtube").replace("youtube.com", "youtube")
            return f"Материал из {host}"
        return "Сохранённый материал"

    if matched_stamped and cleaned:
        return cleaned
    if raw_stem:
        return raw_stem if "." not in base_name else base_name
    return "Сохранённая заметка"
