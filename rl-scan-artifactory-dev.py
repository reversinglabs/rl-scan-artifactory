# python3 ts=4space
# TODO: code-review
# artifactory_to_spectra_assure.py and main.py have identical contents

import logging
import sys

from rl_scan_artifactory.main import main

if 0:
    file_handler = logging.FileHandler(filename="rl-scan-artifactory-dev.log")
    stdout_handler = logging.StreamHandler(stream=sys.stdout)
    handlers = [file_handler, stdout_handler]

    logging.basicConfig(
        level=logging.WARNING,
        format="[%(asctime)s] {%(filename)s:%(lineno)d} %(levelname)s - %(message)s",
        handlers=handlers,
    )

logger = logging.getLogger()

main()
