#!/usr/bin/env python3
"""Map-capable entry point for the Komodobots bot lab runner."""

import logging
from run_frobodm2_lab import main



LOGGER = logging.getLogger(__name__)
if __name__ == "__main__":
    raise SystemExit(main())
