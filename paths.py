"""Where the source workbooks live.

Order of preference:
  1. the folder named in the environment variable SHOULD_COST_INPUTS
  2. an 'inputs' folder inside this project (the layout used in the repository)
  3. the folder above this project (the original desktop layout)
The app itself needs none of them: it runs from data/Rate_Master.xlsx alone.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_local = os.path.join(HERE, "inputs")
INPUT_DIR = os.environ.get("SHOULD_COST_INPUTS") or (_local if os.path.isdir(_local) else os.path.dirname(HERE))


def find(name):
    """Full path of an input file, looking in INPUT_DIR and then the folder above the project."""
    for folder in (INPUT_DIR, os.path.dirname(HERE)):
        p = os.path.join(folder, name)
        if os.path.exists(p):
            return p
    return os.path.join(INPUT_DIR, name)
