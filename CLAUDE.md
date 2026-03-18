# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

fmlpack converts file trees to/from FML (Filesystem Markup Language) — single text-based archives for passing directory contexts to LLMs. Single-file Python module at `src/fmlpack.py`.

## Commands

```bash
make test          # Run all tests (creates .venv, installs deps, runs pytest)
make build         # Build sdist + wheel into dist/
make install       # Install from built tarball into .venv
make upload        # Upload to PyPI via twine

# Run a single test
.venv/bin/pytest -v -s tests/test_fmlpack.py::TestClassName::test_name
```

## Architecture

Single entry point: `src/fmlpack.py` with `main()`. Three modes: create (`-c`), extract (`-x`), list (`-l`).

Key internal flow:
- `expand_and_collect_paths()` → walks directories, applies ignore rules
- `generate_fml()` → reads files, emits FML tags (`<|||file_start|||>`, `<|||file_end|||>`)
- `extract_fml()` → parses FML stream, recreates files
- `list_fml()` → parses FML stream, lists contained paths
- `IgnoreMatcher` (wraps `pathspec`) handles `.gitignore` + `.fmlpackignore` + `--exclude` patterns
- Binary detection via `_is_binary_file()` with UTF-8 multi-byte boundary awareness

FML tags are designed to be unambiguous even when LLMs reformat content. `file_end` can appear inline (glued to content) and the parser handles this via `endswith()` detection.

## Development Process

Test-driven development only. Write failing tests first, then implement minimal code to pass.

## Dependencies

Runtime: `pathspec>=0.10.3`, `tiktoken`. Python >=3.6.
