# FMLPack

`fmlpack` is a tool to convert a file tree to/from a Filesystem Markup Language (FML) document. It creates a single text-based archive of a directory structure, suitable for passing file contexts to LLMs (Large Language Models).

## Features

- **Pack**: Archives files and directories into a single FML file.
- **Unpack**: Extracts files from an FML archive to the filesystem.
- **Filtering**: Supports `.gitignore` rules via `--gitignore`, plus specific exclusions via `.fmlpackignore` and `--exclude`.
- **Safety**: Prevents path traversal attacks during extraction.

## Installation

### Using Pip (Recommended)

Install directly with pip to automatically handle dependencies:

```bash
pip install fmlpack
```

### Manual Installation

`fmlpack` is a single-file Python script, but it requires the `pathspec` library.

1.  Install the dependency: `pip install pathspec`.
2.  Copy `src/fmlpack.py` to a location in your PATH.
3.  Make it executable: `chmod +x fmlpack.py`.

## Usage

### Creating an archive

```bash
# Archive current directory to archive.fml
fmlpack -c . -f archive.fml

# Archive using .gitignore rules (excludes .git/ automatically)
fmlpack -c . --gitignore -f archive.fml

# Archive specific files and folders
fmlpack -c src/ tests/ -f source_code.fml

# Exclude specific patterns
fmlpack -c . --exclude "*.pyc" --exclude "__pycache__"
```

### Extracting an archive

```bash
# Extract to current directory
fmlpack -x -f archive.fml

# Extract to specific directory
fmlpack -x -f archive.fml -C /tmp/output
```

### Listing contents

```bash
fmlpack -t -f archive.fml
```

## Testing

This project uses `pytest` for testing.

1.  Install test dependencies:
    ```bash
    pip install pytest pytest-cov pathspec
    ```

2.  Run tests:
    ```bash
    pytest
    ```

3.  Run tests with coverage report:
    ```bash
    pytest --cov=./src/ tests/test_fmlpack.py
    ```

[![codecov](https://codecov.io/gh/yourusername/fmlpack/branch/main/graph/badge.svg)](https://codecov.io/gh/yourusername/fmlpack)
