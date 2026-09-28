"""One lock per session, held by one process, for one turn.

Two Agent Bridge turns must never write into the same session at the same time,
because they would both believe they had the next message number. The way that
is prevented is deliberately the oldest and dullest one available: an advisory
lock taken out on a file, held open by the running process. Each platform
supplies that primitive in its own dialect - `fcntl.flock` on an open
descriptor on POSIX, `msvcrt.locking` over one byte of the same file on
Windows - and nothing about the contract differs between them.

What makes it safe is what it does *not* do. It records nothing. There is no
lease to renew, no heartbeat to miss, no timestamp to compare, no owner name to
trust, and no rule for deciding that somebody else's lock has gone stale and may
be taken away. The operating system holds the lock as long as the descriptor is
open, and drops it the moment that process ends - normally, by crash, or by
being killed outright. A dead holder therefore blocks nobody, and no code of
ours has to notice that it died.

`.lock` is a pathname to lock, not a place to keep state. Nothing is ever
written into it, nothing is ever read out of it, and deleting it destroys no
part of the session record.

Contention is not an error to work around. It means another turn is busy, so the
answer is `BUSY_SESSION`, immediately, having changed nothing.

SPDX-License-Identifier: CC0-1.0
"""

from __future__ import annotations

import contextlib
import os
from typing import Iterator

from .errors import BridgeError, Failure

try:  # POSIX: the advisory lock is an flock on an open descriptor.
    import fcntl
except ImportError:  # Windows: msvcrt.locking is the twin there.
    fcntl = None

try:  # Windows: a byte-range lock on the same open descriptor.
    import msvcrt
except ImportError:  # POSIX: fcntl is the twin there.
    msvcrt = None

#: The file inside a session directory that is used purely as a lock target.
LOCK_FILENAME = ".lock"

#: How many bytes of the lock file the Windows twin locks. The file is never
#: written or read, so one byte at the start is the whole of it.
LOCKED_BYTES = 1


def lock_path(session_dir: str) -> str:
    """Where this session's lock is taken out."""
    return os.path.join(session_dir, LOCK_FILENAME)


def _acquire(handle: int) -> None:
    """Take this session's exclusive lock without waiting, or raise OSError.

    The two dialects say the same thing. `flock` takes one exclusive advisory
    lock on the open descriptor; `msvcrt.locking` with `LK_NBLCK` takes the
    operating system's own lock over one byte of the file, starting at the
    position the descriptor is seeked to, which is why it is seeked to the
    start first so the one byte is always the same byte. Both are held by the
    open descriptor, both are dropped by the operating system the moment it
    closes or the holding process ends, and both refuse rather than wait,
    which is what makes `BUSY_SESSION` immediate.
    """
    if msvcrt is not None:
        os.lseek(handle, 0, os.SEEK_SET)
        msvcrt.locking(handle, msvcrt.LK_NBLCK, LOCKED_BYTES)
    else:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release(handle: int) -> None:
    """Give the lock back before the descriptor closes.

    On Windows the byte range is unlocked explicitly, at the same position and
    over the same byte the lock was taken on. On POSIX closing the descriptor
    has been the release for the whole life of this lock and stays exactly
    that, so there is nothing for this function to do there.
    """
    if msvcrt is None:
        return
    os.lseek(handle, 0, os.SEEK_SET)
    msvcrt.locking(handle, msvcrt.LK_UNLCK, LOCKED_BYTES)


@contextlib.contextmanager
def session_lock(session_dir: str) -> Iterator[str]:
    """Hold this session's lock for the duration of the block.

    Raises `BUSY_SESSION` at once if another process already holds it - no
    waiting, no retry, and nothing in the session touched. Raises
    `SESSION_NOT_FOUND` when there is no such directory to lock.

    The lock is released by unlocking where the platform unlocks and then
    closing the descriptor on the way out, which happens whether the block
    finished, raised, or was interrupted.
    """
    if not os.path.isdir(session_dir):
        raise BridgeError(Failure.SESSION_NOT_FOUND, detail=session_dir)
    path = lock_path(session_dir)
    try:
        handle = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise BridgeError(Failure.SESSION_INVALID, detail=str(exc))
    try:
        try:
            _acquire(handle)
        except OSError:
            raise BridgeError(Failure.BUSY_SESSION, detail=session_dir)
        yield path
    finally:
        try:
            _release(handle)
        except OSError:
            # Closing the descriptor below releases the lock on both
            # platforms, so a failed explicit unlock cannot strand a holder.
            pass
        os.close(handle)
