# Flag value is always true when setting any envvar

Click 8.2.1 includes fixes related to boolean flags.

We’re encountering a specific issue described in [this comment](https://github.com/pallets/click/issues/2897#issuecomment-2873272069). The comment appears in the thread for a different but related issue ([#2897](https://github.com/pallets/click/issues/2897)), focused on a separate aspect of boolean flag handling. Maybe the issue was overlooked because the discussion centered on the main issue.

---
A user's comment on the issue, with the reproduction the body refers to:

I'm using the `envvar` option and I set the `envvar` to `False`, however it's always `true` for me.

```python
# hi.py
import click

@click.command()
@click.option("--dry-run/--no-dry-run", default=False, envvar="DRY_RUN")
def main(dry_run: bool):
    print(type(dry_run))
    print(f"Dry run: {dry_run}")

if __name__ == "__main__":
    main()
```

```python
export DRY_RUN=false

python hi.py
```
Output
```python
<class 'bool'>
Dry run: True
```
