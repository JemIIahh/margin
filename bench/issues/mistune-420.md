# escape flag in create_markdown is ignored when using a custom renderer – must be set manually

### Problem

When using a **custom renderer** with `mistune.create_markdown`, the `escape` flag is **ignored**, even if explicitly passed:

```python
markdown = mistune.create_markdown(
    renderer=renderer,
    escape=False,  # This is ignored
    hard_wrap=False
)
```

This results in HTML still being escaped, which can be confusing if you're expecting raw HTML rendering.

### Root Cause
The create_markdown function does not propagate the escape flag to the renderer instance if you provide your own renderer. It only sets the flag if it's creating the default renderer internally.

### Solution / Workaround
To make it work, you need to pass the `escape` flag when instantiating your custom renderer, like this:
```python
class SectionRenderer(mistune.HTMLRenderer):
    def __init__(self, escape: bool = True):
        super().__init__(escape=escape)
        self._in_section = False
        # other logic...

renderer = SectionRenderer(escape=False)

markdown = mistune.create_markdown(
    renderer=renderer,
    hard_wrap=False
)
```

Now the `escape=False` will take effect as expected.

### Recommendation
Consider one of the following improvements:

- Document this behavior in the create_markdown docstring, clarifying that escape and similar flags only apply if no custom renderer is provided.
- Propagate the flag into the renderer if the renderer accepts it (perhaps conditionally via hasattr or renderer inspection).
