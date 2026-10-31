"""Wardlight API. Arrow is told to use the system allocator before pyarrow loads, so memory it frees after reading
the core table goes back to the operating system (deploy/run.sh sets the same)."""

import os

os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")
