# Can not tabulate row with a field that looks like a Python Bool using maxcolwidths

The following line will fail with an error about "bool' object has no attribute 'expandtabs'

    tabulate.tabulate([['init','True']], maxcolwidths=[None, 42])

This happens because the _wrap_text_to_col_widths method casts the cell to a casted cell by calling _type(cell, numpars)(cell)  which will convert the string 'True' into a bool.  Unfortunately the wrapper.wrap method called immediately after expects a str according to it's docstring and so explodes when passed a bool

My quick naïve reading suggests you could remove the entire if/else clause for casted_cell and just set casted cell equal to str(cell); if your next call only accepts a str why cast to anything else?  Still I'll leave it to those that know the code better then ignorant me to figure out the best fix.

Also completely random nitpick, but I noticed the _type method docstring lists other types it will convert, but does not include bool in it's description despite checking for and handling bools so may want to update that for consistency.
