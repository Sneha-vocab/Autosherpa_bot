"""
Simple script to run the test matrix.
Usage: python run_tests.py
"""

import asyncio
import sys
from test_matrix import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠ Test execution interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error running tests: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


