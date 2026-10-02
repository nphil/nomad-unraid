"""python3 run_tolerant.py SCRIPT.py ARGS...   : runs exp3/exp5 with the tolerant embed_many patched in."""
import runpy, sys
import tolerant  # noqa: F401
script = sys.argv[1]; sys.argv = sys.argv[1:]
runpy.run_path(script, run_name="__main__")
