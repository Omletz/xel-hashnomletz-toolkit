"""Cross-platform pseudo-terminal spawn, used only for the seed-reveal flow in wallet_manager.py.

Why this exists: xelis_wallet's interactive prompt redraws its whole status line on every keystroke using
raw ANSI cursor codes. Confirmed live on Linux (2026-09-23): driving it over a PLAIN pipe
(subprocess.Popen with stdin/stdout=PIPE) garbles badly -- typed commands get interleaved with each other
because the app expects a real terminal's raw-mode byte stream, not a plain buffered pipe. `pexpect.spawn`
(backed by a real POSIX pty via ptyprocess) fixed this completely -- see the module docstring in
wallet_manager.py for the proven working flow.

`pexpect.spawn` is POSIX-only. Windows history on this project (2026-09-23):
1. First attempt used `wexpect`. CONFIRMED BROKEN on real Windows hardware: the wallet process spawned
   and stayed alive (held memory) but sat at 0% CPU indefinitely -- a true silent deadlock, not garbling.
   Diagnosis: wexpect is successfully launching the subprocess through *a* pty, but isn't driving it
   correctly (input not reaching the process, or its read loop not pumping output the way the child
   needs to keep making progress -- xelis_wallet prints continuous, high-volume progress output during
   table generation; if that output isn't drained fast enough the child can block on a full console
   buffer). wexpect is also a small, not clearly actively-maintained project with other known rough
   edges (e.g. issues around EOF handling) -- not confidence-inspiring for a security-critical path.
2. Current attempt: `pywinpty` (the `winpty` package), a real ConPTY-backed pseudo-console library used
   in production by e.g. Jupyter/terminado for exactly this "drive an interactive console app from
   Python" job -- much more battle-tested than wexpect. Its `PtyProcess.read()` is a BLOCKING call with
   unclear/version-dependent non-blocking semantics, so rather than guess at exact non-blocking-read
   flags, this wraps it in a background reader thread feeding a queue -- see _WinPty below. That sidesteps
   needing to know pywinpty's exact non-blocking contract: Queue.get(timeout=...) always behaves the same
   regardless of what the underlying read call does.

**STILL UNVERIFIED**: this box is Linux-only. The pywinpty path below is written against its documented
API (see pty_compat's own research, not hands-on testing) and has never actually been run. Test it before
trusting seed-reveal on Windows -- see README's "Not yet verified" section. If this ALSO doesn't work,
the next things to try, in order: (a) get raw diagnostics -- a minimal standalone script that spawns
xelis_wallet via winpty.PtyProcess directly (no wallet_manager.py involved) and prints every byte read
immediately, to see whether output is arriving at all; (b) check whether xelis_wallet's table-generation
phase specifically is the problem (try seed-reveal against an ALREADY-created wallet, skipping the slow
table-gen path, to isolate whether the hang is generic-to-PTY or specific-to-high-volume-output)."""
import os
import queue
import threading


class TimeoutMarker(Exception):
    pass


class EOFMarker(Exception):
    pass


class _WinPty:
    """Wraps winpty.PtyProcess to present the same surface wallet_manager.py already expects from
    pexpect: send(), read_nonblocking(size, timeout), isalive(), pid. A background thread does the
    actual (blocking) reads and feeds a queue, so read_nonblocking here never needs to know pywinpty's
    own non-blocking-read semantics -- it just does a plain Queue.get(timeout=...)."""

    def __init__(self, command, args, encoding, codec_errors):
        import winpty
        self._encoding = encoding
        self._codec_errors = codec_errors
        self.proc = winpty.PtyProcess.spawn([command] + list(args))
        self.pid = self.proc.pid
        self._q = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        try:
            while True:
                chunk = self.proc.read(4096)
                if not chunk:
                    break
                self._q.put(chunk)
        except Exception:
            pass
        finally:
            self._q.put(None)  # EOF marker

    def isalive(self) -> bool:
        try:
            return self.proc.isalive()
        except Exception:
            return False

    def send(self, s: str):
        self.proc.write(s)

    def read_nonblocking(self, size: int = 4096, timeout: float = 0.3) -> str:
        try:
            chunk = self._q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutMarker()
        if chunk is None:
            raise EOFMarker()
        if isinstance(chunk, bytes):
            return chunk.decode(self._encoding, errors=self._codec_errors)
        return chunk

    def wait(self):
        while self.isalive():
            threading.Event().wait(0.1)

    def kill(self, sig=None):
        try:
            self.proc.terminate(force=True)
        except Exception:
            pass


def spawn(command: str, args: list, timeout: float, encoding: str = "utf-8", codec_errors: str = "replace"):
    """command is the executable path, args is its argv list -- kept separate (not joined into one
    quoted string) so neither backend needs manual shell-quoting, which differs between POSIX shlex rules
    and Windows argv conventions."""
    if os.name == "nt":
        return _WinPty(command, args, encoding, codec_errors)
    else:
        import pexpect
        return pexpect.spawn(command, args=args, timeout=timeout, encoding=encoding, codec_errors=codec_errors)


def is_timeout_exception(exc: Exception) -> bool:
    if os.name == "nt":
        return isinstance(exc, TimeoutMarker)
    else:
        import pexpect
        return isinstance(exc, pexpect.TIMEOUT)


def is_eof_exception(exc: Exception) -> bool:
    if os.name == "nt":
        return isinstance(exc, EOFMarker)
    else:
        import pexpect
        return isinstance(exc, pexpect.EOF)
