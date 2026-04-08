# html2html

## HTML format repair script

This repo now includes `fix_html_format.py`, a production-oriented Python utility that repairs common PDF-to-HTML conversion defects.

### Problems it fixes

- Misclassified headings that should be numbered paragraphs (for example around paragraph 3 in `23702376.html`).
- Multiple numbered paragraphs merged into one `<p>` block (as seen in `23724922.html`).
- Number marker and paragraph body split across elements or page boundaries (common in `Untitled-2.html`).
- Literal escaped newlines (`\n`) left in output HTML text.

### Usage

```bash
python3 fix_html_format.py 23702376.html --in-place
python3 fix_html_format.py 23702376.html 23724922.html Untitled-2.html --output-dir fixed_html
```

### Output

The script prints a per-file change summary with counts for each applied normalization rule.
