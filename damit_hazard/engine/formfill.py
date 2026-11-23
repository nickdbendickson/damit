"""Fill {{field}} placeholders from a dam record. Unknown fields stay as written.

There is no built-in state form and no form number. The template is the engineer's file.
"""

import re

_FIELD = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")


def fill(template, fields):
    """Return (text, missing keys). A missing key is left as {{key}}."""
    fields = fields or {}
    missing = []

    def repl(match):
        key = match.group(1)
        if key in fields and fields[key] is not None:
            return str(fields[key])
        missing.append(key)
        return match.group(0)

    return _FIELD.sub(repl, template or ""), missing
