"""Build the run ZIP in memory, byte-for-byte identically for identical input.

The archive holds exactly the files :func:`taskfactory.web.generate.generate`
returns in ``artifacts``. Entries are written in sorted path order with a fixed
timestamp (1980-01-01) and fixed Unix permissions, so two builds of the same
artifacts produce the same bytes. Nothing is written to disk.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping

__all__ = ["build_zip"]

# The earliest timestamp a ZIP can hold, used for every entry so no clock value
# reaches the archive.
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_FILE_MODE = 0o644 << 16
_UNIX_CREATE_SYSTEM = 3


def build_zip(artifacts: Mapping[str, bytes]) -> bytes:
    """Return the ZIP bytes of ``artifacts`` as ``{relative_path: bytes}``.

    Paths are sorted, compression is ZIP_DEFLATED, and every entry has the same
    timestamp and permissions, so the result depends only on the input.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(artifacts):
            info = zipfile.ZipInfo(filename=path, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = _UNIX_CREATE_SYSTEM
            info.external_attr = _FILE_MODE
            archive.writestr(info, artifacts[path])
    return buffer.getvalue()
