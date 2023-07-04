import sys
import os
from io import StringIO
from contextlib import redirect_stdout

import dotenv
import webview
from loguru import logger

from server import server

dotenv.load_dotenv()


def setup_logger():
    logger.remove()
    logger.add(sys.stderr, level=os.getenv('LOG_LEVEL', 'DEBUG'))
    logger.add('log.log', level='DEBUG', mode='w')


if __name__ == '__main__':
    """Entry point for the GUI"""
    setup_logger()

    stream = StringIO()
    with redirect_stdout(stream):
        window = webview.create_window(
            title='Provisioning Helper Utility',
            url=server,
            width=1400,
            height=950,
        )
        webview.start(private_mode=False, debug=eval(os.getenv('FLASK_DEBUG')))


