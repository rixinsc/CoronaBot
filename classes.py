from discord.ext import commands
from collections.abc import MutableMapping
from typing import Callable, Union
import asyncio
import aiofiles
import json


class TransformedDict(MutableMapping):
    """A pseudo-dictionary object"""

    def __init__(self, *args, **kwargs):
        self._store = dict()
        self.update(*args, **kwargs)

    def __getitem__(self, key):
        return self._store[key]

    def __setitem__(self, key, value):
        self._store[key] = value

    def __delitem__(self, key):
        del self._store[key]

    def __iter__(self):
        return iter(self._store)

    def __len__(self):
        return len(self._store)

    def __contains__(self, key):
        return self._store.__contains__(key)

    def __repr__(self):
        return '{0}({1})'.format(type(self).__name__, self._store.__repr__())

    def copy(self):
        return self.__class__(self._store)

    @classmethod
    def fromkeys(cls, keys, value=None):
        return cls(dict.fromkeys(keys, value))


class FileDatabase(TransformedDict):
    """
    A asynchronous database implementation utilising local filesystem.

    General Usage:
    value = db[key]

    Methods:
    instance - instance name
    coroutine pull - Force get latest DB from online gist
    coroutine push - Force push update to online gist
    coroutine fetch - Fetch a latest value from online DB
    coroutine aset - Set a k,v pair asynchronously
    coroutine fetchset - Fetch latest data from DB,
                         set default data if not found.
    """

    def __init__(self, *, filename):
        self.filename = filename
        self.__iter_pull = False
        super().__init__()

    def _check_circular_reference(self,
                                  obj: Union[
                                      dict, list, tuple, set, frozenset],
                                  _seen=None) -> Union[
                                      dict, list, tuple, set, frozenset]:
        if _seen is None:
            _seen = set()
        if id(obj) in _seen:
            raise ValueError("Circular reference detected.")
        _seen.add(id(obj))
        res = obj
        if isinstance(obj, dict):
            res = {
                self._check_circular_reference(k, _seen):
                self._check_circular_reference(v, _seen)
                for k, v in obj.items()}
        elif isinstance(obj, (list, tuple, set, frozenset)):
            res = type(obj)(self._check_circular_reference(v, _seen)
                            for v in obj)
        # remove id again; only *nested* references count
        _seen.remove(id(obj))
        # return checked object
        return res

    def __decode_dict_key(self, d: dict) -> dict:
        new_dict = {}
        for key, val in d.items():
            # type decode logic
            if key.startswith("(int)"):
                new_key = int(key[5:])
            elif key.startswith("(float)"):
                new_key = float(key[7:])
            elif key.startswith("\\"):
                new_key = key[1:]
            else:
                new_key = key
            # recurse if val is dict
            if type(val) is dict:
                val = self.__decode_dict_key(val)
            new_dict[new_key] = val
        return new_dict

    def __encode_dict_key(self, d: dict) -> dict:
        self._check_circular_reference(d)
        new_dict = {}
        for key, val in d.items():
            # type encode logic
            if type(key) is str and key.startswith(("(int)", "(float)", "\\")):
                new_key = '\\' + str(key)
            elif type(key) is str:
                new_key = key
            elif type(key) is int:
                new_key = '(int)' + str(key)
            elif type(key) is float:
                new_key = '(float)' + str(key)
            else:
                raise TypeError("Key must be of type str or int or float.")
            # recurse if val is dict
            if type(val) is dict:
                val = self.__encode_dict_key(val)
            new_dict[new_key] = val
        return new_dict

    async def pull(self):
        """coroutine - Pull the latest data from DB."""
        try:
            async with aiofiles.open(self.filename, 'r', encoding='utf8') as f:
                content = await f.read()
                self._store = self.__decode_dict_key(json.loads(content))
        except FileNotFoundError:
            await self.push()
        return self

    async def push(self):
        """coroutine - Push the latest data to DB."""
        async with aiofiles.open(self.filename, 'w', encoding='utf8') as f:
            content = json.dumps(self.__encode_dict_key(self._store),
                                 ensure_ascii=False, check_circular=False)
            await f.write(content)

    def copy(self):
        raise RuntimeError(
            "Copy of database isn't supported, instead create a new "
            "DB object and pass in the same credentials.")

    async def aset(self, key, value):
        """coroutine - An asynchronous method to set an item."""
        self[key] = value
        await self.push()

    _placeholder = object()

    async def fetch(self, key, default=_placeholder):
        """coroutine - Fetch data from DB, pass in parameter
        'default' to prevent KeyError."""
        await self.pull()
        try:
            return self[key]
        except KeyError as e:
            if default is self._placeholder:
                raise e
            else:
                return default

    async def fetchset(self, key, default=None):
        """coroutine - Fetch data from DB, create an entry
        with value None if not found."""
        await self.pull()
        if key not in self._store:
            await self.aset(key, default)
        return self[key]


class TimedLock():
    """
    A lock object with timeout support.

    Parameter:
    timeout - timeout until forcing lock to release, -1 for indefinite
    """

    def __init__(self, timeout: int = 15):
        self._lock = asyncio.Lock()
        self._timeout = timeout
        self._waiting = 0

    async def acquire(self) -> True:
        """
        Acquire the lock.
        Resets the lock if timeout is reached.
        """
        # no calculating timeout for timeout < 0
        if self._timeout < 0:
            return await self._lock.acquire()

        try:
            self._waiting += 1
            await asyncio.wait_for(asyncio.shield(self._lock.acquire()),
                                   self._waiting * self._timeout)
        except asyncio.TimeoutError:
            print("Maximum lock time reached ({}s), releasing..."
                  .format(self._timeout))
            self._lock.release()
        self._waiting -= 1
        return True

    def release(self) -> None:
        """Release the lock."""
        if self._lock.locked():
            self._lock.release()

    @property
    def locked(self) -> bool:
        """Return True if lock is acquired."""
        return self._lock.locked()

    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.release()


class Bot(commands.Bot):
    def __init__(self, *args, **kwargs):
        """
        New methods:
        db -> Database, bot's database
        scheduleClose(Callable) -> schedule closing of loop-aware
                                   functionalities
        """
        super(Bot, self).__init__(*args, **kwargs)
        self.db = None
        self.instance_name = "main"
        self._db_name = kwargs.get("db_name", "db")
        self._closeFunctions = []
        self._webSessions = {}

    async def start(self, *args, **kwargs):
        self.db = FileDatabase(filename=f"{self._db_name}.json")
        await super(Bot, self).start(*args, **kwargs)

    def scheduleClose(self, func: Callable):
        """
        Schedule closure of loops/sessions that need to be closed when
        shutting down.
        """
        self._closeFunctions.append(func)

    async def close(self, *args, **kwargs):
        for func in self._closeFunctions:
            if asyncio.iscoroutinefunction(func):
                await func()
            else:
                func()
        await super(Bot, self).close(*args, **kwargs)
