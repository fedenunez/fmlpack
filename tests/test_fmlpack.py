import pytest
import os
import sys
import subprocess
import pathlib
import shutil
import io
import stat
from unittest.mock import patch, mock_open, MagicMock

# Determine the paths
_current_file_path = pathlib.Path(__file__).resolve()
_project_root_dir = _current_file_path.parent.parent
_fmlpack_script_location = _project_root_dir / "src" / "fmlpack.py"

# Fallback path logic
if not _fmlpack_script_location.exists():
    _fmlpack_script_location = pathlib.Path("src/fmlpack.py").resolve()
    _project_root_dir = _fmlpack_script_location.parent.parent

# --- Fix for import precedence ---
# Ensure we import the local src/fmlpack.py, not an installed system version.
_src_dir = _project_root_dir / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

# Attempt to import fmlpack module or its functions.
try:
    from fmlpack import (
        process_arguments, get_fml_spec, get_relative_path, is_binary_file,
        is_excluded_cli, generate_fml, get_common_base_dir, expand_and_collect_paths,
        extract_fml_archive, list_fml_archive, IgnoreMatcher, main as fmlpack_main,
        find_project_root, load_ignore_matcher
    )
    FMLPACK_MODULE_IMPORTED = True
except ImportError:
    FMLPACK_MODULE_IMPORTED = False
    # Define dummy functions if direct import fails.
    def get_relative_path(r, f): return os.path.relpath(f,r)
    def is_binary_file(f): return False
    def is_excluded_cli(f, p): return False
    def get_common_base_dir(p, c=None): return os.getcwd()
    def expand_and_collect_paths(i,r, m=None): return []
    def find_project_root(s): return s
    def load_ignore_matcher(s, g): return None
    def generate_fml(r, f, e, i, m=None): return [], []
    def extract_fml_archive(a, t, extra=None): pass
    def list_fml_archive(a): pass
    class IgnoreMatcher:
        def __init__(self, r, p): pass
        def matches(self, p, d): return False


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
    (base_path / "unicode_file.txt").write_text("Привет, мир!", encoding="utf-8") 
    (base_path / "file with spaces.txt").write_text("content of file with spaces", encoding="utf-8")
    (base_path / "file_no_newline.txt").write_text("no newline at end", encoding="utf-8")


# --- Pytest Fixtures ---
@pytest.fixture
def temp_test_dir(tmp_path: pathlib.Path):
    """Creates a temporary directory with a standard test structure."""
    create_test_structure(tmp_path)
    return tmp_path

# --- Unit Tests ---
@pytest.mark.skipif(not FMLPACK_MODULE_IMPORTED, reason="fmlpack module not directly importable")
class TestHelperFunctions:
    def test_get_fml_spec(self):
        assert len(get_fml_spec()) > 0

    def test_get_relative_path(self):
        assert get_relative_path("/base", "/base/file.txt") == "file.txt"
        assert get_relative_path("/base", "/base/dir/file.txt") == os.path.join("dir", "file.txt")

    def test_is_binary_file(self, tmp_path: pathlib.Path):
        text_file = tmp_path / "test.txt"
        text_file.write_text("hello", encoding="utf-8")
        assert not is_binary_file(str(text_file))
        binary_file_null = tmp_path / "test_null.bin"
        binary_file_null.write_bytes(b"hello\x00world")
        assert is_binary_file(str(binary_file_null))

    def test_is_excluded_cli(self):
        assert is_excluded_cli("path/to/file.txt", ["*.txt"])
        assert is_excluded_cli("path/to/file.txt", ["file.txt"])
        assert is_excluded_cli("a/b/c.log", ["*c.log"])
        assert not is_excluded_cli("path/to/file.doc", ["*.txt"])

    def test_get_common_base_dir_files_only(self, tmp_path: pathlib.Path):
        # Case: Just files provided
        d1 = tmp_path / "d1"
        d1.mkdir()
        f1 = d1 / "f1.txt"
        f1.touch()
        # Common base of a single file is its directory
        assert pathlib.Path(get_common_base_dir([str(f1)])) == d1

    def test_get_common_base_dir_directory_input(self, tmp_path: pathlib.Path):
        # Case: Directory provided (Standard Tar Behavior)
        # fmlpack -c mydir -> base should be parent of mydir, so archive contains mydir/file
        d1 = tmp_path / "d1"
        d1.mkdir()
        # Logic: if dir provided != cwd, step up
        assert pathlib.Path(get_common_base_dir([str(d1)], current_working_dir=tmp_path)) == tmp_path

    def test_get_common_base_dir_dot_input(self, tmp_path: pathlib.Path):
        # Case: Dot (.) provided
        # fmlpack -c . -> base should be . (cwd), so archive contains file (not ./file or name/file)
        assert pathlib.Path(get_common_base_dir([str(tmp_path)], current_working_dir=tmp_path)) == tmp_path

    def test_expand_and_collect_paths(self, temp_test_dir: pathlib.Path):
        base_str = str(temp_test_dir)
        # Test wildcard expansion
        paths = expand_and_collect_paths([os.path.join("dir1", "*.txt")], base_str)
        assert str(temp_test_dir / "dir1" / "file1a.txt") in paths
        assert str(temp_test_dir / "dir1" / "file1b.txt") in paths
        
        # Test directory recursion
        paths_dir = expand_and_collect_paths(["dir2"], base_str)
        assert str(temp_test_dir / "dir2" / "sub_dir" / "file_sub.txt") in paths_dir
        
    def test_expand_paths_dot(self, temp_test_dir: pathlib.Path):
        # Test expanding "."
        paths = expand_and_collect_paths([str(temp_test_dir)], str(temp_test_dir))
        assert str(temp_test_dir / "file_root.txt") in paths
        
    def test_expand_paths_walk_error(self, temp_test_dir: pathlib.Path):
        # Force os.walk to raise an error by mocking it, ensuring no crash
        with patch('os.walk', side_effect=OSError("Permission denied")):
            with patch('sys.stderr', new=io.StringIO()) as fake_err:
                expand_and_collect_paths([str(temp_test_dir / "dir1")], str(temp_test_dir))
                assert "Could not walk directory" in fake_err.getvalue()


@pytest.mark.skipif(not FMLPACK_MODULE_IMPORTED, reason="fmlpack module not directly importable")
class TestIgnoreMatcherLogic:
    def test_basic_ignores(self, tmp_path: pathlib.Path):
        matcher = IgnoreMatcher(str(tmp_path), ["*.log", "temp/"])
        
        # Should match
        assert matcher.matches(str(tmp_path / "error.log"), False)
        assert matcher.matches(str(tmp_path / "sub" / "access.log"), False)
        assert matcher.matches(str(tmp_path / "temp" / "file.txt"), False)
        assert matcher.matches(str(tmp_path / "temp"), True)

        # Should not match
        assert not matcher.matches(str(tmp_path / "main.py"), False)
        assert not matcher.matches(str(tmp_path / "temporary" / "file.txt"), False) # "temp/" matches dir only

    def test_anchored_ignores(self, tmp_path: pathlib.Path):
        matcher = IgnoreMatcher(str(tmp_path), ["/root_only.txt"])
        # Matches root_only.txt in base dir
        assert matcher.matches(str(tmp_path / "root_only.txt"), False)
        # Should NOT match root_only.txt in subdirectory
        assert not matcher.matches(str(tmp_path / "sub" / "root_only.txt"), False)

    def test_complex_ignores(self, tmp_path: pathlib.Path):
        # Testing various .gitignore rules logic in fallback matcher
        patterns = [
            "debug/",       # Directory only
            "*.tmp",        # Recursive pattern
            "!important.tmp", # Negation
            "/config.json"  # Anchored
        ]
        matcher = IgnoreMatcher(str(tmp_path), patterns)

        assert matcher.matches(str(tmp_path / "debug"), True)
        assert matcher.matches(str(tmp_path / "src" / "debug"), True)
        assert matcher.matches(str(tmp_path / "debug" / "log.txt"), False)
        
        # Directory only check - file named "debug" should NOT match
        assert not matcher.matches(str(tmp_path / "debug"), False)

        assert matcher.matches(str(tmp_path / "temp.tmp"), False)
        assert matcher.matches(str(tmp_path / "subdir" / "stuff.tmp"), False)
        
        # Negation check
        assert not matcher.matches(str(tmp_path / "important.tmp"), False)
        assert not matcher.matches(str(tmp_path / "subdir" / "important.tmp"), False)

        # Anchored check
        assert matcher.matches(str(tmp_path / "config.json"), False)
        assert not matcher.matches(str(tmp_path / "subdir" / "config.json"), False)
        
    def test_ignore_outside_root(self, tmp_path: pathlib.Path):
        matcher = IgnoreMatcher(str(tmp_path / "inner"), ["*.log"])
        # File outside root
        assert not matcher.matches(str(tmp_path / "outside.log"), False)
        
    def test_ignore_root_itself(self, tmp_path: pathlib.Path):
        matcher = IgnoreMatcher(str(tmp_path), ["foo"])
        assert not matcher.matches(str(tmp_path), True)

    def test_negation(self, tmp_path: pathlib.Path):
        matcher = IgnoreMatcher(str(tmp_path), ["*.log", "!important.log"])
        assert matcher.matches(str(tmp_path / "error.log"), False)
        assert not matcher.matches(str(tmp_path / "important.log"), False)
        
    def test_ignore_comments_and_blanks(self, tmp_path: pathlib.Path):
        patterns = ["# comment", "  ", "*.log"]
        matcher = IgnoreMatcher(str(tmp_path), patterns)
        assert matcher.matches(str(tmp_path / "test.log"), False)


@pytest.mark.skipif(not FMLPACK_MODULE_IMPORTED, reason="fmlpack module not directly importable")
class TestFmlLogic:
    def test_generate_fml_basic(self, temp_test_dir: pathlib.Path):
        files_to_archive = [str(temp_test_dir / "file_root.txt")]
        fml_content_lines, errors = generate_fml(str(temp_test_dir), files_to_archive, [], False)
        fml_content = "".join(fml_content_lines)
        assert "<|||file_start=file_root.txt|||>" in fml_content
        assert not errors

    def test_generate_fml_adds_newline(self, temp_test_dir: pathlib.Path):
        files = [str(temp_test_dir / "file_no_newline.txt")]
        fml_content_lines, _ = generate_fml(str(temp_test_dir), files, [], False)
        content = "".join(fml_content_lines)
        # We expect a newline to be appended before file_end
        assert "no newline at end\n<|||file_end|||>" in content
        
    def test_generate_fml_read_error(self, temp_test_dir: pathlib.Path):
        f = temp_test_dir / "unreadable.txt"
        f.touch()
        # Mock is_binary_file to False to force entry into the read block
        with patch("fmlpack.is_binary_file", return_value=False):
            # Mock open specifically for reading
            with patch("builtins.open", side_effect=OSError("Read permission denied")):
                fml, errors = generate_fml(str(temp_test_dir), [str(f)], [], False)
        assert len(errors) > 0
        assert "Could not process file" in errors[0]

    def test_extract_fml_basic(self, tmp_path: pathlib.Path):
        fml_content = "<|||file_start=test.txt|||>\nHello\n<|||file_end|||>\n"
        fml_file = tmp_path / "archive.fml"
        fml_file.write_text(fml_content, encoding="utf-8")
        
        extract_dir = tmp_path / "out"
        
        # Suppress print output for unit test
        with patch('sys.stdout', new=io.StringIO()):
             extract_fml_archive(str(fml_file), str(extract_dir))
        
        assert (extract_dir / "test.txt").read_text(encoding="utf-8") == "Hello\n"

    def test_extract_fml_stdin(self, tmp_path: pathlib.Path):
        fml_content = "<|||file_start=stdin.txt|||>\nFrom Stdin\n<|||file_end|||>\n"
        extract_dir = tmp_path / "out_stdin"
        
        with patch('sys.stdin', io.StringIO(fml_content)):
            with patch('sys.stdout', new=io.StringIO()):
                extract_fml_archive('-', str(extract_dir))
        
        assert (extract_dir / "stdin.txt").read_text(encoding="utf-8") == "From Stdin\n"
        
    def test_extract_fml_missing_archive(self, tmp_path: pathlib.Path):
        with pytest.raises(SystemExit) as e:
            with patch('sys.stderr', new=io.StringIO()) as fake_err:
                extract_fml_archive(str(tmp_path / "nonexistent.fml"), str(tmp_path))
        assert e.value.code == 1
        assert "Archive file not found" in fake_err.getvalue()
        
    def test_extract_fml_open_error(self, tmp_path: pathlib.Path):
        # Simulate access denied on the archive file itself
        archive = tmp_path / "locked.fml"
        archive.touch()
        with patch("builtins.open", side_effect=PermissionError("Denied")):
            with pytest.raises(SystemExit):
                with patch('sys.stderr', new=io.StringIO()) as fake_err:
                    extract_fml_archive(str(archive), str(tmp_path))
                    assert "Error opening archive" in fake_err.getvalue()

    def test_extract_fml_file_creation_error(self, tmp_path: pathlib.Path):
        fml_content = "<|||file_start=fail.txt|||>\ncontent\n<|||file_end|||>"
        archive = tmp_path / "valid.fml"
        archive.write_text(fml_content, encoding="utf-8")
        
        # We need to side_effect open: work for reading archive, fail for writing target
        real_open = open
        def side_effect(file, mode="r", *args, **kwargs):
            if "w" in mode:
                raise OSError("Write denied")
            return real_open(file, mode, *args, **kwargs)
            
        with patch("builtins.open", side_effect=side_effect):
            with patch('sys.stderr', new=io.StringIO()) as fake_err:
                with patch('sys.stdout', new=io.StringIO()):
                    extract_fml_archive(str(archive), str(tmp_path))
        assert "Error creating file" in fake_err.getvalue()
        
    def test_extract_fml_dir_creation_error(self, tmp_path: pathlib.Path):
        fml_content = "<|||dir=fail_dir|||>"
        archive = tmp_path / "valid.fml"
        archive.write_text(fml_content, encoding="utf-8")
        
        # Patch makedirs: Succeed for target root (first call), fail for FML dir (second call)
        with patch("os.makedirs", side_effect=[None, OSError("Mkdir failed")]) as mock_mkdir:
            with patch('sys.stderr', new=io.StringIO()) as fake_err:
                with patch('sys.stdout', new=io.StringIO()):
                    extract_fml_archive(str(archive), str(tmp_path))
        assert "Error creating directory" in fake_err.getvalue()

    def test_extract_fml_warn_extra_args(self, tmp_path):
        fml = tmp_path / "test.fml"
        fml.touch()
        with patch('sys.stderr', new=io.StringIO()) as fake_err:
            extract_fml_archive(str(fml), str(tmp_path), additional_files=["extra"])
            assert "Unexpected arguments" in fake_err.getvalue()

    def test_extract_fml_orphan_end_tag(self, tmp_path):
        content = "<|||file_end|||>\n"
        fml = tmp_path / "test.fml"
        fml.write_text(content, encoding="utf-8")
        with patch('sys.stderr', new=io.StringIO()) as fake_err:
            extract_fml_archive(str(fml), str(tmp_path))
            assert "without an active file context" in fake_err.getvalue()

    def test_extract_fml_dir_tag_in_content(self, tmp_path):
        content = "<|||file_start=f.txt|||>\nLine 1\n<|||dir=nested|||>\nLine 2\n<|||file_end|||>"
        fml = tmp_path / "test.fml"
        fml.write_text(content, encoding="utf-8")
        extract_fml_archive(str(fml), str(tmp_path))
        
        f_content = (tmp_path / "f.txt").read_text(encoding="utf-8")
        assert "<|||dir=nested|||>" in f_content
        assert not (tmp_path / "nested").exists()
        
    def test_list_fml_archive(self, tmp_path: pathlib.Path):
        archive = tmp_path / "list.fml"
        archive.write_text("<|||file_start=a|||>\n<|||dir=b|||>", encoding="utf-8")
        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            list_fml_archive(str(archive))
        assert "a" in fake_out.getvalue()
        assert "b" in fake_out.getvalue()
        
    def test_list_fml_missing_file(self, tmp_path: pathlib.Path):
        with pytest.raises(SystemExit):
            with patch('sys.stderr', new=io.StringIO()):
                list_fml_archive("missing.fml")


@pytest.mark.skipif(not FMLPACK_MODULE_IMPORTED, reason="fmlpack module not directly importable")
class TestProjectRootFinding:
    def test_find_project_root_git(self, tmp_path: pathlib.Path):
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        (proj_root / ".git").mkdir()
        (proj_root / "subdir").mkdir()
        
        assert find_project_root(str(proj_root / "subdir")) == str(proj_root)

    def test_find_project_root_ignore(self, tmp_path: pathlib.Path):
        proj_root = tmp_path / "ignore_proj"
        proj_root.mkdir()
        (proj_root / ".fmlpackignore").touch()
        (proj_root / "subdir").mkdir()
        
        assert find_project_root(str(proj_root / "subdir")) == str(proj_root)
        
    def test_find_project_root_fallback(self, tmp_path: pathlib.Path):
        # No marker, returns absolute start dir
        start = tmp_path / "deep"
        start.mkdir()
        assert find_project_root(str(start)) == str(start.resolve())

    def test_load_ignore_matcher(self, tmp_path: pathlib.Path):
        # Setup files
        (tmp_path / ".fmlpackignore").write_text("*.fmlpack\n", encoding="utf-8")
        (tmp_path / ".gitignore").write_text("*.gitignored\n", encoding="utf-8")
        
        # Load with gitignore enabled
        matcher = load_ignore_matcher(str(tmp_path), True)
        assert matcher.matches(str(tmp_path / "test.fmlpack"), False)
        assert matcher.matches(str(tmp_path / "test.gitignored"), False)
        
        # Load without gitignore
        matcher_no_git = load_ignore_matcher(str(tmp_path), False)
        assert matcher_no_git.matches(str(tmp_path / "test.fmlpack"), False)
        assert not matcher_no_git.matches(str(tmp_path / "test.gitignored"), False)
        
    def test_load_ignore_matcher_empty(self, tmp_path: pathlib.Path):
        assert load_ignore_matcher(str(tmp_path), False) is None

    def test_load_ignore_read_error(self, tmp_path: pathlib.Path):
        (tmp_path / ".gitignore").touch()
        with patch("builtins.open", side_effect=PermissionError("Denied")):
            # Should not crash
            matcher = load_ignore_matcher(str(tmp_path), True)
            # Should return matcher with default .git/ rule if flag is True
            assert matcher is not None
            assert matcher.matches(str(tmp_path / ".git" / "HEAD"), False)


@pytest.mark.skipif(not FMLPACK_MODULE_IMPORTED, reason="fmlpack module not directly importable")
class TestBinaryDetection:
    def test_binary_exception_handling(self, tmp_path: pathlib.Path):
        # Mock open to raise exception
        f = tmp_path / "unreadable"
        f.touch()
        with patch("builtins.open", side_effect=OSError("Read error")):
            # If reading fails, it should default to True (binary) to be safe
            assert is_binary_file(str(f)) is True
            
    def test_binary_unicode_error(self, tmp_path: pathlib.Path):
        f = tmp_path / "bad_unicode"
        # Write invalid utf-8 sequence
        f.write_bytes(b"\x80\x81")
        assert is_binary_file(str(f)) is True


@pytest.mark.skipif(not FMLPACK_MODULE_IMPORTED, reason="fmlpack module not directly importable")
class TestMainEntry:
    def test_main_no_args(self):
        # Should exit 1 and print usage to stderr
        with patch("sys.argv", ["fmlpack.py"]):
            with pytest.raises(SystemExit) as e:
                with patch("sys.stderr", new=io.StringIO()) as fake_err:
                    with patch("sys.stdin.isatty", return_value=True): # Simulating interactive shell
                        fmlpack_main()
            assert e.value.code == 1
            assert "Error: No operation specified" in fake_err.getvalue()

    def test_main_invalid_args(self):
        with patch("sys.argv", ["fmlpack.py", "--create", "--extract"]):
            with pytest.raises(SystemExit) as e:
                with patch("sys.stderr", new=io.StringIO()) as fake_err:
                    fmlpack_main()
            assert e.value.code == 1
            assert "Only one of" in fake_err.getvalue()
            
    def test_main_file_arg_logic(self):
        # Test the check "Error: -f/--file or piped input is required"
        with patch("sys.argv", ["fmlpack.py", "--list"]):
            with patch("sys.stdin.isatty", return_value=True):
                with pytest.raises(SystemExit):
                    with patch("sys.stderr", new=io.StringIO()) as fake_err:
                        fmlpack_main()
                        assert "is required" in fake_err.getvalue()
                        
    def test_main_broken_pipe(self):
        # Simulate broken pipe on stdout during create
        with patch("sys.argv", ["fmlpack.py", "-c", ".", "-f", "-"]):
            with patch("sys.stdin.isatty", return_value=False):
                with patch("fmlpack.generate_fml", return_value=(["data"], [])):
                    with patch("sys.stdout.write", side_effect=BrokenPipeError):
                        # Ensure sys.stderr is mocked so close() doesn't kill real stderr
                        with patch("sys.stderr", new=io.StringIO()):
                            with pytest.raises(SystemExit) as e:
                                fmlpack_main()
                            assert e.value.code == 0
                        
    def test_main_extract_warns_args(self, tmp_path):
        fml = tmp_path / "a.fml"
        fml.touch()
        with patch("sys.argv", ["fmlpack.py", "-x", "-f", str(fml), "extra_arg"]):
            with patch("sys.stderr", new=io.StringIO()) as fake_err:
                with patch("fmlpack.extract_fml_archive") as mock_extract:
                    fmlpack_main()
                    # We can't easily check stderr here because main calls extract...
                    # Wait, extract_fml_archive prints the warning.
                    # Since we verify unit test for extract_fml_archive prints warning, we assume main passes it.
                    mock_extract.assert_called_with(str(fml), ".", ["extra_arg"])
                    
    def test_main_list_warns_args(self, tmp_path):
        fml = tmp_path / "a.fml"
        fml.touch()
        with patch("sys.argv", ["fmlpack.py", "-t", "-f", str(fml), "extra_arg"]):
            with patch("sys.stderr", new=io.StringIO()) as fake_err:
                with patch("fmlpack.list_fml_archive"):
                    fmlpack_main()
                    assert "Warning: Input paths provided" in fake_err.getvalue()


# --- CLI Tests (Subprocess) ---
class TestCliCommands:
    
    def run_fmlpack(self, args, std_input=None, cwd=None, expect_success=True):
        if not _fmlpack_script_location.exists():
             pytest.skip(f"fmlpack.py not found at expected location: {_fmlpack_script_location}")
        
        cmd = FMLPACK_CMD_FOR_SUBPROCESS + args
        process = subprocess.run(
            cmd,
            input=std_input, 
            capture_output=True,
            text=True, 
            encoding='utf-8', 
            check=False,
            cwd=str(cwd) if cwd else None
        )
        if expect_success and process.returncode != 0:
            print(f"Stdout: {process.stdout}")
            print(f"Stderr: {process.stderr}")
            pytest.fail(f"CLI command {' '.join(cmd)} failed with exit code {process.returncode}")
        return process

    def test_cli_help(self):
        result = self.run_fmlpack(["--help"], expect_success=True)
        assert "usage:" in result.stdout.lower()
        assert "--create" in result.stdout

    def test_cli_spec_help(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["--spec-help"], cwd=temp_test_dir, expect_success=True)
        assert "# Filesystem Markup Language (FML)" in result.stdout

    def test_cli_create_basic_stdout(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c", "file_root.txt"], cwd=temp_test_dir, expect_success=True)
        assert "<|||file_start=file_root.txt|||>" in result.stdout

    def test_cli_create_to_file(self, temp_test_dir: pathlib.Path):
        output_fml = temp_test_dir / "archive.fml"
        self.run_fmlpack(["-c", "file_root.txt", "-f", str(output_fml)], cwd=temp_test_dir, expect_success=True)
        assert output_fml.exists()
        assert "<|||file_start=file_root.txt|||>" in output_fml.read_text(encoding="utf-8")

    def test_cli_create_multiple_files(self, temp_test_dir: pathlib.Path):
        # fmlpack -c file_root.txt dir1
        # Expectation: file_root.txt at root, dir1/file1a.txt
        result = self.run_fmlpack(["-c", "file_root.txt", "dir1"], cwd=temp_test_dir, expect_success=True)
        assert "<|||file_start=file_root.txt|||>" in result.stdout
        # Because we passed 'dir1', it acts like tar: preserves 'dir1' container
        assert "<|||dir=dir1|||>" in result.stdout
        assert "<|||file_start=dir1/file1a.txt|||>" in result.stdout

    def test_cli_create_absolute_paths(self, temp_test_dir: pathlib.Path):
        abs_p = str(temp_test_dir / "file_root.txt")
        result = self.run_fmlpack(["-c", abs_p], cwd=temp_test_dir, expect_success=True)
        # Should still be relative in archive
        assert "<|||file_start=file_root.txt|||>" in result.stdout

    def test_cli_create_include_spec(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c", "file_root.txt", "-s"], cwd=temp_test_dir, expect_success=True)
        assert "<|||file_start=fmlpack-spec.md|||>" in result.stdout
        assert "# Filesystem Markup Language (FML)" in result.stdout

    def test_cli_exclude_patterns(self, temp_test_dir: pathlib.Path):
        # Exclude using wildcard
        # Using "." -> Base is CWD.
        result = self.run_fmlpack(["-c", ".", "--exclude", "*.txt"], cwd=temp_test_dir, expect_success=True)
        assert "file_root.txt" not in result.stdout
        # binary_file.bin is ignored by binary check (default), so we check empty_dir
        assert "<|||dir=empty_dir|||>" in result.stdout

    def test_cli_multiple_excludes(self, temp_test_dir: pathlib.Path):
        # Exclude dir1 and unicode file
        result = self.run_fmlpack(["-c", ".", "--exclude", "dir1", "--exclude", "unicode_file.txt"], cwd=temp_test_dir, expect_success=True)
        assert "<|||dir=dir1|||>" not in result.stdout
        assert "file1a.txt" not in result.stdout
        assert "unicode_file.txt" not in result.stdout
        assert "<|||file_start=file_root.txt|||>" in result.stdout

    def test_cli_directory_change_create(self, temp_test_dir: pathlib.Path):
        # Change to dir1, archive ., output should be relative to dir1
        # Since input is ".", base is dir1. paths inside are "file1a.txt"
        result = self.run_fmlpack(["-c", ".", "-C", str(temp_test_dir / "dir1")], cwd=temp_test_dir, expect_success=True)
        assert "<|||file_start=file1a.txt|||>" in result.stdout
        assert "dir1/file1a.txt" not in result.stdout

    def test_cli_directory_change_extract(self, temp_test_dir: pathlib.Path):
        fml = "<|||file_start=moved.txt|||>\ncontent\n<|||file_end|||>\n"
        target = temp_test_dir / "target_c"
        self.run_fmlpack(["-x", "-C", str(target)], std_input=fml, cwd=temp_test_dir, expect_success=True)
        assert (target / "moved.txt").exists()

    def test_cli_list(self, temp_test_dir: pathlib.Path):
        fml = "<|||file_start=f1.txt|||>\n.<|||file_end|||>\n<|||dir=d1|||>"
        result = self.run_fmlpack(["-t"], std_input=fml, cwd=temp_test_dir, expect_success=True)
        assert "f1.txt" in result.stdout
        assert "d1" in result.stdout

    def test_cli_gitignore_support(self, temp_test_dir: pathlib.Path):
        project_dir = temp_test_dir / "git_project"
        project_dir.mkdir()
        (project_dir / ".gitignore").write_text("*.tmp\nignore_me/\n", encoding="utf-8")
        (project_dir / "main.py").write_text("print()", encoding="utf-8")
        (project_dir / "junk.tmp").write_text("junk", encoding="utf-8")
        (project_dir / "ignore_me").mkdir()
        (project_dir / "ignore_me" / "secret.txt").write_text("s", encoding="utf-8")

        result = self.run_fmlpack(["-c", ".", "--gitignore"], cwd=project_dir, expect_success=True)
        # Use specific tags to avoid matching .gitignore content
        assert "<|||file_start=main.py|||>" in result.stdout
        assert "<|||file_start=junk.tmp|||>" not in result.stdout
        assert "<|||file_start=ignore_me/secret.txt|||>" not in result.stdout

    def test_git_directory_implicitly_ignored(self, temp_test_dir: pathlib.Path):
        """Verify that .git/ is ignored when --gitignore is used, even without .gitignore file."""
        project_dir = temp_test_dir / "implicit_git"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        (project_dir / ".git" / "HEAD").write_text("ref: refs/heads/master", encoding="utf-8")
        (project_dir / "main.py").write_text("print()", encoding="utf-8")

        result = self.run_fmlpack(["-c", ".", "--gitignore"], cwd=project_dir, expect_success=True)
        assert "<|||file_start=main.py|||>" in result.stdout
        # Should verify that NO file starting with .git/ is included
        assert ".git/HEAD" not in result.stdout
        assert "<|||file_start=.git/HEAD|||>" not in result.stdout

    def test_path_traversal_attack(self, temp_test_dir: pathlib.Path):
        """Test that extraction prevents writing outside target directory."""
        # Malicious FML trying to write to ../evil.txt
        unsafe_fml = (
            "<|||file_start=../evil.txt|||>\n"
            "I am malicious\n"
            "<|||file_end|||>\n"
        )
        target = temp_test_dir / "safe_zone"
        target.mkdir()
        
        result = self.run_fmlpack(["-x", "-C", str(target)], std_input=unsafe_fml, cwd=temp_test_dir, expect_success=True)
        
        # Check stderr for warning
        assert "skipping unsafe path" in result.stderr.lower()
        
        # Check that file was NOT created outside
        assert not (temp_test_dir / "evil.txt").exists()
        # Check that it wasn't created inside weirdly
        assert not (target / ".." / "evil.txt").resolve().exists()

    def test_empty_directory_handling(self, temp_test_dir: pathlib.Path):
        empty_dir = temp_test_dir / "explicit_empty"
        empty_dir.mkdir()
        
        # Create archive of empty dir explicitly
        # Should behave like tar explicit_empty -> preserve folder name
        result = self.run_fmlpack(["-c", "explicit_empty"], cwd=temp_test_dir, expect_success=True)
        assert "<|||dir=explicit_empty|||>" in result.stdout
        
        # Extract it
        extract_to = temp_test_dir / "restore_empty"
        self.run_fmlpack(["-x", "-C", str(extract_to)], std_input=result.stdout, cwd=temp_test_dir, expect_success=True)
        assert (extract_to / "explicit_empty").exists()
        assert (extract_to / "explicit_empty").is_dir()

    def test_binary_file_skipping(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c", "binary_file.bin"], cwd=temp_test_dir, expect_success=True)
        assert "<|||file_start=binary_file.bin|||>" not in result.stdout

    def test_unicode_filenames(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c", "unicode_file.txt"], cwd=temp_test_dir, expect_success=True)
        assert "<|||file_start=unicode_file.txt|||>" in result.stdout
        
    def test_error_missing_input(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c"], cwd=temp_test_dir, expect_success=False)
        assert result.returncode == 1

    def test_error_multiple_modes(self, temp_test_dir: pathlib.Path):
        result = self.run_fmlpack(["-c", "-x"], cwd=temp_test_dir, expect_success=False)
        assert result.returncode == 1

if __name__ == "__main__":
    os.environ["PYTHONPATH"] = str(_project_root_dir / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")
    sys.exit(pytest.main([__file__] + sys.argv[1:]))
