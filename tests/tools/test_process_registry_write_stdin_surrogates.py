"""Sibling regression test for #79178: background-PTY stdin must round-trip
surrogateescape content instead of crashing on the strict UTF-8 encode."""
import shlex
import time

import pytest

from tools.process_registry import ProcessRegistry


def test_write_stdin_pty_surrogateescape_roundtrip(tmp_path):
    registry = ProcessRegistry()
    out = tmp_path / "out.bin"
    script = tmp_path / "read_stdin.py"
    # readline(): a PTY never delivers EOF, so read one line (canonical mode
    # delivers it after the newline we send).
    script.write_text(
        f"import sys\nopen({str(out)!r}, 'wb').write(sys.stdin.buffer.readline())\n"
    )
    session = registry.spawn_local(
        f"python3 {shlex.quote(str(script))}",
        cwd=str(tmp_path),
        use_pty=True,
    )
    if session._pty is None:
        registry.kill_process(session.id)
        pytest.skip("ptyprocess not available; PTY path not exercised")
    try:
        result = registry.write_stdin(
            session.id, b"\xff".decode("utf-8", "surrogateescape") + "\n"
        )
        assert result["status"] == "ok", result
        # Wait for the CONTENT, not for the file to exist. The child runs
        # open(out,'wb').write(...), so the file is created EMPTY at open()
        # time and filled only once the PTY delivers the line. The previous
        # wait stopped at out.exists(), which the empty file satisfies, so
        # the read returned b'' whenever the parent won that gap. On a
        # 144-worker runner the gap is wide enough to lose deterministically
        # (this failed both attempts in CI, not just once); it also loses
        # 6 times in 25 runs on an unloaded 16-core box.
        deadline = time.monotonic() + 30
        got = b""
        while time.monotonic() < deadline:
            try:
                got = out.read_bytes()
            except FileNotFoundError:
                got = b""
            if got == b"\xff\n":
                break
            time.sleep(0.05)
        assert got == b"\xff\n"
    finally:
        registry.kill_process(session.id)
