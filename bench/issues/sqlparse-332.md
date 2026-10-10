# get_real_name can't get name of column where dbname is included.

Get_real_name can't get name of column where dbname is included(like db1.table1.a1), it's real_name returning table1 not a1.
```
import sqlparse
from sqlparse.sql import IdentifierList, Identifier

sql = '''
select a, db1.table1.a1    # here
as BBB
from test_table
'''
parsed = sqlparse.parse(sql)
stmt = parsed[0]  # grab the Statement object
extract_table_identifiers(stmt)

def extract_table_identifiers(token_stream):
    for item in token_stream:
        if isinstance(item, IdentifierList):
            for identifier in item.get_identifiers():
                if identifier.has_alias():
                    print(identifier.get_real_name())
                else:
                    print(identifier.get_name())
        elif isinstance(item, Identifier):
            print(item.get_real_name())
```
