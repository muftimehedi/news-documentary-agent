"""Checkpointer (short-term job/thread state) + store (long-term memory), kept separate."""
from __future__ import annotations

from contextlib import contextmanager


@contextmanager
def checkpoint_cm(db_path: str):
    """Durable sqlite checkpointer (verified: langgraph-checkpoint-sqlite SqliteSaver,
    context-manager API). Yields a valid saver; falls back to in-memory.

    Never swallows caller exceptions: backend selection happens BEFORE yield,
    so a throw() into the yield propagates instead of masking the real error
    (previously caused 'generator didn't stop after throw()')."""
    saver_cm = None
    for module in ("langgraph.checkpoint.sqlite", "langgraph_checkpoint_sqlite"):
        try:
            mod = __import__(module, fromlist=["SqliteSaver"])
            saver_cm = mod.SqliteSaver.from_conn_string(db_path)
            break
        except Exception:
            continue
    if saver_cm is None:
        from langgraph.checkpoint.memory import MemorySaver

        yield MemorySaver()
    else:
        with saver_cm as saver:
            yield saver


def get_checkpointer(db_path: str):
    """Back-compat: prefer an in-memory saver for direct compile() calls.
    Durable runs should use checkpoint_cm() (sqlite file)."""
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()
