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

def get_relative_path(root_dir, file_path):
    """
    Get the relative path of a file from the root directory.
    """
    return os.path.relpath(file_path, root_dir)

def is_binary_file(file_path):
    """
    Check if a file is a binary file based on its content.
    """
    try:
        with open(file_path, "rb") as f:
            # Check for null bytes
            content = f.read(1024)
            if b"\x00" in content:
                return True
            # Check for non-UTF-8 characters
            try:
                content.decode('utf-8')
            except UnicodeDecodeError:
                return True
    except Exception: # pylint: disable=broad-except
        # If we can't read it for any reason, treat as binary to be safe
        return True
    return False

def is_excluded_cli(file_path, exclude_patterns):
    """Check if a file path matches any of the CLI exclude patterns."""
    if not exclude_patterns:
        return False
    for pattern in exclude_patterns:
        if fnmatch.fnmatch(file_path, pattern) or \
           any(fnmatch.fnmatch(part, pattern) for part in pathlib.Path(file_path).parts):
            return True
    return False


class IgnoreMatcher:
    """Gitignore-style matcher for .fmlpackignore and optionally .gitignore."""
    def __init__(self, patterns, use_pathspec):
        self.use_pathspec = use_pathspec and pathspec is not None
        self._posix_sep = "/"
        if self.use_pathspec:
            self._spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)
        else:
            self._compiled = self._compile_fallback(patterns)

    @staticmethod
    def _read_patterns_from_file(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read().splitlines()
        except Exception:  # pylint: disable=broad-except
            return []

    @staticmethod
    def _normalize_posix(p):
        return p.replace(os.sep, "/")

    @staticmethod
    def _strip_comments_and_blank(lines):
        cleaned = []
        for line in lines:
            # Keep exact gitignore semantics only if pathspec is used.
            # For fallback: strip comments and blanks.
            l = line.rstrip("\n\r")
            if not l:
                continue
            if l.lstrip().startswith("#"):
                continue
            cleaned.append(l)
        return cleaned

    @staticmethod
    def _compile_fallback(patterns):
        """Compile patterns to a structured list implementing a subset of .gitignore rules."""
        compiled = []
        cleaned = IgnoreMatcher._strip_comments_and_blank(patterns)
        for raw in cleaned:
            neg = raw.startswith("!")
            pat = raw[1:] if neg else raw

            dir_only = pat.endswith("/")
            if dir_only:
                pat = pat[:-1]

            anchored = pat.startswith("/")
            if anchored:
                pat = pat[1:]

            compiled.append({
                "neg": neg,
                "dir_only": dir_only,
                "anchored": anchored,
                "pat": pat
            })
        return compiled

    def matches(self, relpath, is_dir):
        # Convert to posix
        rel_posix = self._normalize_posix(relpath)

        if self.use_pathspec:
            # For directory-only matches, pathspec expects trailing slash for strict dir patterns
            candidate = rel_posix if not is_dir else (rel_posix if rel_posix.endswith("/") else rel_posix + "/")
            return self._spec.match_file(candidate)

        # Fallback logic with limited gitignore semantics
        matched = False
        parts = rel_posix.split(self._posix_sep) if rel_posix else [rel_posix]
        for rule in self._compiled:
            if rule["dir_only"] and not is_dir:
                continue

            pat = rule["pat"]

            if rule["anchored"]:
                # Match from repo root
                if fnmatch.fnmatch(rel_posix, pat):
                    matched = not rule["neg"]
            else:
                if "/" in pat:
                    # Pattern with slash but not anchored: match against full path
                    if fnmatch.fnmatch(rel_posix, pat):
                        matched = not rule["neg"]
                else:
                    # No slash: match any path segment (basename match)
                    if any(fnmatch.fnmatch(seg, pat) for seg in parts):
                        matched = not rule["neg"]
        return matched


def load_ignore_matcher(root_dir, use_gitignore_flag):
    """Load .fmlpackignore and optional .gitignore from root_dir and create a matcher."""
    patterns = []

    fmlpackignore_path = os.path.join(root_dir, ".fmlpackignore")
    if os.path.isfile(fmlpackignore_path):
        try:
            with open(fmlpackignore_path, "r", encoding="utf-8") as f:
                patterns.extend(f.read().splitlines())
        except Exception:  # pylint: disable=broad-except
            pass

    if use_gitignore_flag:
        gitignore_path = os.path.join(root_dir, ".gitignore")
        if os.path.isfile(gitignore_path):
            try:
                with open(gitignore_path, "r", encoding="utf-8") as f:
                    patterns.extend(f.read().splitlines())
            except Exception:  # pylint: disable=broad-except
                pass

    if not patterns:
        return None

    # Use pathspec if available for accurate gitignore semantics, otherwise fallback
    return IgnoreMatcher(patterns, use_pathspec=True if pathspec is not None else False)


def should_exclude(relpath, is_dir, exclude_patterns, ignore_matcher):
    """Unified exclusion: CLI --exclude patterns OR ignore files."""
    if is_excluded_cli(relpath, exclude_patterns):
        return True
    if ignore_matcher and ignore_matcher.matches(relpath, is_dir):
        return True
    return False


def generate_fml(root_dir, files_and_folders, exclude_patterns, include_spec, ignore_matcher=None):
    """Generate the FML content for the given files and folders."""
    fml_content = []
    errors = [] # Store errors encountered during processing

    # Ensure root_dir is an absolute path for correct relative path calculation
    root_dir_abs = os.path.abspath(root_dir)

    processed_dirs = set()

    if include_spec:
        fml_content.append("<|||file_start=fmlpack-spec.md|||>\n")
        fml_content.append(get_fml_spec())
        fml_content.append("<|||file_end|||>\n")

    sorted_items = sorted(files_and_folders) # Process in a consistent order

    for item_path_orig in sorted_items: # item_path_orig is an absolute path from expand_and_collect_paths
        item_path_abs = os.path.abspath(item_path_orig) 
        relative_path = get_relative_path(root_dir_abs, item_path_abs)

        # Create parent directory entries if not already processed
        parent_dir = os.path.dirname(relative_path)
        current_parent_parts = []
        if parent_dir and parent_dir != '.': # Check if it's not the root itself or an empty parent
            for part in pathlib.Path(parent_dir).parts:
                current_parent_parts.append(part)
                dir_to_check = os.path.join(*current_parent_parts)
                if dir_to_check not in processed_dirs and not should_exclude(dir_to_check, True, exclude_patterns, ignore_matcher):
                    fml_content.append(f"<|||dir={dir_to_check}|||>\n")
                    processed_dirs.add(dir_to_check)

        if os.path.isdir(item_path_abs):
            if relative_path not in processed_dirs and not should_exclude(relative_path, True, exclude_patterns, ignore_matcher):
                if relative_path != ".": # Avoid <|||dir=.|||> if root_dir itself is listed
                    fml_content.append(f"<|||dir={relative_path}|||>\n")
                processed_dirs.add(relative_path)

        elif os.path.isfile(item_path_abs):
            if should_exclude(relative_path, False, exclude_patterns, ignore_matcher):
                errors.append(f"Excluding: {relative_path}")
            elif is_binary_file(item_path_abs):
                errors.append(f"Ignoring binary file: {relative_path}")
            else:
                fml_content.append(f"<|||file_start={relative_path}|||>\n")
                try:
                    with open(item_path_abs, "r", encoding="utf-8") as f:
                        content=f.read()
                        if content and not content.endswith('\n'):
                            content += '\n'
                        fml_content.append(content)
                except UnicodeDecodeError as e:
                    errors.append(f"Error reading file {relative_path}: {e}")
                except Exception as e: # pylint: disable=broad-except
                    errors.append(f"Could not process file {relative_path}: {e}")
                fml_content.append("<|||file_end|||>\n")
        elif not os.path.exists(item_path_abs):
             offending_item_display_path = get_relative_path(root_dir_abs, item_path_abs)
             errors.append(f"Input item not found: {offending_item_display_path} (resolved to {item_path_abs})")


    return fml_content, errors

def get_common_base_dir(paths):
    """
    Find the shallowest common parent directory for a list of absolute paths.
    If paths includes files, their parent directories are considered.
    If only one path is given and it's a directory, it's the base.
    If only one path is given and it's a file, its parent is the base.
    If no paths, current working directory.
    """
    if not paths:
        return os.getcwd()

    processed_paths = []
    for p_str in paths:
        abs_p = os.path.abspath(p_str) # Should already be absolute
        if os.path.isfile(abs_p): # Check existence for file/dir determination
            processed_paths.append(os.path.dirname(abs_p))
        elif os.path.isdir(abs_p):
            processed_paths.append(abs_p)
        else:
            # For non-existent paths, use dirname if it looks like a file path (has an extension),
            # otherwise, assume it was intended as a directory path for common base calculation.
            processed_paths.append(os.path.dirname(abs_p) if os.path.basename(abs_p).rfind('.') > 0 else abs_p)


    if not processed_paths:
        return os.getcwd()

    return os.path.commonpath(processed_paths)


def expand_and_collect_paths(input_patterns, reference_dir_for_relative_patterns):
    """
    Expands glob patterns using glob.glob and collects all specified files and directories.
    Ensures all returned paths are absolute.
    If a directory is specified or matched, its contents are recursively added later by os.walk.
    """
    initial_collected_paths = set() # Stores absolute path strings

    for pattern_orig in input_patterns:
        current_pattern_to_process = str(pattern_orig) # Ensure it's a string

        # Handle "." case directly to avoid globbing for it.
        if current_pattern_to_process == ".":
            abs_path = str(pathlib.Path(reference_dir_for_relative_patterns, ".").resolve(strict=False))
            initial_collected_paths.add(abs_path)
            continue

        is_wildcard_pattern = any(c in current_pattern_to_process for c in "*?[")

        # Determine the full pattern for glob.glob module
        if os.path.isabs(current_pattern_to_process):
            full_pattern_for_glob_module = current_pattern_to_process
        else:
            full_pattern_for_glob_module = os.path.join(reference_dir_for_relative_patterns, current_pattern_to_process)

        matched_by_glob_module = glob.glob(full_pattern_for_glob_module, recursive=True)

        if not matched_by_glob_module and not is_wildcard_pattern:
            # Specific path (no wildcards), and glob found nothing (e.g., non-existent).
            # Add this specific path (made absolute) to initial_collected_paths.
            abs_path = os.path.abspath(full_pattern_for_glob_module)
            initial_collected_paths.add(abs_path)
        else:
            for p_str in matched_by_glob_module:
                initial_collected_paths.add(os.path.abspath(p_str)) # Ensure absolute

    final_collected_paths = set()
    queue = list(initial_collected_paths)
    processed_for_walk = set()

    while queue:
        path_str_abs = queue.pop(0)
        final_collected_paths.add(path_str_abs)

        path_obj = pathlib.Path(path_str_abs)
        if path_obj.exists() and path_obj.is_dir():
            if path_str_abs not in processed_for_walk:
                processed_for_walk.add(path_str_abs)
                try:
                    for root, dirs, files in os.walk(path_str_abs):
                        current_root_abs = os.path.abspath(root)
                        final_collected_paths.add(current_root_abs)
                        for d_name in dirs:
                            final_collected_paths.add(os.path.abspath(os.path.join(current_root_abs, d_name)))
                        for f_name in files:
                            final_collected_paths.add(os.path.abspath(os.path.join(current_root_abs, f_name)))
                except OSError as e:
                    print(f"Warning: Could not walk directory {path_str_abs}: {e}", file=sys.stderr)

    return sorted(list(final_collected_paths))


FSL = len("<|||file_start=")
FEL = len("|||>")
DIRSL = len("<|||dir=")
DIREL = len("|||>")

def extract_fml_archive(archive_file_path, target_dir_path, additional_files=None):
    """Extract files from an FML archive."""
    if additional_files:
        print(f"Warning: Unexpected arguments for extraction: {additional_files}. These will be ignored.", file=sys.stderr)
        print(f"To specify extraction directory, use the -C/--directory option.", file=sys.stderr)

    os.makedirs(target_dir_path, exist_ok=True)

    try:
        if archive_file_path == '-':
            f_in = sys.stdin
        else:
            f_in = open(archive_file_path, "r", encoding="utf-8")
    except FileNotFoundError:
        print(f"Error: Archive file not found: {archive_file_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error opening archive file {archive_file_path}: {e}", file=sys.stderr)
        sys.exit(1)


    current_file_handle = None
    current_file_path_str = None
    file_content_buffer = []

    with f_in:
        for line_num, line_raw in enumerate(f_in, 1):
            line = line_raw.rstrip('\n\r') # Preserves leading spaces

            if line.startswith("<|||file_start="): # Strict check: no leading spaces
                if current_file_handle:
                    current_file_handle.write("".join(file_content_buffer))
                    file_content_buffer = []
                    current_file_handle.close()
                    print(f"Extracted: {current_file_path_str}")
                current_file_path_str = line[FSL:-FEL]
                full_path = os.path.join(target_dir_path, current_file_path_str)
                try:
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    current_file_handle = open(full_path, "w", encoding="utf-8")
                except Exception as e:
                    print(f"Error creating file {full_path}: {e}", file=sys.stderr)
                    current_file_handle = None

            elif line == "<|||file_end|||>": # Strict check: no leading/trailing spaces (other than what rstrip removed)
                if current_file_handle:
                    current_file_handle.write("".join(file_content_buffer))
                    file_content_buffer = []
                    current_file_handle.close()
                    print(f"Extracted: {current_file_path_str}")
                    current_file_handle = None
                    current_file_path_str = None
                else:
                    # This could happen if <|||file_end|||> is found outside an active file context
                    # or if the file handle failed to open.
                    print(f"Warning: Encountered <|||file_end|||> without an active file context near line {line_num}.", file=sys.stderr)


            elif line.startswith("<|||dir="): # Strict check: no leading spaces
                if current_file_handle: # A dir tag inside a file content block is not standard.
                    # Treat as content if a file is open.
                    file_content_buffer.append(line_raw)
                else:
                    dir_path_str = line[DIRSL:-DIREL]
                    full_path = os.path.join(target_dir_path, dir_path_str)
                    try:
                        os.makedirs(full_path, exist_ok=True)
                        print(f"Created directory: {dir_path_str}")
                    except Exception as e:
                        print(f"Error creating directory {full_path}: {e}", file=sys.stderr)


            elif current_file_handle:
                file_content_buffer.append(line_raw) # Append the raw line (with original newline)
            # Lines outside any tag or file context (e.g. blank lines, comments not in file content) are ignored during extraction.

        # After loop, if a file was still open (e.g. FML ends mid-file without <|||file_end|||>)
        if current_file_handle:
            current_file_handle.write("".join(file_content_buffer))
            current_file_handle.close()
            print(f"Extracted (EOF): {current_file_path_str}")


def list_fml_archive(archive_file_path):
    """List the contents of an FML archive, adhering strictly to tag specification."""
    try:
        if archive_file_path == '-':
            f_in = sys.stdin
        else:
            f_in = open(archive_file_path, "r", encoding="utf-8")
    except FileNotFoundError:
        print(f"Error: Archive file not found: {archive_file_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error opening archive file {archive_file_path}: {e}", file=sys.stderr)
        sys.exit(1)

    with f_in:
        for line_raw in f_in:
            line = line_raw.rstrip('\n\r') # Remove only trailing newlines, keep leading spaces
            if line.startswith("<|||file_start="): # Strict check
                print(line[FSL:-FEL])
            elif line.startswith("<|||dir="): # Strict check
                print(line[DIRSL:-DIREL])
            # <|||file_end|||> is not typically listed, only file and dir paths.

def main():
    """Main function."""
    args = process_arguments()

    if args.spec_help:
        print(get_fml_spec())
        return

    num_modes = sum([args.create, args.extract, args.list])

    if num_modes > 1:
        print("Error: Only one of --create, --extract, or --list can be specified.", file=sys.stderr)
        sys.exit(1)

    is_create_mode = args.create
    if num_modes == 0:
        if args.input or (args.file == '-' and not sys.stdin.isatty()):
            is_create_mode = True
        elif not args.file and sys.stdin.isatty() and not args.input:
            print("Error: No operation specified (create, extract, list) and no input provided.", file=sys.stderr)
            print("Try 'fmlpack --help' for more information.", file=sys.stderr)
            sys.exit(1)
        elif args.file and not args.input:
            print(f"Error: Archive file '{args.file}' specified, but no operation (--create, --extract, --list).", file=sys.stderr)
            sys.exit(1)


    archive_file_path = args.file if args.file else None
    if not archive_file_path and (args.extract or args.list) and sys.stdin.isatty():
        print("Error: -f/--file or piped input is required for --extract or --list.", file=sys.stderr)
        sys.exit(1)
    if not archive_file_path and (args.extract or args.list) and not sys.stdin.isatty():
        archive_file_path = '-'

    # Final check for determined operation mode
    if not is_create_mode and not args.extract and not args.list:
        # This condition implies no operation could be determined explicitly or by inference.
        # Typically occurs if fmlpack is called with no flags and non-TTY stdin (e.g. empty pipe)
        # or other unhandled argument combinations.
        print("Error: No operation could be determined. Specify -c, -x, or -t, or provide input for creation.", file=sys.stderr)
        print("Try 'fmlpack --help' for more information.", file=sys.stderr)
        sys.exit(1)

    if is_create_mode:
        if not args.input:
            print("Error: At least one input file or folder is required for archive creation.", file=sys.stderr)
            sys.exit(1)

        output_file_path = args.file if args.file else '-'

        all_files_and_folders_to_archive = []
        root_dir_for_fml = ""

        if args.directory:
            base_dir_for_creation = os.path.abspath(args.directory)
            if not os.path.isdir(base_dir_for_creation):
                print(f"Error: Directory specified with -C/--directory does not exist: {base_dir_for_creation}", file=sys.stderr)
                sys.exit(1)

            all_files_and_folders_to_archive = expand_and_collect_paths(args.input, base_dir_for_creation)
            root_dir_for_fml = base_dir_for_creation
        else:
            all_files_and_folders_to_archive = expand_and_collect_paths(args.input, os.getcwd())
            root_dir_for_fml = get_common_base_dir(all_files_and_folders_to_archive)


        # Load ignore matcher from .fmlpackignore and optionally .gitignore
        ignore_matcher = load_ignore_matcher(root_dir_for_fml, args.gitignore)

        fml_content_lines, errors = generate_fml(root_dir_for_fml, all_files_and_folders_to_archive, args.exclude, args.include_spec, ignore_matcher=ignore_matcher)

        if output_file_path == '-':
            try:
                sys.stdout.write("".join(fml_content_lines))
                sys.stdout.flush()
            except BrokenPipeError:
                # Handle cases where stdout pipe is closed (e.g. `fmlpack ... | head`)
                # This is not an error for fmlpack itself.
                try:
                    sys.stderr.close() # Attempt to close stderr to avoid BrokenPipeError there too
                except Exception: # pylint: disable=broad-except
                    pass # Ignore errors on stderr close
                sys.exit(0) # Exit cleanly
        else:
            with open(output_file_path, "w", encoding="utf-8") as f_out:
                f_out.write("".join(fml_content_lines))
            print(f"FML archive created: {output_file_path}")

        if errors:
            print("\nEncountered issues during archive creation:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)


    elif args.extract:
        target_dir = args.directory if args.directory else "."
        extract_fml_archive(archive_file_path, target_dir, args.input if args.input else None)

    elif args.list:
        if args.input:
             print("Warning: Input paths provided with --list will be ignored.", file=sys.stderr)
        list_fml_archive(archive_file_path)

if __name__ == "__main__":
    main()
