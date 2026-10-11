# 3.11 doesn't accept tag properties containing html strings anymore

Hello,

I just got some very weird behaviors in a mkdocs project using `markdown` 3.11: it seems the new version doesn't parse/render correctly tag properties containing html code anymore.

I could confirm the following happens when the md is converted to html in [`Markdown.convert`](https://github.com/Python-Markdown/markdown/blob/master/markdown/core.py#L315). Here is a minimal POC :

Markdown content: 

```markdown
<span data-tip-txt="<kbd>Ctrl</kbd>">Anything</span>
```

Result:

<img width="292" height="46" alt="Image" src="https://github.com/user-attachments/assets/2957399e-8cdc-4103-823c-148829c96383" />

Related html:

```html
<p>&lt;span data-tip-txt="<kbd>Ctrl</kbd>"&gt;Anything</p>
```

Expected html:

```html
<p><span data-tip-txt="<kbd>Ctrl</kbd>">Anything</span></p>
```

---

Some observations:
* This doesn't happen with previous versions of `markdown` (I tested 3.9 and 3.10 successfully).
* This happens with the default configuration of mkdocs (no theme, no plugins, no md extensions at all)

Regards,
Fred
