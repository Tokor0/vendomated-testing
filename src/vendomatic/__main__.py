"""Makes ``python -m vendomatic`` the same program as ``vendomatic``.

Guarded, so that importing this module -- which tools that walk a package will
do -- does not run a command and exit the interpreter.
"""

from .cli import run

if __name__ == "__main__":
    run()
