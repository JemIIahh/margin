# [BUG] - `sqlparse.split()` fails to split statements in v0.5.4 (regression from v0.5.3)


### Environment
- **sqlparse version:** 0.5.4
- **Python version:** 3.9

### Description
After upgrading from `sqlparse==0.5.3` to `sqlparse==0.5.4`, the `sqlparse.split()` function no longer correctly splits a multi-statement SQL string into individual statements. This breaks our data pipeline which relies on splitting complex transaction blocks into individual statements.

### Expected Behavior
When calling `sqlparse.split()` on a formatted SQL string containing multiple statements (DELETE, INSERT, etc.) wrapped in a transaction block, the function should split them into individual executable statements.

**This works correctly in v0.5.3.**

### Actual Behavior
In v0.5.4, `sqlparse.split()` fails to split the statements properly, returning the entire block as a single statement or splitting incorrectly.

### Code to Reproduce

```python
import sqlparse

# Issue occurs specifically with BEGIN/END TRANSACTION blocks
sql = """BEGIN TRANSACTION; 
DELETE FROM "schema"."table_a" USING "table_a_temp" WHERE "schema"."table_a"."id" = "table_a_temp"."id"; 
INSERT INTO "schema"."table_a" SELECT * FROM "table_a_temp"; 
END TRANSACTION;"""

formatted = sqlparse.format(sql, strip_comments=True, reindent_aligned=True)
statements = sqlparse.split(formatted)

print(f"Statements found: {len(statements)}")
print(f"Expected: 4 (BEGIN, DELETE, INSERT, END)")

for idx, stmt in enumerate(statements, 1):
    print(f"Statement {idx}: {stmt[:60]}...")
```

### Expected Output (v0.5.3)
Should split into multiple individual statements (DELETE, INSERT, etc.), allowing each to be executed separately.

### Actual Output (v0.5.4)
Returns fewer statements than expected or fails to split properly.

### Workaround
Pinning to `sqlparse==0.5.3` resolves the issue.

```txt
sqlparse==0.5.3
```

### Impact
This regression breaks production data pipelines that rely on statement splitting for transaction management and execution.

### Additional Context
The SQL is auto-generated as part of a data pipeline operation that performs DELETE/INSERT operations on dimension tables. 

**Key finding:** The issue occurs **specifically when SQL is wrapped with `BEGIN TRANSACTION` and `END TRANSACTION`**. Without these transaction keywords, `sqlparse.split()` works correctly in v0.5.4.

This worked reliably in v0.5.3 but broke in v0.5.4.

### Request
Could you please investigate what changed in v0.5.4 that would affect statement splitting behavior? This appears to be a regression that impacts production workloads.
