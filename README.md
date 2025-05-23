# fmlpack

**`fmlpack`** by [fedenunez](https://github.com/fedenunez) is a command-line tool that improves how you interact with Large Language Models (LLMs) by seamlessly bridging your local file system with any LLM. It acts like a 'tar' for LLMs, packaging entire file trees (codebases, documentation, etc.) into a single, text-based FML (Filesystem Markup Language) document that LLMs can easily understand and generate. `fmlpack` then unpacks FML output from an LLM back into your file system, enabling a complete and effortless round-trip for your project files.

## Installation

```bash
pip install fmlpack
```

## Integration and Usage Examples

### Working with `tulp`

`fmlpack` is a great companion to `tulp` (another tool by fedenunez, available at [github.com/fedenunez/tulp](https://github.com/fedenunez/tulp)). `tulp` is a CLI tool for interacting with LLMs. You can easily pipe FML content generated by `fmlpack` directly to `tulp`, or have `tulp` generate FML content that `fmlpack` can then extract.

**Examples:**

1.  **Send the current directory's content (as FML) to `tulp` for processing:**
    ```bash
    fmlpack -c . | tulp "Please review this code and suggest improvements:"
    ```

2.  **Ask `tulp` to generate code based on a prompt and save it as an FML file, then extract it:**
    ```bash
    # Assuming tulp is configured to output FML for such requests
    fmlpack --spec-help | tulp "Generate a Python project with a main.py and utils.py for a simple calculator, writing the code to the output in FML format" > project.fml
    fmlpack -x -f project.fml -C ./new_calculator_project
    ```

### General LLM Chat Interaction

For any chat-based LLM, you can:

1.  **Pack your project:**
    ```bash
    fmlpack -c /path/to/your/project > project_snapshot.fml
    ```
2.  **Copy and Paste:** Open `project_snapshot.fml`, copy its entire content, and paste it into the LLM's chat window.
3.  **Receive FML from LLM:** If the LLM generates code or files in FML format, copy that output, save it to a file (e.g., `llm_output.fml`), and then extract it:
    ```bash
    fmlpack -x -f llm_output.fml -C ./output_directory
    ```

### Linux Clipboard Integration with `xsel`

On Linux, `fmlpack` works wonderfully with clipboard tools like `xsel`:

1.  **Copy an entire directory structure (as FML) to the clipboard:**
    ```bash
    fmlpack -c . | xsel -b
    ```
    Now you can paste this FML into an LLM chat, an email, or anywhere else.

2.  **Create a file structure from FML content in the clipboard:**
    ```bash
    xsel -b | fmlpack -x -C ./target_directory
    ```
    This is useful if an LLM provides you with an FML block representing multiple files.

### Basic `fmlpack` Commands

*   **Create an FML archive:**
    ```bash
    fmlpack -c <input_path_or_paths...> -f output.fml
    fmlpack -c . # Output to stdout
    ```
*   **Extract files from an FML archive:**
    ```bash
    fmlpack -x -f input.fml -C <target_directory>
    cat input.fml | fmlpack -x -C <target_directory>
    ```
*   **List contents of an FML archive:**
    ```bash
    fmlpack -t -f input.fml
    cat input.fml | fmlpack -t
    ```
*   **Get help:**
    ```bash
    fmlpack --help
    ```
*   **Display FML Specification:**
    ```bash
    fmlpack --spec-help
    ```

## Why fmlpack and FML?

Working with Large Language Models (LLMs) often involves providing them with the content of multiple files, such as an entire codebase or a documentation folder. Manually copying and pasting individual files is cumbersome, error-prone, and loses the project's structural context.

`fmlpack` and FML provide a robust solution by:

*   **Packaging Projects:** Consolidating your chosen directories and text files into a single, coherent FML text stream for the LLM.
*   **LLM-Friendly Format:** FML's simple, clear tags for files and directories make it straightforward for an LLM to "see" the structure and content.
*   **Universal LLM Compatibility:** Being plain text, FML is compatible with **ANY** chat-based LLM or LLM API. No vendor lock-in or special model requirements.
*   **Maintaining Project Structure:** FML preserves relative file paths and directory organization, crucial for the LLM to understand file interrelations.
*   **Seamlessly Recreating LLM Output:** LLMs can generate or modify code using FML. `fmlpack` then reconstructs files and directories on your local system from this FML output.

The design of FML was inspired by the clarity of formats like ChatML, aiming for simplicity in representing structured file system data for AI interaction.

## The FML Format

FML employs simple tags to represent your file system: `<|||file_start=path/to/file.ext|||>` and `<|||file_end|||>` enclose file content, while `<|||dir=path/to/dir|||>` denotes directories. This clarity makes FML easy for both humans and LLMs to work with. `fmlpack` handles the conversion to and from this format seamlessly.

For a detailed explanation of the format, please see the [full FML Specification](fml-spec.md).
