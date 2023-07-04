"""
Application stub
"""
import sys
import os
from tempfile import TemporaryFile

from loguru import logger

from ssh import Credentials


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    else:
        application_path = os.path.dirname(__file__)
    return os.path.join(application_path, relative_path)


def remove_file(file):
    try:
        os.remove(file)
        logger.debug('File deleted: {}', file)
    except FileNotFoundError:
        logger.exception('Could not find or remove file: {}', file)
    return


def make_temp(output):
    file = TemporaryFile()
    file.write(output)
    file.seek(0)
    return file


def initialize():
    pass


def do_stuff():
    # do whatever you need to do
    response = "This is response from Python backend"
    return response


def get_credentials():
    credentials = Credentials()
    credentials.verify()
    return credentials


if __name__ == '__main__':
    pass


