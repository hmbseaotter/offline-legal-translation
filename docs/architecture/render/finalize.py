"""Fill a rendered report's table of contents, then save it as DOCX and PDF.

    python3 finalize.py in.docx out.docx out.pdf

The renderer (build.js) writes a table-of-contents field that Word would only
fill in on request. This opens the document in headless LibreOffice, updates
every index and field (twice, because filling the contents can move headings
to a later page), and saves the result both as .docx and as .pdf.

Needs LibreOffice with its Python bridge (`import uno`). Not part of any test
suite or package; it is a documentation build helper.
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import uno  # type: ignore[import-not-found]
from com.sun.star.beans import PropertyValue  # type: ignore[import-not-found]


def _prop(name: str, value: Any) -> Any:
    prop = PropertyValue()
    prop.Name, prop.Value = name, value
    return prop


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _connect(port: int) -> Any:
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local
    )
    url = f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
    for _ in range(120):
        try:
            return resolver.resolve(url)
        except Exception:  # the office process is still starting
            time.sleep(0.5)
    raise RuntimeError("could not connect to the LibreOffice process")


def finalize(src: Path, out_docx: Path, out_pdf: Path) -> None:
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="lo-profile-") as profile:
        office = subprocess.Popen(
            [
                "soffice",
                "--headless",
                "--invisible",
                "--nologo",
                "--norestore",
                f"-env:UserInstallation={uno.systemPathToFileUrl(profile)}",
                f"--accept=socket,host=127.0.0.1,port={port};urp;",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        desktop = None
        try:
            ctx = _connect(port)
            desktop = ctx.ServiceManager.createInstanceWithContext(
                "com.sun.star.frame.Desktop", ctx
            )
            doc = desktop.loadComponentFromURL(
                uno.systemPathToFileUrl(os.path.abspath(src)), "_blank", 0, (_prop("Hidden", True),)
            )
            for _ in range(2):
                indexes = doc.getDocumentIndexes()
                for i in range(indexes.getCount()):
                    indexes.getByIndex(i).update()
                doc.getTextFields().refresh()
                doc.refresh()
            doc.storeToURL(
                uno.systemPathToFileUrl(os.path.abspath(out_docx)),
                (_prop("FilterName", "MS Word 2007 XML"),),
            )
            doc.storeToURL(
                uno.systemPathToFileUrl(os.path.abspath(out_pdf)),
                (_prop("FilterName", "writer_pdf_Export"),),
            )
            doc.close(True)
        finally:
            if desktop is not None:
                with contextlib.suppress(Exception):  # the bridge drops as the office exits
                    desktop.terminate()
            try:
                office.wait(timeout=30)
            except subprocess.TimeoutExpired:
                office.kill()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: finalize.py in.docx out.docx out.pdf")
    finalize(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
