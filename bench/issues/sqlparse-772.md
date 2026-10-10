# Stipping inline comments breaks the SQL.

It should not concatenate value with keywords when stripping comments.

## Reproduction

```python
>>> sqlparse.format('SELECT 1/*bar*/ AS foo', strip_comments=True)
'SELECT 1AS foo'
```

## Expected Behavior

```python
>>> sqlparse.format('SELECT 1/*bar*/ AS foo', strip_comments=True)
'SELECT 1 AS foo'
```

## Versions
 - Python: `3.11.4`
 - sqlparse: `0.5.0`
