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
import pathspec 

__version__ = "0.2.2"

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

    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

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
        help="Exclude files matching PATTERN (matches against archive path)",
    )
    parser.add_argument(
        "--gitignore",
        action="store_true",
        help="Also use .gitignore (searched upwards from base directory) as ignore patterns when creating an archive",
    )
    parser.add_argument("input", nargs="*", help="Input files or folders for archive creation")

    return parser.parse_args()

def get_relative_path(root_dir, file_path):
    """
    Get the relative path of a file from the root directory.
    """
    return os.path.relpath(file_path, root_dir)

def to_posix_path(path):
    """
    Convert a path to POSIX style (forward slashes), suitable for FML tags.
    """
    return path.replace(os.sep, '/')

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
    # Normalize file_path to avoid OS specific separator issues in matching
    normalized_path = file_path.replace(os.sep, "/")
    for pattern in exclude_patterns:
        if fnmatch.fnmatch(normalized_path, pattern) or \
           any(fnmatch.fnmatch(part, pattern) for part in normalized_path.split("/")):
            return True
    return False


class IgnoreMatcher:
    """Gitignore-style matcher using pathspec."""
    def __init__(self, ignore_root_dir, patterns):
        self.ignore_root = os.path.abspath(ignore_root_dir)
        self._spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    def matches(self, abs_path, is_dir):
        """
        Check if an absolute path matches the ignore patterns.
        The path is first converted to a relative path from the ignore root.
        """
        if not abs_path.startswith(self.ignore_root):
            # Path is outside the ignore root scope; defaults to not ignored by this matcher.
            return False
        
        # Get path relative to the ignore root (where .gitignore resides)
        relpath = os.path.relpath(abs_path, self.ignore_root)
        if relpath == '.':
            return False

        # Convert to posix for consistent matching with pathspec
        rel_posix = relpath.replace(os.sep, "/")

        # For directory-only matches, pathspec expects trailing slash for strict dir patterns
        # or we rely on match_file vs match_tree behavior.
        # Ensure we pass the trailing slash if it is a directory to match 'dir/' patterns correctly.
        candidate = rel_posix + "/" if is_dir else rel_posix
        
        try:
            return self._spec.match_file(candidate)
        except Exception: # pylint: disable=broad-except
             return False


def find_project_root(start_dir):
    """
    Find the project root by looking for .git, .fmlpackignore, or .gitignore upwards.
    Returns the absolute path of the directory found, or start_dir if none found.
    """
    current = os.path.abspath(start_dir)
    # limit depth to avoid infinite loops in weird FS structures
    for _ in range(50): 
        if os.path.exists(os.path.join(current, ".git")) or \
           os.path.exists(os.path.join(current, ".fmlpackignore")) or \
           os.path.exists(os.path.join(current, ".gitignore")):
            return current
        
        parent = os.path.dirname(current)
        if parent == current: # Reached root
            break
        current = parent
    
    return os.path.abspath(start_dir)


def load_ignore_matcher(start_dir, use_gitignore_flag):
    """
    Load .fmlpackignore and optional .gitignore. 
    Searches upwards from start_dir to find the 'project root'.
    """
    project_root = find_project_root(start_dir)
    patterns = []

    fmlpackignore_path = os.path.join(project_root, ".fmlpackignore")
    if os.path.isfile(fmlpackignore_path):
        try:
            with open(fmlpackignore_path, "r", encoding="utf-8") as f:
                patterns.extend(f.read().splitlines())
        except Exception:  # pylint: disable=broad-except
            pass

    if use_gitignore_flag:
        gitignore_path = os.path.join(project_root, ".gitignore")
        if os.path.isfile(gitignore_path):
            try:
                with open(gitignore_path, "r", encoding="utf-8") as f:
                    patterns.extend(f.read().splitlines())
            except Exception:  # pylint: disable=broad-except
                pass
        
        # Explicitly ignore .git/ when using gitignore flag
        patterns.append(".git/")

    if not patterns:
        return None

    return IgnoreMatcher(project_root, patterns)


def should_exclude(abs_path, rel_path_archive, is_dir, exclude_patterns, ignore_matcher):
    """
    Unified exclusion check.
    abs_path: Absolute path on disk (for ignore_matcher)
    rel_path_archive: Relative path intended for the archive (for CLI excludes)
    """
    # CLI excludes usually match against the path visible in the archive
    if is_excluded_cli(rel_path_archive, exclude_patterns):
        return True
    
    # Ignore matcher works on filesystem structure (absolute paths -> relative to git root)
    if ignore_matcher and ignore_matcher.matches(abs_path, is_dir):
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

    # FIX: Deduplicate inputs before processing
    unique_items = set(os.path.abspath(p) for p in files_and_folders)
    sorted_items = sorted(unique_items) 

    for item_path_abs in sorted_items: 
        relative_path = get_relative_path(root_dir_abs, item_path_abs)

        # Create parent directory entries if not already processed
        parent_dir = os.path.dirname(relative_path)
        current_parent_parts = []
        if parent_dir and parent_dir != '.': 
            parts = pathlib.Path(parent_dir).parts
            for part in parts:
                current_parent_parts.append(part)
                dir_to_check_rel = os.path.join(*current_parent_parts)
                dir_to_check_abs = os.path.join(root_dir_abs, dir_to_check_rel)
                
                if dir_to_check_rel not in processed_dirs:
                    if not should_exclude(dir_to_check_abs, dir_to_check_rel, True, exclude_patterns, ignore_matcher):
                        # Ensure POSIX style output
                        fml_content.append(f"<|||dir={to_posix_path(dir_to_check_rel)}|||>\n")
                        processed_dirs.add(dir_to_check_rel)
                    else:
                        processed_dirs.add(dir_to_check_rel) # Mark as processed so we don't check again, even if excluded

        if os.path.isdir(item_path_abs):
            if relative_path not in processed_dirs:
                if not should_exclude(item_path_abs, relative_path, True, exclude_patterns, ignore_matcher):
                    if relative_path != ".": # Avoid <|||dir=.|||>
                        fml_content.append(f"<|||dir={to_posix_path(relative_path)}|||>\n")
                    processed_dirs.add(relative_path)

        elif os.path.isfile(item_path_abs):
            if should_exclude(item_path_abs, relative_path, False, exclude_patterns, ignore_matcher):
                # Silent exclusion is preferred for ignore files.
                pass 
            elif is_binary_file(item_path_abs):
                errors.append(f"Ignoring binary file: {to_posix_path(relative_path)}")
            else:
                fml_content.append(f"<|||file_start={to_posix_path(relative_path)}|||>\n")
                try:
                    with open(item_path_abs, "r", encoding="utf-8") as f:
                        content=f.read()
                        if content and not content.endswith('\n'):
                            content += '\n'
                        fml_content.append(content)
                except UnicodeDecodeError as e:
                    errors.append(f"Error reading file {to_posix_path(relative_path)}: {e}")
                except Exception as e: # pylint: disable=broad-except
                    errors.append(f"Could not process file {to_posix_path(relative_path)}: {e}")
                fml_content.append("<|||file_end|||>\n")
        elif not os.path.exists(item_path_abs):
             offending_item_display_path = get_relative_path(root_dir_abs, item_path_abs)
             errors.append(f"Input item not found: {offending_item_display_path} (resolved to {item_path_abs})")


    return fml_content, errors

def get_common_base_dir(paths, current_working_dir=None):
    """
    Find the shallowest common parent directory for a list of absolute paths.
    
    If current_working_dir is provided, ensures that if a path matches it,
    it is not treated as a child of its parent (i.e. '.' stays '.').
    """
    if not paths:
        return os.getcwd()
    
    if current_working_dir is None:
        current_working_dir = os.getcwd()

    processed_paths = []
    for p_str in paths:
        abs_p = os.path.abspath(p_str) 
        if os.path.isfile(abs_p): 
            processed_paths.append(os.path.dirname(abs_p))
        elif os.path.isdir(abs_p):
            # Use parent of directory to ensure directory name is preserved in archive
            # UNLESS the directory is effectively the current working directory (e.g. input was '.')
            if abs_p == os.path.abspath(current_working_dir):
                processed_paths.append(abs_p)
            else:
                processed_paths.append(os.path.dirname(abs_p))
        else:
            processed_paths.append(os.path.dirname(abs_p) if os.path.basename(abs_p).rfind('.') > 0 else abs_p)

    if not processed_paths:
        return os.getcwd()

    return os.path.commonpath(processed_paths)


def expand_and_collect_paths(input_patterns, reference_dir_for_relative_patterns, ignore_matcher=None):
    """
    Expands glob patterns and collects all specified files and directories.
    Applies ignore_matcher during the walk to prevent recursing into ignored directories.
    """
    initial_collected_paths = set() 

    for pattern_orig in input_patterns:
        current_pattern_to_process = str(pattern_orig) 

        # Handle "." case directly
        if current_pattern_to_process == ".":
            abs_path = str(pathlib.Path(reference_dir_for_relative_patterns, ".").resolve(strict=False))
            initial_collected_paths.add(abs_path)
            continue

        is_wildcard_pattern = any(c in current_pattern_to_process for c in "*?[")

        if os.path.isabs(current_pattern_to_process):
            full_pattern_for_glob_module = current_pattern_to_process
        else:
            full_pattern_for_glob_module = os.path.join(reference_dir_for_relative_patterns, current_pattern_to_process)

        matched_by_glob_module = glob.glob(full_pattern_for_glob_module, recursive=True)

        if not matched_by_glob_module and not is_wildcard_pattern:
            abs_path = os.path.abspath(full_pattern_for_glob_module)
            initial_collected_paths.add(abs_path)
        else:
            for p_str in matched_by_glob_module:
                initial_collected_paths.add(os.path.abspath(p_str)) 

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
                        
                        # Prune ignored directories in-place
                        if ignore_matcher:
                            dirs[:] = [d for d in dirs if not ignore_matcher.matches(os.path.join(current_root_abs, d), True)]
                        
                        # Add current dir (if not root of walk which is already added)
                        if current_root_abs != path_str_abs:
                             final_collected_paths.add(current_root_abs)

                        for d_name in dirs:
                            final_collected_paths.add(os.path.abspath(os.path.join(current_root_abs, d_name)))
                        
                        for f_name in files:
                            f_abs = os.path.abspath(os.path.join(current_root_abs, f_name))
                            if ignore_matcher and ignore_matcher.matches(f_abs, False):
                                continue
                            final_collected_paths.add(f_abs)
                            
                except OSError as e:
                    print(f"Warning: Could not walk directory {path_str_abs}: {e}", file=sys.stderr)

    return sorted(list(final_collected_paths))


def is_safe_path(target_root, path_to_join):
    """
    Ensures that joining path_to_join to target_root does not escape target_root.
    """
    target_root_abs = os.path.abspath(target_root)
    joined_path = os.path.abspath(os.path.join(target_root_abs, path_to_join))
    return os.path.commonpath([target_root_abs, joined_path]) == target_root_abs


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
            line = line_raw.rstrip('\n\r') 

            if line.startswith("<|||file_start="): 
                if current_file_handle:
                    current_file_handle.write("".join(file_content_buffer))
                    file_content_buffer = []
                    current_file_handle.close()
                    print(f"Extracted: {current_file_path_str}")
                
                current_file_path_str = line[FSL:-FEL]
                
                # Security Check: Path Traversal
                if not is_safe_path(target_dir_path, current_file_path_str):
                    print(f"Warning: Skipping unsafe path at line {line_num}: {current_file_path_str}", file=sys.stderr)
                    current_file_handle = None
                    current_file_path_str = None
                    continue

                full_path = os.path.join(target_dir_path, current_file_path_str)
                try:
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    current_file_handle = open(full_path, "w", encoding="utf-8")
                except Exception as e:
                    print(f"Error creating file {full_path}: {e}", file=sys.stderr)
                    current_file_handle = None

            elif line == "<|||file_end|||>": 
                if current_file_handle:
                    current_file_handle.write("".join(file_content_buffer))
                    file_content_buffer = []
                    current_file_handle.close()
                    print(f"Extracted: {current_file_path_str}")
                    current_file_handle = None
                    current_file_path_str = None
                else:
                    # Report orphan tags
                    print(f"Warning: Encountered <|||file_end|||> without an active file context near line {line_num}.", file=sys.stderr)


            elif line.startswith("<|||dir="): 
                if current_file_handle: 
                    file_content_buffer.append(line_raw)
                else:
                    dir_path_str = line[DIRSL:-DIREL]
                    
                    # Security Check: Path Traversal
                    if not is_safe_path(target_dir_path, dir_path_str):
                        print(f"Warning: Skipping unsafe directory path: {dir_path_str}", file=sys.stderr)
                        continue

                    full_path = os.path.join(target_dir_path, dir_path_str)
                    try:
                        os.makedirs(full_path, exist_ok=True)
                        print(f"Created directory: {dir_path_str}")
                    except Exception as e:
                        print(f"Error creating directory {full_path}: {e}", file=sys.stderr)


            elif current_file_handle:
                file_content_buffer.append(line_raw) 

        if current_file_handle:
            current_file_handle.write("".join(file_content_buffer))
            current_file_handle.close()
            print(f"Extracted (EOF): {current_file_path_str}")


def list_fml_archive(archive_file_path):
    """List the contents of an FML archive."""
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
            line = line_raw.rstrip('\n\r') 
            if line.startswith("<|||file_start="): 
                print(line[FSL:-FEL])
            elif line.startswith("<|||dir="): 
                print(line[DIRSL:-DIREL])

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

    if not is_create_mode and not args.extract and not args.list:
        print("Error: No operation could be determined. Specify -c, -x, or -t, or provide input for creation.", file=sys.stderr)
        print("Try 'fmlpack --help' for more information.", file=sys.stderr)
        sys.exit(1)

    if is_create_mode:
        if not args.input:
            print("Error: At least one input file or folder is required for archive creation.", file=sys.stderr)
            sys.exit(1)

        output_file_path = args.file if args.file else '-'

        # Determine base directory for operations (defaults to CWD)
        if args.directory:
            base_dir_for_creation = os.path.abspath(args.directory)
            if not os.path.isdir(base_dir_for_creation):
                print(f"Error: Directory specified with -C/--directory does not exist: {base_dir_for_creation}", file=sys.stderr)
                sys.exit(1)
        else:
            base_dir_for_creation = os.getcwd()

        # Load ignore matcher (search upwards from base_dir for gitignore)
        ignore_matcher = load_ignore_matcher(base_dir_for_creation, args.gitignore)

        # Collect files, passing the matcher to prune during traversal
        all_files_and_folders_to_archive = expand_and_collect_paths(args.input, base_dir_for_creation, ignore_matcher)
        
        # Calculate the root for relative paths in the FML archive
        if args.directory:
             root_dir_for_fml = base_dir_for_creation
        else:
             # Pass base_dir_for_creation to handle '.' correctly
             root_dir_for_fml = get_common_base_dir(all_files_and_folders_to_archive, base_dir_for_creation)

        fml_content_lines, errors = generate_fml(root_dir_for_fml, all_files_and_folders_to_archive, args.exclude, args.include_spec, ignore_matcher=ignore_matcher)

        if output_file_path == '-':
            try:
                # FIX: Use buffer write to support UTF-8 on Windows consoles without crash
                sys.stdout.buffer.write("".join(fml_content_lines).encode("utf-8"))
                sys.stdout.buffer.flush()
            except BrokenPipeError:
                try:
                    sys.stderr.close() 
                except Exception: 
                    pass 
                sys.exit(0) 
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
