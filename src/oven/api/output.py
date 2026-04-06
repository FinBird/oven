"""Output abstractions for decompilation results."""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol, TextIO, runtime_checkable


@runtime_checkable
class OutputHandler(Protocol):
    """Protocol for handling decompilation output."""

    def write(self, text: str) -> None:
        """Write text to output."""
        ...

    def close(self) -> None:
        """Close output resource."""
        ...


class StringOutputHandler:
    """Output handler that collects output in a string."""

    def __init__(self) -> None:
        self._buffer: list[str] = []
        self._closed: bool = False

    def write(self, text: str) -> None:
        if self._closed:
            return
        self._buffer.append(text)

    def close(self) -> None:
        self._closed = True

    def get_value(self) -> str:
        """Get collected string."""
        return "".join(self._buffer)


class StreamOutputHandler:
    """Output handler that writes to a text stream."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, text: str) -> None:
        self._stream.write(text)

    def close(self) -> None:
        # Don't close the stream, caller owns it
        pass


class FileOutputHandler:
    """Output handler that writes to a file."""

    def __init__(
        self, path: Path | str, encoding: str = "utf-8", newline: str = "\n"
    ) -> None:
        self._path = Path(path)
        self._encoding = encoding
        self._newline = newline
        self._file: TextIO | None = None

    def write(self, text: str) -> None:
        if self._file is None:
            # Ensure parent directory exists
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(
                self._path, "w", encoding=self._encoding, newline=self._newline
            )
        self._file.write(text)

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def __enter__(self) -> FileOutputHandler:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()


class MultiFileOutputHandler:
    """Output handler that manages multiple files in a directory."""

    def __init__(
        self, output_dir: Path | str, encoding: str = "utf-8", newline: str = "\n"
    ) -> None:
        self._output_dir = Path(output_dir)
        self._encoding = encoding
        self._newline = newline
        self._current_handler: FileOutputHandler | None = None
        self._created_files: list[Path] = []

    def create_file(self, relative_path: Path | str) -> FileOutputHandler:
        """Create a new file output handler for a relative path."""
        if self._current_handler is not None:
            self._current_handler.close()

        full_path = self._output_dir / relative_path
        self._current_handler = FileOutputHandler(
            full_path, encoding=self._encoding, newline=self._newline
        )
        self._created_files.append(full_path)
        return self._current_handler

    def write(self, text: str) -> None:
        """Write to current file (if any)."""
        if self._current_handler is not None:
            self._current_handler.write(text)

    def close(self) -> None:
        """Close all open files."""
        if self._current_handler is not None:
            self._current_handler.close()
            self._current_handler = None

    def get_created_files(self) -> list[Path]:
        """Get list of created files."""
        return self._created_files.copy()
