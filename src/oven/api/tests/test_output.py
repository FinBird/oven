"""Tests for output abstractions."""

from __future__ import annotations

import tempfile
from pathlib import Path
import io

import pytest

from oven.api.output import (
    StringOutputHandler,
    StreamOutputHandler,
    FileOutputHandler,
    MultiFileOutputHandler,
)


def test_string_output_handler() -> None:
    """Test StringOutputHandler."""
    handler = StringOutputHandler()
    handler.write("Hello, ")
    handler.write("World!")
    handler.close()

    assert handler.get_value() == "Hello, World!"

    # Can write after close (no-op or safe)
    handler.write(" Ignored")
    # get_value still returns previous content
    assert handler.get_value() == "Hello, World!"


def test_stream_output_handler() -> None:
    """Test StreamOutputHandler."""
    stream = io.StringIO()
    handler = StreamOutputHandler(stream)

    handler.write("Line 1\n")
    handler.write("Line 2")
    handler.close()

    assert stream.getvalue() == "Line 1\nLine 2"
    # Stream should not be closed
    assert not stream.closed


def test_file_output_handler() -> None:
    """Test FileOutputHandler."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "output.txt"
        handler = FileOutputHandler(file_path, encoding="utf-8")

        handler.write("Test content\n")
        handler.write("More content")
        handler.close()

        assert file_path.exists()
        assert file_path.read_text(encoding="utf-8") == "Test content\nMore content"


def test_file_output_handler_context_manager() -> None:
    """Test FileOutputHandler as context manager."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "output.txt"

        with FileOutputHandler(file_path) as handler:
            handler.write("Inside context")

        assert file_path.exists()
        assert file_path.read_text() == "Inside context"


def test_multi_file_output_handler() -> None:
    """Test MultiFileOutputHandler."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "output"
        handler = MultiFileOutputHandler(output_dir)

        # Create first file
        file1 = handler.create_file("file1.txt")
        file1.write("Content 1\n")

        # Write directly through handler (to current file)
        handler.write("More for file1\n")

        # Create second file
        file2 = handler.create_file("subdir/file2.txt")
        file2.write("Content 2")

        # Write to second file
        handler.write(" more")

        handler.close()

        # Check files were created
        files = handler.get_created_files()
        assert len(files) == 2
        assert files[0] == output_dir / "file1.txt"
        assert files[1] == output_dir / "subdir/file2.txt"

        # Check contents
        assert files[0].read_text() == "Content 1\nMore for file1\n"
        assert files[1].read_text() == "Content 2 more"

        # Check directory structure
        assert files[1].parent.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
