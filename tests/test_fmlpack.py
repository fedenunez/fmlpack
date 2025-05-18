import pytest
import os
import sys
import subprocess
import pathlib
import shutil
import io
from unittest.mock import patch, mock_open

# Attempt to import fmlpack module or its functions.
# This assumes fmlpack.py is in the PYTHONPATH or accessible.
try:
    from fmlpack import (
        process_arguments, get_fml_spec, get_relative_path, is_binary_file,
        is_excluded, generate_fml, get_common_base_dir, expand_and_collect_paths,
        extract_fml_archive, list_fml_archive, main as fmlpack_main
    )
    FMLPACK_MODULE_IMPORTED = True
except ImportError:
    FMLPACK_MODULE_IMPORTED = False
    # Define dummy functions if direct import fails, for unit tests that might still run.
    # CLI tests will use subprocess and won't rely on these dummies.
    def process_arguments(): raise NotImplementedError("fmlpack module not imported")
    def get_fml_spec(): return "DUMMY FML SPEC" # Return a known string for tests that might use it
    def get_relative_path(r, f): return os.path.relpath(f,r)
    def is_binary_file(f): return b"\x00" in pathlib.Path(f).read_bytes()[:1024] # Basic mock
    def is_excluded(f, p): return False # Simplistic mock
    def generate_fml(r, i, e, s): return ([],[])
    def get_common_base_dir(p): return os.getcwd() if not p else os.path.commonpath([os.path.dirname(x) if '.' in os.path.basename(x) else x for x in p])
    def expand_and_collect_paths(i,r): return []
    def extract_fml_archive(a, t, ad=None): raise NotImplementedError("fmlpack module not imported")
    def list_fml_archive(a): raise NotImplementedError("fmlpack module not imported")
    def fmlpack_main(): raise NotImplementedError("fmlpack module not imported")


# Determine the command to run fmlpack script via subprocess.
# Assumes this test file (test_fmlpack.py) is at the root of the project,
# and fmlpack.py is located at 'src/fmlpack.py'.
_current_file_path = pathlib.Path(__file__).resolve()
_project_root_dir = _current_file_path.parent # Assumes test_fmlpack.py is in project root
_fmlpack_script_location = _project_root_dir / "src" / "fmlpack.py"

if not _fmlpack_script_location.exists():
    # Fallback if structure is different, e.g., tests/test_fmlpack.py
    _project_root_dir = _current_file_path.parent.parent
    _fmlpack_script_location = _project_root_dir / "src" / "fmlpack.py"

FMLPACK_CMD_FOR_SUBPROCESS = [sys.executable, str(_fmlpack_script_location)]


# --- Helper Functions ---
def create_test_structure(base_path: pathlib.Path):
    """Creates a standard directory structure for testing."""
    (base_path / "dir1").mkdir()
    (base_path / "dir2").mkdir()
    (base_path / "dir1" / "file1a.txt").write_text("content1a", encoding="utf-8")
    (base_path / "dir1" / "file1b.txt").write_text("content1b", encoding="utf-8")
    (base_path / "file_root.txt").write_text("root content", encoding="utf-8")
    (base_path / "dir2" / "sub_dir").mkdir()
    (base_path / "dir2" / "sub_dir" / "file_sub.txt").write_text("sub content", encoding="utf-8")
    (base_path / "empty_dir").mkdir()
    with open(base_path / "binary_file.bin", "wb") as f:
        f.write(b"binary\x00content")
    (base_path / "unicode_file.txt").write_text("Привет, мир!", encoding="utf-8") # Hello, world! in Russian
    (base_path / "file with spaces.txt").write_text("content of file with spaces", encoding="utf-8")
    (base_path / "file_no_newline.txt").write_text("no newline at end", encoding="utf-8")


# --- Pytest Fixtures ---
@pytest.fixture
def temp_test_dir(tmp_path: pathlib.Path):
    """Creates a temporary directory with a standard test structure."""
    create_test_structure(tmp_path)
    return tmp_path

@pytest.fixture
def mock_args(mocker):
    """Fixture to mock sys.argv for process_arguments tests."""
    return lambda args_list: mocker.patch.object(sys, 'argv', ['fmlpack.py'] + args_list)

# --- Unit Tests for Helper Functions (if directly imported) ---
@pytest.mark.skipif(not FMLPACK_MODULE_IMPORTED, reason="fmlpack module not directly importable")
class TestHelperFunctions:
    def test_get_relative_path(self):
        assert get_relative_path("/base", "/base/file.txt") == "file.txt"
        assert get_relative_path("/base", "/base/dir/file.txt") == os.path.join("dir", "file.txt")
        # On Windows, paths might be tricky. os.path.join ensures platform independence.
        # Test with current dir reference
        cwd = os.getcwd()
        assert get_relative_path(cwd, os.path.join(cwd, "file.txt")) == "file.txt"


    def test_is_binary_file(self, tmp_path: pathlib.Path):
        text_file = tmp_path / "test.txt"
        text_file.write_text("hello", encoding="utf-8")
        assert not is_binary_file(str(text_file))

        binary_file_null = tmp_path / "test_null.bin"
        binary_file_null.write_bytes(b"hello\x00world")
        assert is_binary_file(str(binary_file_null))

        non_utf8_file = tmp_path / "test_bad_encoding.txt"
        non_utf8_file.write_bytes(b'\x80abc') # \x80 is invalid in UTF-8 start
        assert is_binary_file(str(non_utf8_file))

        empty_file = tmp_path / "empty.txt"
        empty_file.touch()
        assert not is_binary_file(str(empty_file))


    def test_is_excluded(self):
        assert is_excluded("path/to/file.txt", ["*.txt"])
        assert is_excluded("path/to/file.txt", ["file.txt"])
        assert is_excluded("path/to/file.txt", ["path/to/*"])
        assert is_excluded("path/to/file.txt", ["path*"])
        assert not is_excluded("path/to/file.doc", ["*.txt"])
        assert is_excluded("config.pyc", ["*.pyc"])
        assert is_excluded(os.path.join("somedir", "other.pyc"), ["*.pyc"])
        assert is_excluded(os.path.join(".git", "config"), [".git"])
        assert is_excluded(os.path.join("build", "lib", "file.so"), ["build"])
        assert is_excluded(os.path.join("a", "b", "c.log"), ["*c.log"])
        # Ensure "c.doc" is not excluded by "c.log" or "*.txt" patterns.
        assert not is_excluded(os.path.join("a", "b", "c.doc"), ["c.log", "*.txt"]) # Match full segment or pattern


    def test_get_common_base_dir(self, tmp_path: pathlib.Path):
        d1 = tmp_path / "d1"
        f1 = d1 / "f1.txt"
        d2 = d1 / "d2"
        f2 = d2 / "f2.txt"
        d3 = tmp_path / "d3"
        f3 = d3 / "f3.txt"

        for p in [f1, f2, f3]:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()

        assert pathlib.Path(get_common_base_dir([str(f1)])) == d1
        assert pathlib.Path(get_common_base_dir([str(d1)])) == d1
        assert pathlib.Path(get_common_base_dir([str(f1), str(f2)])) == d1
        assert pathlib.Path(get_common_base_dir([str(f1), str(f2), str(f3)])) == tmp_path
        assert pathlib.Path(get_common_base_dir([])) == pathlib.Path(os.getcwd())

        ne_d1 = tmp_path / "ne_d1"
        ne_f1 = ne_d1 / "ne_f1.txt"
        ne_d2 = ne_d1 / "ne_d2"
        ne_f2 = ne_d2 / "ne_f2.txt"
        assert pathlib.Path(get_common_base_dir([str(ne_f1), str(ne_f2)])) == ne_d1


    def test_expand_and_collect_paths(self, temp_test_dir: pathlib.Path):
        base_str = str(temp_test_dir)
        
        paths = expand_and_collect_paths(["file_root.txt"], base_str)
        assert str(temp_test_dir / "file_root.txt") in paths

        paths = expand_and_collect_paths(["dir1"], base_str)
        expected_dir1_contents = {
            str(temp_test_dir / "dir1"),
            str(temp_test_dir / "dir1" / "file1a.txt"),
            str(temp_test_dir / "dir1" / "file1b.txt"),
        }
        assert expected_dir1_contents.issubset(set(paths))

        paths = expand_and_collect_paths([os.path.join("dir1","*.txt")], base_str)
        expected_dir1_txt_files = { # glob might not return parent dir if only files matched
            str(temp_test_dir / "dir1" / "file1a.txt"),
            str(temp_test_dir / "dir1" / "file1b.txt"),
        }
        assert set(paths) == expected_dir1_txt_files

        paths_dot = expand_and_collect_paths(["."], base_str)
        assert str(temp_test_dir / "file_root.txt") in paths_dot
        assert str(temp_test_dir / "dir1" / "file1a.txt") in paths_dot
        assert str(temp_test_dir / "empty_dir") in paths_dot

        paths = expand_and_collect_paths(["non_existent_file.txt"], base_str)
        assert str(temp_test_dir / "non_existent_file.txt") in paths


# --- Unit Tests for FML Generation/Parsing Logic (if directly imported) ---
@pytest.mark.skipif(not FMLPACK_MODULE_IMPORTED, reason="fmlpack module not directly importable")
class TestFmlLogic:
    def test_generate_fml_basic(self, temp_test_dir: pathlib.Path):
        files_to_archive = [
            str(temp_test_dir / "file_root.txt"),
            str(temp_test_dir / "dir1" / "file1a.txt")
        ]
        fml_content_lines, errors = generate_fml(str(temp_test_dir), files_to_archive, [], False)
        fml_content = "".join(fml_content_lines)

        assert not errors
        assert "<|||file_start=file_root.txt|||>\nroot content\n<|||file_end|||>\n" in fml_content
        assert f"<|||file_start={os.path.join('dir1', 'file1a.txt')}|||>\ncontent1a\n<|||file_end|||>\n" in fml_content
        assert f"<|||dir=dir1|||>\n" in fml_content # Parent dir

    def test_generate_fml_file_no_newline(self, temp_test_dir: pathlib.Path):
        files_to_archive = [str(temp_test_dir / "file_no_newline.txt")]
        fml_content_lines, errors = generate_fml(str(temp_test_dir), files_to_archive, [], False)
        fml_content = "".join(fml_content_lines)
        assert not errors
        # generate_fml should add a newline if it's missing
        assert "<|||file_start=file_no_newline.txt|||>\nno newline at end\n<|||file_end|||>\n" in fml_content


    def test_extract_fml_basic(self, tmp_path: pathlib.Path):
        fml_content = (
            "<|||dir=mydir|||>\n"
            "<|||file_start=mydir/test.txt|||>\nHello FML\n<|||file_end|||>\n"
            "<|||file_start=another.txt|||>\nAnother file\n<|||file_end|||>\n"
        )
        fml_file = tmp_path / "test.fml"
        fml_file.write_text(fml_content, encoding="utf-8")
        extract_dir = tmp_path / "extracted"
        
        # Capture stdout for extract messages
        with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
            extract_fml_archive(str(fml_file), str(extract_dir))
            output = mock_stdout.getvalue()

        assert (extract_dir / "mydir").is_dir()
        assert (extract_dir / "mydir" / "test.txt").read_text(encoding="utf-8") == "Hello FML\n"
        assert (extract_dir / "another.txt").read_text(encoding="utf-8") == "Another file\n"
        assert "Created directory: mydir" in output
        assert "Extracted: mydir/test.txt" in output


    def test_extract_fml_malformed_missing_end_tag(self, tmp_path: pathlib.Path, capsys):
        fml_content = "<|||file_start=test.txt|||>\nContent without end tag"
        fml_file = tmp_path / "test.fml"
        fml_file.write_text(fml_content, encoding="utf-8")
        extract_dir = tmp_path / "extracted"

        # Use capsys for direct calls if they print to original sys.stdout/stderr
        # extract_fml_archive prints to sys.stdout
        extract_fml_archive(str(fml_file), str(extract_dir))
        captured = capsys.readouterr() # For prints made by extract_fml_archive

        assert (extract_dir / "test.txt").exists()
        assert (extract_dir / "test.txt").read_text(encoding="utf-8") == "Content without end tag"
        assert "Extracted (EOF): test.txt" in captured.out


    def test_list_fml_archive(self, tmp_path: pathlib.Path, capsys):
        fml_content = (
            "<|||dir=data|||>\n"
            "<|||file_start=data/info.txt|||>\nSome info\n<|||file_end|||>\n"
        )
        fml_file = tmp_path / "test.fml"
        fml_file.write_text(fml_content, encoding="utf-8")
        list_fml_archive(str(fml_file))
        captured = capsys.readouterr()
        assert captured.out == "data\ndata/info.txt\n"


# --- CLI (End-to-End) Tests using subprocess ---
class TestCliCommands:
    
    def run_fmlpack(self, args, std_input=None, cwd=None, expect_success=True):
        if not _fmlpack_script_location.exists():
             pytest.skip(f"fmlpack.py not found at expected location: {_fmlpack_script_location}")
        
        cmd = FMLPACK_CMD_FOR_SUBPROCESS + args
        process = subprocess.run(
            cmd,
            input=std_input, # Pass string directly if text=True, subprocess handles encoding
            capture_output=True,
            text=True, # Decodes stdout/stderr to text, expects string input
            encoding='utf-8', # Specify encoding for text mode
            check=False, # Do not check automatically, we'll assert on returncode
            cwd=str(cwd) if cwd else None # Ensure cwd is string
        )
        if expect_success and process.returncode != 0:
            print(f"Stdout: {process.stdout}")
            print(f"Stderr: {process.stderr}")
            pytest.fail(f"CLI command {' '.join(cmd)} failed with exit code {process.returncode}")
        return process

    def test_cli_help(self):
        result = self.run_fmlpack(["--help"], expect_success=True)
        assert "usage:" in result.stdout.lower() # Changed from fmlpack.py to general usage
        assert "--create" in result.stdout
        assert "--extract" in result.stdout

    def test_cli_spec_help(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["--spec-help"], cwd=temp_test_dir, expect_success=True)
        # Cannot directly compare with get_fml_spec() if module not imported
        # So check for key phrases from the spec.
        assert "# Filesystem Markup Language (FML)" in result.stdout
        assert "<|||file_start=${filepath}|||>" in result.stdout


    def test_cli_create_basic_stdout(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c", "file_root.txt"], cwd=temp_test_dir, expect_success=True)
        assert "<|||file_start=file_root.txt|||>\nroot content\n<|||file_end|||>\n" in result.stdout
        assert not result.stderr.strip()


    def test_cli_create_to_file(self, temp_test_dir: pathlib.Path):
        output_fml = temp_test_dir / "archive.fml"
        result = self.run_fmlpack(["-c", "file_root.txt", "-f", str(output_fml)], cwd=temp_test_dir, expect_success=True)
        assert output_fml.exists()
        content = output_fml.read_text(encoding="utf-8")
        assert "<|||file_start=file_root.txt|||>\nroot content\n<|||file_end|||>\n" in content
        assert f"FML archive created: {str(output_fml)}" in result.stdout
        assert not result.stderr.strip()

    def test_cli_create_file_no_newline_at_end(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c", "file_no_newline.txt"], cwd=temp_test_dir, expect_success=True)
        # fmlpack should add a newline to the content in the FML
        expected_fml_part = "<|||file_start=file_no_newline.txt|||>\nno newline at end\n<|||file_end|||>\n"
        assert expected_fml_part in result.stdout

    def test_cli_create_with_C_option(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c", "-C", "dir1", "file1a.txt"], cwd=temp_test_dir, expect_success=True)
        assert "<|||file_start=file1a.txt|||>\ncontent1a\n<|||file_end|||>\n" in result.stdout
        assert "dir1/file1a.txt" not in result.stdout # Path should be relative to -C dir

    def test_cli_create_with_dot_input(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c", "."], cwd=temp_test_dir, expect_success=True)
        assert "<|||file_start=file_root.txt|||>" in result.stdout
        assert f"<|||file_start={os.path.join('dir1','file1a.txt')}|||>" in result.stdout
        assert "<|||dir=empty_dir|||>" in result.stdout

    def test_cli_create_with_exclude(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(
            ["-c", ".", "--exclude", "binary_file.bin", "--exclude", "dir2"],
            cwd=temp_test_dir, expect_success=True # Command itself succeeds, errors are in stderr
        )
        assert "<|||file_start=binary_file.bin|||>" not in result.stdout
        assert f"<|||file_start={os.path.join('dir2','sub_dir','file_sub.txt')}|||>" not in result.stdout
        assert "excluding: binary_file.bin" in result.stderr.lower()
        # Exact message for dir2 depends on how exclusion is reported for directories that contain other items
        # It should prevent dir2 and its contents from being added.
        assert "excluding: dir2" in result.stderr.lower() or f"excluding: {os.path.join('dir2','')}" in result.stderr.lower()


    def test_cli_create_include_spec(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c", "file_root.txt", "--include-spec"], cwd=temp_test_dir, expect_success=True)
        assert "<|||file_start=fmlpack-spec.md|||>" in result.stdout
        assert "# Filesystem Markup Language (FML)" in result.stdout # Check part of spec content

    def test_cli_create_non_existent_input(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c", "non_existent_file.txt"], cwd=temp_test_dir, expect_success=True) # cmd is success
        assert "<|||file_start=non_existent_file.txt|||>" not in result.stdout
        # Check for the specific error message format after fix in fmlpack.py
        expected_error_msg = "input item not found: non_existent_file.txt (resolved to "
        assert expected_error_msg in result.stderr.lower()
        assert str(temp_test_dir / "non_existent_file.txt").lower() in result.stderr.lower()


    def test_cli_extract_basic(self, temp_test_dir: pathlib.Path):
        fml_content = (
            "<|||dir=ex_dir|||>\n"
            "<|||file_start=ex_dir/data.txt|||>\nExtract Me\n<|||file_end|||>\n"
        )
        fml_file = temp_test_dir / "myarchive.fml"
        fml_file.write_text(fml_content, encoding="utf-8")

        result = self.run_fmlpack(["-x", "-f", str(fml_file)], cwd=temp_test_dir, expect_success=True)
        assert "Extracted: ex_dir/data.txt" in result.stdout
        assert "Created directory: ex_dir" in result.stdout
        assert (temp_test_dir / "ex_dir" / "data.txt").read_text(encoding="utf-8") == "Extract Me\n"


    def test_cli_extract_with_C_option(self, temp_test_dir: pathlib.Path):
        fml_content = "<|||file_start=hello.txt|||>\nHello Again\n<|||file_end|||>\n"
        fml_file = temp_test_dir / "myarchive.fml"
        fml_file.write_text(fml_content, encoding="utf-8")
        extract_destination = temp_test_dir / "specific_output"

        result = self.run_fmlpack(["-x", "-f", str(fml_file), "-C", str(extract_destination)], cwd=temp_test_dir, expect_success=True)
        assert (extract_destination / "hello.txt").read_text(encoding="utf-8") == "Hello Again\n"


    def test_cli_extract_from_stdin(self, temp_test_dir: pathlib.Path):
        fml_content = "<|||file_start=stdin_test.txt|||>\nInput from pipe\n<|||file_end|||>\n"
        # Extract to current working directory (temp_test_dir)
        result = self.run_fmlpack(["-x"], std_input=fml_content, cwd=temp_test_dir, expect_success=True)
        assert (temp_test_dir / "stdin_test.txt").read_text(encoding="utf-8") == "Input from pipe\n"

    def test_cli_extract_non_existent_archive_file(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-x", "-f", "non_existent.fml"], cwd=temp_test_dir, expect_success=False)
        assert result.returncode == 1
        assert "error: archive file not found: non_existent.fml" in result.stderr.lower()

    def test_cli_list_basic(self, temp_test_dir: pathlib.Path):
        fml_content = (
            "<|||dir=listed_dir|||>\n"
            "<|||file_start=listed_dir/file.txt|||>\nContent\n<|||file_end|||>\n"
        )
        fml_file = temp_test_dir / "list_archive.fml"
        fml_file.write_text(fml_content, encoding="utf-8")
        result = self.run_fmlpack(["-t", "-f", str(fml_file)], cwd=temp_test_dir, expect_success=True)
        assert result.stdout == "listed_dir\nlisted_dir/file.txt\n"

    def test_cli_list_from_stdin(self, temp_test_dir: pathlib.Path):
        fml_content = "<|||file_start=stdin_list_test.txt|||>\nContent\n<|||file_end|||>\n"
        result = self.run_fmlpack(["-t"], std_input=fml_content, cwd=temp_test_dir, expect_success=True)
        assert result.stdout == "stdin_list_test.txt\n"

    def test_cli_error_multiple_modes(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c", "-x", "some_input"], cwd=temp_test_dir, expect_success=False)
        assert result.returncode == 1
        assert "error: only one of --create, --extract, or --list can be specified" in result.stderr.lower()

    def test_cli_error_create_no_input(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c"], cwd=temp_test_dir, expect_success=False)
        assert result.returncode == 1
        assert "error: at least one input file or folder is required" in result.stderr.lower()

    def test_cli_error_extract_list_no_archive_or_pipe(self, temp_test_dir: pathlib.Path):
        # This test relies on the default behavior of subprocess where stdin is not a TTY that sys.stdin.isatty()
        # would make the script think it is interactive.
        # fmlpack.py checks if -f is missing AND sys.stdin.isatty() to error.
        # If -f is missing and stdin is NOT a TTY (like in subprocess), it expects data from stdin.
        # If no data is piped, it might hang or process empty input.
        # The current fmlpack.py logic in main():
        #   if not archive_file_path and (args.extract or args.list) and sys.stdin.isatty(): -> error
        #   if not archive_file_path and (args.extract or args.list) and not sys.stdin.isatty(): archive_file_path = '-'
        # So, if run via subprocess with no -f and no input, it should try to read from empty stdin.
        
        # Test extract with no -f and no stdin data (simulating isatty() is hard, focusing on no input data)
        # With the new final check in main(), this should error out if it defaults to reading stdin
        # but no mode (-x or -t) is explicitly given to consume stdin.
        # If -x or -t is given and no -f, it uses stdin. Empty stdin is valid FML (0 files/dirs).
        result_extract = self.run_fmlpack(["-x"], cwd=temp_test_dir, expect_success=True) # Reads from empty stdin, no error code.
        assert result_extract.stdout == "" # No files extracted from empty input
        assert result_extract.stderr == "" # No errors for empty FML

        # If the goal is to test the "stdin is a TTY" error, that's hard with subprocess.
        # The original test was:
        #   assert "error: -f/--file or piped input is required for --extract or --list" in result_extract.stderr.lower()
        # This message is for when stdin.isatty() is true.

    def test_cli_default_mode_detection_create_with_input(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["file_root.txt"], cwd=temp_test_dir, expect_success=True)
        assert "<|||file_start=file_root.txt|||>" in result.stdout

    def test_cli_default_mode_no_op_no_input(self, temp_test_dir: pathlib.Path):
        # With the added check in fmlpack.py main(), this should now fail with rc 1
        result = self.run_fmlpack([], cwd=temp_test_dir, expect_success=False)
        assert result.returncode == 1
        # The error message might be from the new check or the isatty() check depending on env.
        assert "error: no operation" in result.stderr.lower()


    def test_cli_create_unicode_filename_and_content(self, temp_test_dir: pathlib.Path):
        # temp_test_dir already creates "unicode_file.txt" with "Привет, мир!"
        unicode_filename_os = "unicode_file.txt" # The actual filename on disk
        unicode_content_os = "Привет, мир!"

        result_create = self.run_fmlpack(["-c", unicode_filename_os], cwd=temp_test_dir, expect_success=True)
        expected_fml = f"<|||file_start={unicode_filename_os}|||>\n{unicode_content_os}\n<|||file_end|||>\n"
        assert expected_fml in result_create.stdout

        extract_dir = temp_test_dir / "extract_unicode"
        result_extract = self.run_fmlpack(["-x", "-C", str(extract_dir)], std_input=result_create.stdout, cwd=temp_test_dir, expect_success=True)
        
        extracted_file_path = extract_dir / unicode_filename_os
        assert extracted_file_path.exists()
        # Ensure reading with UTF-8
        read_content = extracted_file_path.read_text(encoding='utf-8')
        assert read_content == unicode_content_os + "\n"


if __name__ == "__main__":
    # This allows running pytest on this file directly.
    # E.g., python test_fmlpack.py
    # Requires pytest to be installed and accessible.
    os.environ["PYTHONPATH"] = str(_project_root_dir / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")
    sys.exit(pytest.main([__file__] + sys.argv[1:]))

