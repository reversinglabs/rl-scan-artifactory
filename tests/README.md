# Reading the test suite

Short version for someone who hasn't used pytest before. Nothing here is
pytest-in-general, just the four things this suite actually uses.

## Running it

```sh
make unit-test          # fresh venv, installs pytest, runs everything
python3 -m pytest       # if your venv is already active
python3 -m pytest tests/test_name_mangler_common.py       # one file
python3 -m pytest -k split_release                        # one topic
python3 -m pytest -x                                      # stop at the first failure
python3 -m pytest -vv                                     # show every test name
```

## Reading the output

```
157 passed, 19 xfailed
```

| Symbol | Means | Do you care? |
|---|---|---|
| `.` / `passed` | the test passed | no |
| `x` / `xfailed` | a **known bug**, expected to fail, and it did | no — it's on the list |
| `X` / `XPASS` | a known bug that now passes → **you fixed something** | yes, see below |
| `F` / `FAILED` | a regression, or an expectation that needs updating | yes |
| `E` / `ERROR` | the test couldn't even start (bad wiring) | yes |

`xfail_strict = true` in `pyproject.toml` turns an `XPASS` into a `FAILED`. That
is deliberate: it is how the suite tells you a bug is fixed.

## The three pieces of pytest syntax used here

**1. A test is a function whose name starts with `test_`.** It passes if it
doesn't raise. `assert` is the whole API.

```python
def test_strip_tail() -> None:
    assert NameManglerCommon._strip_tail("foo.rpm", ".rpm") == "foo"
```

**2. `@pytest.mark.parametrize` runs the same body once per row.** The names in
the first argument must match the function's parameters exactly.

```python
@pytest.mark.parametrize(
    ("raw", "expected"),        # <- these two names ...
    [
        ("-abc", "abc"),
        ("abc-", "abc"),
    ],
)
def test_strip(raw: str, expected: str) -> None:   # <- ... must be these two parameters
    assert strip(raw) == expected
```

If you remove the decorator but leave the parameters, pytest reports
`fixture 'raw' not found` — it has no idea where to get a value from. Remove
both or neither.

**3. `@pytest.mark.xfail(reason=..., strict=True)` marks a known bug.** The test
describes the behaviour you *want*; the mark says the code doesn't do it yet.

```python
@pytest.mark.xfail(reason="BUG ...", strict=True)
def test_the_thing_works() -> None:
    assert thing() == "right answer"
```

## When you fix a bug

Delete the `@pytest.mark.xfail(...)` decorator. Keep the function. That's it.

```diff
-@pytest.mark.xfail(
-    reason="BUG _strip_tail lowercases str1 but not str2",
-    strict=True,
-)
 def test_strip_tail_is_case_insensitive_on_both_sides() -> None:
     assert NameManglerCommon._strip_tail("foo.rpm", ".RPM") == "foo"
```

Some bugs also have a companion test named `..._currently_...` that pins the
*wrong* answer so the damage shows up in a diff. **Delete that one entirely**
when you fix the bug — it exists only to document the broken state.

Do not comment the test body out. A commented-out test is indistinguishable from
a deleted one, and you lose the coverage you just earned by fixing the code.

## When a test fails and you think the test is wrong

That happens, and it's a legitimate outcome — the test encodes a reading of the
intent, which can be wrong, or the intent may have changed. Edit the expectation
and say so in the docstring, e.g.
`test_split_release_no_longer_strips_leading_zeros`. What you don't want is to
delete the test, because then the next change in that area has nothing to push
against.

## Where things are

| File | Covers |
|---|---|
| `conftest.py` | `make_repo` / `make_file` / `make_simple` factories, no tests |
| `test_helpers.py` | `set_proxy` |
| `test_name_mangler_common.py` | the string surgery: strip, split, combine |
| `test_name_mangler_types.py` | the purl table, one row per package type |
| `test_simple_data.py` | properties → name/version/arch/release |
| `test_file_properties.py` | which files are candidates; maven and docker derivation |
| `test_generic_meta.py` | the `.rl_meta` side-car |
| `test_docker_manifest_extract.py` | manifest.json parsing |
| `test_artifactory_api_pure.py` | sha256 verification, target paths |

Nothing touches the network. `FakeArtifactoryApi` in `test_file_properties.py`
serves canned properties.
