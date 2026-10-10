# Parser rejects out-of-order array of tables

The tomlkit parser rejects the following document:
```
[[fruit]]  # the issue disappears if [fruit] is a table instead of a table array
apple.color = "red"

[potato]  # the issue disappears if this line is removed

[fruit.apple.texture]
smooth = true
```
and raises:
```
tomlkit.exceptions.ParseError: Key "fruit" already exists. at line 7 col 0
```

It seems clear to me that the document is valid TOML 1.0.0. In any case the presence of the `[potato]` table should not make a difference wrt its validity.

This issue applies to the latest commit 6512eaa3937a6eb2136face6a6704a52aa33e6e3 on master as well as the latest release v0.11.6.

I'm experimenting with a TOML fuzzer which revealed this issue. I guess most normal applications are not likely to hit this case, so I understand if this gets low priority. It still seems worthwhile to fix it though.
