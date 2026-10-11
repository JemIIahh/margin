# Unnecessary parentheses added to expression in indexed assignment

**Describe the bug**

Black unnecessarily adds parentheses around the right-hand side expression in indexed assignments when breaking lines for long index names. This results in added visual clutter and does not conform to typical Python formatting standards where no additional parentheses would be expected. In particular, PyLint raises the [superfluous-parens](https://pylint.readthedocs.io/en/latest/user_guide/messages/convention/superfluous-parens.html) warning.

**To Reproduce**

Given the following Python script:

```python
import numpy as np

def main():
    dictionary_of_arrays = {
        "long_key_name_for_the_example": np.zeros((3, 1)),
        "short": np.zeros((3, 1)),
    }
    index_zero = 0
    very_long_index_name = 1
    dictionary_of_arrays["long_key_name_for_the_example"][very_long_index_name, index_zero] = 10 - 5
```

When formatted using the online Black formatter at <https://black.vercel.app/?version=main>, the assignment line is formatted as follows:

```python
dictionary_of_arrays["long_key_name_for_the_example"][
    very_long_index_name, index_zero
] = (10 - 5)
```

**Expected behavior**

The expected code should look like this:

```python
dictionary_of_arrays["long_key_name_for_the_example"][
    very_long_index_name, index_zero
] = 10 - 5
```

**Environment**

- Black's version: main (online formatter)
- OS and Python version: N/A (used the online formatter)

**Additional context**

None.
