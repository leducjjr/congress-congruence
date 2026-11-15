"""Texas Politics Project polls: see statepolls.py. Kept so the earlier commands still work:

    python -m congress_congruence.ingest.tpp link
    python -m congress_congruence.ingest.tpp load
"""

import sys

from .statepolls import *  # noqa: F401,F403
from .statepolls import main


if __name__ == "__main__":
    sys.exit(main(sys.argv, default="tpp"))
