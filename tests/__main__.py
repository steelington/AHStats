"""Test runner entry point for python -m tests."""
from tests import run_tests
import sys

if __name__ == '__main__':
    sys.exit(run_tests())
