"""Local PubPartner connector. An MCP client launches this module over stdio.

Run from the repository with the standalone PubPartner dependencies and
mcp>=1.29,<2 installed. Configure the client to launch this interpreter with
arguments -m pubpartner.connector and the absolute path to the chosen cartridge.
Selecting the cartridge locally limits which character the client can request.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .cartridge import Cartridge, load_cartridge
from .prompt_assembler import assemble_prompt


def serve(cartridge: Cartridge) -> None:
    server = FastMCP(
        "PubPartner",
        instructions=(
            "When the user activates this cartridge, call pp_brief for character "
            "and relevant memory before replying. The user can set it aside at any time."
        ),
    )

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    async def pp_brief(query: str = "") -> str:
        """Get the selected character's voice, tendencies and relevant memories."""
        return assemble_prompt(cartridge, query=query).text

    server.run(transport="stdio")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cartridge", type=Path)
    source = parser.parse_args().cartridge
    if source.is_file() and source.suffix == ".zip":
        # Own the extracted copy for the lifetime of this client connection.
        with TemporaryDirectory(prefix="pubpartner_connector_") as temp:
            with ZipFile(source) as archive:
                archive.extractall(temp)
            entries = list(Path(temp).iterdir())
            root = entries[0] if len(entries) == 1 and entries[0].is_dir() else Path(temp)
            with load_cartridge(root) as cartridge:
                serve(cartridge)
    else:
        with load_cartridge(source) as cartridge:
            serve(cartridge)


if __name__ == "__main__":
    main()
