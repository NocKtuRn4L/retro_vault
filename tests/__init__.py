# `python -m unittest discover tests` imports test modules with this folder on
# sys.path, so they import shared helpers such as qt_support by bare name. Do
# the same when a module is run as `python -m unittest tests.test_x`.
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
