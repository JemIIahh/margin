# Escaping pipe (`|`) characters when `tablefmt="pipe"`

Thanks for the epic libary!

I have an edge-case that produces invalid markdown tables. Let's say I have a CSV file like this.

```csv
col1,col2|withpipe,col3
y,y|n|unknown,y
```

when I would read it (with `pd.read_csv()`) and then convert it to markdown with `.to_markdown(tablefmt='pipe')`, it would return:

```md
|    | col1   | col2|withpipe   | col3   |
|---:|:-------|:----------------|:-------|
|  0 | y      | y|n|unknown     | y      |
```

Which is of course not a valid table because the rows don't have equal numbers of columns, and there are too many columns.

Of course, this could be fixed at the source. But I maintain [mkdocs-table-reader-plugin](https://github.com/timvink/mkdocs-table-reader-plugin) which depends on `tabulate`, and I would prefer for users that it 'just works', or at least gives an informative error.

A work around is to escape all pipe characters before conversion (`|` -> `\|`):

```python
df = pd.read_csv(...)
df.columns = [x.replace('|','\\|') for x in df.columns]
df = df.applymap(lambda s: s.replace('|','\\|') if isinstance(s, str) else s)
df.to_markdown(tablefmt="pipe")
```

There is however a slight performance hit for larger tables of course.

Is this something you would like to address in `tabulate`?
