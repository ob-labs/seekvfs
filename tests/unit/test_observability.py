from __future__ import annotations

import builtins

import pytest

from seekvfs.vfs import VFS
from tests.conftest import _StubBackend


@pytest.fixture
def no_logfire(monkeypatch) -> None:
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "logfire":
            raise ModuleNotFoundError("No module named 'logfire'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


@pytest.fixture
def span_exporter():
    logfire = pytest.importorskip("logfire")
    testing = pytest.importorskip("logfire.testing")

    exporter = testing.TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        inspect_arguments=False,
        additional_span_processors=[testing.SimpleSpanProcessor(exporter)],
    )
    yield exporter
    logfire.shutdown()


def test_write_emits_logfire_span(span_exporter) -> None:
    vfs = VFS(routes={"seekvfs://a/": {"backend": _StubBackend()}})
    vfs.write("seekvfs://a/p", "hello")

    names = [span["name"] for span in span_exporter.exported_spans_as_dict()]
    assert "vfs.write" in names


def test_write_read_degrade_without_logfire(no_logfire) -> None:
    vfs = VFS(routes={"seekvfs://a/": {"backend": _StubBackend()}})
    vfs.write("seekvfs://a/p", "hello")
    assert vfs.read("seekvfs://a/p").content == b"hello"
