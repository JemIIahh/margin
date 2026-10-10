# Date/time types are missing the `fold` argument, breaking compatibility with stdlib

When running the test suite on PyPy3.12, I'm getting the following test failure:

```pytb
$ poetry run pytest
========================================================= test session starts =========================================================
platform linux -- Python 3.12.14[pypy-8.0.0-final], pytest-7.4.4, pluggy-1.2.0
rootdir: /tmp/tomlkit
plugins: cov-4.1.0, anyio-4.15.1
collected 1058 items                                                                                                                   

tests/test_api.py ............................................................................................................. [ 10%] 
................................................                                                                                [ 14%] 
tests/test_build.py ....                                                                                                        [ 15%] 
tests/test_items.py ...s...............................................F........................................                [ 23%] 
tests/test_parser.py ...................................                                                                        [ 27%] 
tests/test_toml_document.py .......................................................................                             [ 33%] 
tests/test_toml_file.py ........                                                                                                [ 34%] 
tests/test_toml_tests.py ...................................................................................................... [ 44%] 
............................................................................................................................... [ 56%] 
............................................................................................................................... [ 68%] 
............................................................................................................................... [ 80%] 
............................................................................................................................... [ 92%] 
......................................................................                                                          [ 98%] 
tests/test_utils.py .......                                                                                                     [ 99%] 
tests/test_write.py ....                                                                                                        [100%] 

============================================================== FAILURES ===============================================================
____________________________________________________ test_times_behave_like_times _____________________________________________________

    def test_times_behave_like_times() -> None:
        i = item(time(12, 34, 56))

        assert i == time(12, 34, 56)
        assert i.as_string() == "12:34:56"

>       i = i.replace(hour=13)

tests/test_items.py:800:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tomlkit/items.py:1312: in replace
    return self._new(super().replace(*args, **kwargs))  # type: ignore[arg-type]
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = tomlkit.items.Time(12, 34, 56), hour = 13, minute = 34, second = 56, microsecond = 0, tzinfo = None

    def replace(self, hour=None, minute=None, second=None, microsecond=None,
                tzinfo=True, *, fold=None):
        """Return a new time with new values for the specified fields."""
        if hour is None:
            hour = self.hour
        if minute is None:
            minute = self.minute
        if second is None:
            second = self.second
        if microsecond is None:
            microsecond = self.microsecond
        if tzinfo is True:
            tzinfo = self.tzinfo
        if fold is None:
            fold = self._fold
>       return type(self)(hour, minute, second, microsecond, tzinfo, fold=fold)
E       TypeError: Time.__new__() got an unexpected keyword argument 'fold'

/usr/lib/pypy3.12/_pydatetime.py:1660: TypeError
======================================================= short test summary info =======================================================
FAILED tests/test_items.py::test_times_behave_like_times - TypeError: Time.__new__() got an unexpected keyword argument 'fold'         
============================================== 1 failed, 1056 passed, 1 skipped in 4.10s ==============================================
```

Looking at the [Python documentation](https://docs.python.org/3.12/library/datetime.html), the `dattime` types have a `fold` argument since Python 3.6. However, the types defined by `tomlkit` are missing this argument which is breaking the compatibility.

Reproduced with 8c959b51c7da2734662af759a7c9f95e9a78060a.
