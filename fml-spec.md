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
    <|||file_end|||>
    ```

This example creates a directory `projects` and a file `plan.txt` within it, containing the specified text.

    ```fml
    <|||file_start=documents/reports/summary.txt|||>
    Summary of the quarterly report.
    <|||file_end|||>
    ```

This example creates a directory `documents` with a subdirectory `reports`, and a file `summary.txt` within `reports`, containing the specified text.
