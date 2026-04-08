#!/usr/bin/env python3
"""Normalize OCR/PDF-converted HTML formatting glitches.

This script fixes recurring structural issues observed in converted legal HTML files:
1) Heading tags that actually contain paragraph text (often around paragraph 3).
2) Multiple numbered paragraphs merged into a single <p> block.
3) Paragraph numbers detached from body text (e.g. '<p>16.</p><p>Text...').
4) Literal escaped newlines ('\\n') left in HTML text.

Usage examples:
  python fix_html_format.py 23702376.html --in-place
  python fix_html_format.py 23702376.html 23724922.html --output-dir fixed
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

PARA_MARKER_RE = re.compile(r"(?<!\d)(\d{1,3})\.\s+")
P_TAG_RE = re.compile(r"<p\b([^>]*)>(.*?)</p>", re.IGNORECASE | re.DOTALL)


@dataclass
class FixStats:
    escaped_newlines: int = 0
    heading_to_paragraph: int = 0
    merged_orphan_markers: int = 0
    split_merged_paragraphs: int = 0


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def normalize_ws(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def seems_paragraph_heading(text: str) -> bool:
    """Heuristic: detect heading text that is really paragraph prose."""
    plain = normalize_ws(strip_tags(text))
    if not plain:
        return False
    if len(plain) < 20:
        return False
    words = plain.split()
    if len(words) < 4:
        return False
    alpha_words = [w for w in words if re.search(r"[A-Za-z]", w)]
    title_case_ratio = sum(w[:1].isupper() for w in alpha_words) / max(len(alpha_words), 1)
    has_sentence_punctuation = any(ch in plain for ch in [":", ",", ";", "?"])
    all_caps = plain.upper() == plain
    return (not all_caps) and (title_case_ratio < 0.95) and has_sentence_punctuation


def replace_escaped_newlines(html: str, stats: FixStats) -> str:
    count = html.count("\\n")
    if count:
        stats.escaped_newlines += count
        html = html.replace("\\n", "\n")
    return html


def merge_orphan_number_markers(html: str, stats: FixStats) -> str:
    # Case A: standalone marker paragraph followed by text paragraph.
    pattern_a = re.compile(
        r"<p\b([^>]*)>\s*(\d{1,3})\.\s*</p>\s*<p\b([^>]*)>(.*?)</p>",
        re.IGNORECASE | re.DOTALL,
    )

    def repl_a(match: re.Match[str]) -> str:
        stats.merged_orphan_markers += 1
        num = match.group(2)
        content = match.group(4).strip()
        return f'<p{match.group(3)}>{num}. {content}</p>'

    html = pattern_a.sub(repl_a, html)

    # Case B: marker appears at end of previous paragraph and continues in next paragraph.
    pattern_b = re.compile(
        r"<p\b([^>]*)>(.*?)\s+(\d{1,3})\.\s*</p>\s*<p\b([^>]*)>(.*?)</p>",
        re.IGNORECASE | re.DOTALL,
    )

    def repl_b(match: re.Match[str]) -> str:
        prev_text = normalize_ws(strip_tags(match.group(2)))
        if not prev_text or prev_text.endswith(":"):
            return match.group(0)
        stats.merged_orphan_markers += 1
        merged = f"{match.group(2).rstrip()} {match.group(3)}. {match.group(5).lstrip()}"
        return f'<p{match.group(1)}>{merged}</p>'

    html = pattern_b.sub(repl_b, html)
    return html


def convert_misclassified_headings(html: str, stats: FixStats) -> str:
    # If a prose heading is immediately followed by '<p>n.</p>', merge into one numbered paragraph.
    pattern = re.compile(
        r"<h([1-6])\b([^>]*)>(.*?)</h\1>\s*<p\b([^>]*)>\s*(\d{1,3})\.\s*</p>",
        re.IGNORECASE | re.DOTALL,
    )

    def repl(match: re.Match[str]) -> str:
        heading_text = match.group(3)
        if not seems_paragraph_heading(heading_text):
            return match.group(0)
        number = match.group(5)
        cleaned = normalize_ws(strip_tags(heading_text))
        stats.heading_to_paragraph += 1
        return f'<p{match.group(4)}>{number}. {cleaned}</p>'

    return pattern.sub(repl, html)


def split_numbered_paragraphs_in_text(text: str) -> List[str]:
    plain = normalize_ws(strip_tags(text))
    matches = list(PARA_MARKER_RE.finditer(plain))
    if len(matches) < 2:
        return [plain]

    chunks: List[str] = []
    first_start = matches[0].start()
    if first_start > 0:
        preamble = plain[:first_start].strip()
        if preamble:
            chunks.append(preamble)

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(plain)
        segment = plain[start:end].strip()
        if segment:
            chunks.append(segment)

    return chunks if len(chunks) > 1 else [plain]


def split_merged_numbered_paragraphs(html: str, stats: FixStats) -> str:
    parts: List[str] = []
    last = 0
    for match in P_TAG_RE.finditer(html):
        parts.append(html[last:match.start()])
        attrs, inner = match.group(1), match.group(2)
        segments = split_numbered_paragraphs_in_text(inner)
        if len(segments) == 1:
            parts.append(match.group(0))
        else:
            stats.split_merged_paragraphs += 1
            rebuilt = "\n".join(f"<p{attrs}>{segment}</p>" for segment in segments)
            parts.append(rebuilt)
        last = match.end()
    parts.append(html[last:])
    return "".join(parts)


def apply_fixes(html: str) -> Tuple[str, FixStats]:
    stats = FixStats()
    html = replace_escaped_newlines(html, stats)
    html = convert_misclassified_headings(html, stats)
    html = merge_orphan_number_markers(html, stats)
    html = split_merged_numbered_paragraphs(html, stats)
    return html, stats


def process_file(path: Path, output_dir: Path | None, in_place: bool) -> Tuple[Path, FixStats]:
    original = path.read_text(encoding="utf-8")
    fixed, stats = apply_fixes(original)

    if in_place:
        target = path
    elif output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / path.name
    else:
        target = path.with_suffix(path.suffix + ".fixed")

    target.write_text(fixed, encoding="utf-8")
    return target, stats


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fix formatting issues in converted HTML files")
    parser.add_argument("files", nargs="+", type=Path, help="Input HTML files")
    parser.add_argument("--in-place", action="store_true", help="Overwrite input files")
    parser.add_argument("--output-dir", type=Path, help="Directory to write fixed files")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    for file_path in args.files:
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        target, stats = process_file(file_path, args.output_dir, args.in_place)
        print(
            f"{file_path} -> {target} | "
            f"escaped_newlines={stats.escaped_newlines}, "
            f"heading_to_paragraph={stats.heading_to_paragraph}, "
            f"merged_markers={stats.merged_orphan_markers}, "
            f"split_merged_paragraphs={stats.split_merged_paragraphs}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
