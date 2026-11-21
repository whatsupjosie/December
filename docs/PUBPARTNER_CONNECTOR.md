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
as the portable runtime. Stop the process to disconnect.

## Set up from PubPartner or PubCast

Open Connections on the PubPartner desk, or AI connections on PubCast's
provider-key page (/byok). Choose a local model, a hosted provider or an
OpenAI-compatible endpoint. A saved account credential can be selected without
revealing its value. Keys entered through the form use Reach's encrypted
credential store. Use connection applies the choice to the current desk.
For Ollama, the local scanner lists installed models when the service responds.

For ChatGPT account consent, configure a registered, eligible OpenAI client
with PUBPARTNER_OPENAI_CLIENT_ID and PUBPARTNER_OPENAI_CALLBACK. The callback
must be the exact /pubpartner URL on the same browser origin where the user
signed in to Reach. Use HTTPS or an http://127.0.0.1 loopback URL.
Set PUBPARTNER_OPENAI_CLIENT_SECRET only for a confidential client.
The user completes account selection and consent on OpenAI. PubPartner uses
the account's eligible model list. Tokens expire in host memory and linking
must be repeated after expiry, a host restart or a new PubCast login.

## Share a cartridge with a client

In Connections, expand the cartridge-sharing control, select the intended ZIP,
then start Local MCP. Point a client on that computer to
http://127.0.0.1:8768/mcp. Other local processes can access this loopback
endpoint while it runs. Only the signed-in Reach owner can select the ZIP and
operate the launcher. Stopping the connector takes its briefing offline.

For an OpenAI workspace tunnel, install the official tunnel-client executable
on the Reach host and set CONTROL_PLANE_API_KEY and CONTROL_PLANE_TUNNEL_ID.
Alternatively, to create one in the screen, set PUBPARTNER_OPENAI_WORKSPACE_ID
and OPENAI_ADMIN_KEY alongside the runtime credential. Choose OpenAI private
tunnel and select Create tunnel and start. The host saves the resulting ID
and reuses it across restarts. If creation is interrupted, check the OpenAI
workspace's tunnel list and set CONTROL_PLANE_TUNNEL_ID before retrying.
Select the displayed tunnel in the supported OpenAI workspace's connector
settings. The process indicator reports the local launcher state. Calling
pp_brief from the remote client confirms the end-to-end connection.

Model selection controls conversations inside PubPartner. The MCP tool makes
the owner-selected cartridge available to a client that calls it. Both can
operate independently. Native app notifications and unsolicited chat delivery
require a separate host workflow.
