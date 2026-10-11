# Comments between fmt:on/off are reformatted

This code:
```python
# fmt: off
 #nospace
 #  twospaces
# fmt: on
```
is changed to:
```python
# fmt: off
# nospace
#  twospaces
# fmt: on
```
I expected the lines betwen `# fmt: off` and `# fmt: on` to remain unchanged.

* Version: master (19.10b1.dev22+gbe49ac7)
* OS: Ubuntu Linux
* Python: 3.6.9

[Playground (master)](https://black.now.sh/?version=master&state=_Td6WFoAAATm1rRGAgAhARYAAAB0L-Wj4ABvAFBdAD2IimZxl1N_Wg0-Ef3tYndKG4aPypUA1Ayrzf5zNZvLSGAENc30wvA2bEeMylIvqRdhWLTqYmXqf_IjzG5SN6r67wWKI0-xLCZn7fylTZeAABDeQELeGAvAAAFscLzgy7kftvN9AQAAAAAEWVo=)
