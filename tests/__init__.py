"""AHSTATS test suite.

Run tests with: python -m tests
"""
import unittest
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def run_tests():
    """Run all tests in the tests directory."""
    loader = unittest.TestLoader()
    suite = loader.discover('tests', pattern='test_*.py')
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_tests())
