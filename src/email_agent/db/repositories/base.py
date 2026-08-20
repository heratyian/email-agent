from collections.abc import Callable
from contextlib import AbstractContextManager
from sqlite3 import Connection

ConnectionContext = Callable[[], AbstractContextManager[Connection]]
