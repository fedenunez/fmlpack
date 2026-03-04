# Changelog

## 0.3.0

- Fix binary detection for files with multi-byte UTF-8 characters (box-drawing, arrows, emojis, em-dash, ellipsis, etc.) that could be incorrectly flagged as binary when a multi-byte sequence was split at the 1024-byte read boundary.
- Parser now detects `<|||file_end|||>` even when appended to the end of a content line without a preceding newline, a common LLM output mistake.

## 0.2.2

- Fix input duplication in pack generation and expand test coverage.

## 0.2.1

- Initial public release.
