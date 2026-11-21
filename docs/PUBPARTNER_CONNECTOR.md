# Local PubPartner connector

A local MCP client can ask for a briefing from the cartridge its owner selected.
The client supplies the language model. The briefing includes character, voice
style, boundaries and relevant memories, so select a cartridge you intend to
share with that client. This exchange does not invoke a model or send a message.

From the repository root, use a Python environment with PubPartner's standalone
dependencies and install the optional SDK with:

    python -m pip install "mcp>=1.29,<2"

Configure a local stdio MCP client to launch:

    python -m pubpartner.connector /absolute/path/to/cartridge.zip

Set the working directory to the repository root or install the standalone
PubPartner package in the client interpreter. On Windows, use the full path
to python.exe and pass the cartridge path as one argument. Directories and
ZIP archives are accepted. The chosen cartridge is fixed for that process.

The client initializes MCP, discovers pp_brief through tools/list, then calls
pp_brief with an optional query. Its text result uses the same prompt assembler
as the portable runtime. Stop the process to disconnect. Making this tool
available in a hosted chat requires a separate authenticated remote transport.
Private invitations, unread delivery and replies require a separate host workflow.
