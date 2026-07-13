import re

from tomd.version import __version__


def test_version_e_uma_string_numerica():
    assert re.fullmatch(r"\d+(\.\d+)+", __version__)
