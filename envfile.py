"""
Reading and writing config.env (KEY=value lines), shared by the main script
and the setup wizard so both parse the file the same way.
"""
import os


def parse(path):
    """
    Returns the KEY=value pairs of the file as an ordered dict (empty if the file
    does not exist). Blank lines and # comments are ignored; a value wrapped in a
    matching pair of quotes is unquoted.
    """
    values = {}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_into_environ(path):
    """Loads the file into os.environ; variables that are already set take precedence."""
    for key, value in parse(path).items():
        os.environ.setdefault(key, value)


def write(path, values, header=(), comments=None):
    """
    Writes values as KEY=value lines, readable by the owner only (0600).
    header: comment lines written first; comments: {KEY: comment line written above KEY}.
    """
    comments = comments or {}
    lines = [f"# {h}" for h in header]
    for key, value in values.items():
        if key in comments:
            lines.append(f"# {comments[key]}")
        lines.append(f"{key}={value}")
    old_umask = os.umask(0o077)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    finally:
        os.umask(old_umask)
    os.chmod(path, 0o600)
