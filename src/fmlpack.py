#!/bin/python3
"""
Created on Fri Oct 27 13:36:28 2023
@author: fedenunez and tulp
"""

import argparse
import os
import fnmatch
import pathlib
import sys
import glob

# Optional dependency for proper .gitignore-style matching
try:
    import pathspec  # type: ignore
except Exception:  # pylint: disable=broad-except
    pathspec = None


def get_fml_spec():
    return """
# Filesystem Markup Language (FML)

The Filesystem Markup Language (FML) is a simple format to represent a file system's structure and content using markup tags.

## Structure Overview

### Tags

- **File Tag:**
  - **Start Tag:** `<|||file_start=${filepath}|||>`
  - **End Tag:** `<|||file_end|||>`
  - **Content:** The file content is placed between the start and end tags.
  - **Rules:**
    - Start and End tags must occupy a full line.
    - The content is placed between the start and end lines.
    - Start and END Tags must start at the beginning of the line with no leading spaces or tabs.

- **Directory Tag:**
  - **Tag:** `<|||dir=${dirpath}|||>`

### Description

- **Files:**
  - Represented by start and end tags indicating their relative path.
  - Content is written between these tags.
  - Only supports UTF8/ASCII text files; binary files are ignored.

- **Directories:**
  - Represented using the directory tag.
  - Useful for specifying empty directories.
  - If a file mentions a directory, it is assumed that the directory already exists.

### Important Notes

- All directories mentioned in a file path will be automatically created.
- All paths are relative to the starting point, which is the folder containing all files with the fewest levels possible.

## Examples

    ```fml
    <|||dir=projects|||>

    <|||file_start=projects/plan.txt|||>
    Project plan details go here.
    <|||file_end|||>`
    ```

This example creates a directory `projects` and a file `plan.txt` within it, containing the specified text.

    ```fml
    <|||file_start=documents/reports/summary.txt|||>
    Summary of the quarterly report.
    <|||file_end|||>
    ```

This example creates a directory `documents` with a subdirectory `reports`, and a file `summary.txt` within `reports`, containing the specified text.
"""

def process_arguments():
    """
    Process command line arguments and return an object with the values
    """
    parser = argparse.ArgumentParser(
        description="fmlpack: Convert a file tree to/from a Filesystem Markup Language (FML) document."
    )

    # tar like options
    parser.add_argument("-c", "--create", action="store_true", help="Create a new archive (default)")
    parser.add_argument("-x", "--extract", action="store_true", help="Extract files from an archive")
    parser.add_argument("-t", "--list", action="store_true", help="List the contents of an archive")
    parser.add_argument("-f", "--file", metavar="ARCHIVE", help="Use archive file or device ARCHIVE. Use '-' for stdin/stdout.")
    parser.add_argument("--spec-help", action="store_true", help="Print the FML specification and exit.")
    parser.add_argument("-s", "--include-spec", action="store_true", help="Include FML specification (as fmlpack-spec.md) in the created archive")
    parser.add_argument(
        "-C",
        "--directory",
        metavar="DIR",
        help="Change to directory DIR before performing operations (for extraction) or use DIR as base for relative paths (for creation)",
    )

    # own options
    parser.add_argument(
        "--exclude",
        metavar="PATTERN",
        action="append",
        help="Exclude files matching PATTERN",
    )
    parser.add_argument(
        "--gitignore",
        action="store_true",
        help="Also use .gitignore (from the base directory) as ignore patterns when creating an archive",
    )
    parser.add_argument("input", nargs="*", help="Input files or folders for archive creation")

    return parser.parse_args()

# ... other functions unchanged ...

def load_ignore_matcher(root_dir, use_gitignore_flag):
    """
    Load ignore patterns from .fmlpackignore and .gitignore files throughout the directory tree,
    honoring git's rule that patterns are relative to the file's location.
    """
    all_patterns = []

    # The advanced logic requires pathspec. If it's not available, the IgnoreMatcher
    # will fall back to fnmatch, but our pattern manipulation is designed for pathspec.
    # Therefore, we use a simpler (but less correct) fallback logic here if pathspec is missing.
    if pathspec is None and use_gitignore_flag:
        sys.stderr.write(
            "Warning: 'pathspec' module not found. .gitignore parsing will be basic and may not fully match git's behavior. "
            "Install with: pip install pathspec\n"
        )
        # Fallback to original, simple behavior: read only root ignore files
        for ignore_filename in [".fmlpackignore", ".gitignore"]:
            if not use_gitignore_flag and ignore_filename == ".gitignore":
                continue
            ignore_path = os.path.join(root_dir, ignore_filename)
            if os.path.isfile(ignore_path):
                try:
                    with open(ignore_path, "r", encoding="utf-8") as f:
                        all_patterns.extend(f.read().splitlines())
                except Exception:  # pylint: disable=broad-except
                    pass
        if use_gitignore_flag:
            all_patterns.insert(0, ".git/")

        # Filter out empty lines and comments for fnmatch
        all_patterns = [p.strip() for p in all_patterns if p.strip() and not p.strip().startswith("#")]

        if not all_patterns:
            return None
        # Assuming IgnoreMatcher is defined elsewhere and handles the use_pathspec flag
        return IgnoreMatcher(all_patterns, use_pathspec=False)

    # --- Pathspec-based logic ---

    root_path = pathlib.Path(root_dir).resolve()
    ignore_files_to_process = []

    # Find all .fmlpackignore files
    ignore_files_to_process.extend(root_path.rglob(".fmlpackignore"))

    if use_gitignore_flag:
        # Find all .gitignore files
        ignore_files_to_process.extend(root_path.rglob(".gitignore"))
        # Always ignore .git folder unless explicitly overridden.
        all_patterns.append("/.git/")

    # Process files. Sorting ensures a consistent order, which is good practice.
    for ignore_file in sorted(ignore_files_to_process):
        try:
            relative_dir_path = ignore_file.parent.relative_to(root_path)

            with ignore_file.open("r", encoding="utf-8") as f:
                for line in f:
                    pattern = line.strip()
                    if not pattern or pattern.startswith("#"):
                        continue

                    # If a pattern contains a slash, it is relative to the directory of the .gitignore file.
                    # We must prepend the directory's path to make it relative to the root for the global matcher.
                    # Patterns without a slash (e.g., "*.log", "build") are global and need no modification.
                    if "/" in pattern:
                        is_negated = pattern.startswith("!")
                        if is_negated:
                            pattern_body = pattern[1:]
                        else:
                            pattern_body = pattern

                        if str(relative_dir_path) == ".":
                             # Pattern is in the root ignore file. Ensure it is treated as root-relative.
                             final_pattern = f"/{pattern_body.lstrip('/')}"
                        else:
                             # Pattern is in a subdirectory's ignore file. Prepend the subdirectory's path.
                             final_pattern = f"/{relative_dir_path.as_posix()}/{pattern_body.lstrip('/')}"

                        if is_negated:
                            final_pattern = "!" + final_pattern

                        all_patterns.append(final_pattern)
                    else:
                        # It's a global pattern (e.g., "*.log"), add it as is.
                        all_patterns.append(pattern)

        except Exception:
            # Silently ignore errors reading or processing ignore files, similar to git.
            pass

    if not all_patterns:
        return None

    # We must use pathspec for this logic to be effective.
    # Assuming IgnoreMatcher is defined elsewhere and handles the use_pathspec flag
    return IgnoreMatcher(all_patterns, use_pathspec=True)

# ... rest of file unchanged ...
