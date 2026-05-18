# Hermes repo tools vs machine dependencies

This repo separates first-class Hermes tools from executables that must be installed on the host machine.

## First-class Hermes tools

Hermes tools are Python-registered tool schemas exposed to models through `tools/registry.py` and grouped in `toolsets.py`.

TinyFish is a first-class Hermes toolset:

- `tinyfish_fetch`
- `tinyfish_search`
- `tinyfish_agent_run`
- `tinyfish_agent_queue`
- `tinyfish_run_status`

These tools live in `tools/tinyfish_browser.py`, register under the `tinyfish` toolset, and are also included in the `browser` and Hermes core platform tool bundles. They are runtime-gated by `TINYFISH_API_KEY` and the `tinyfish` Python SDK.

Secrets must not be hardcoded. TinyFish reads only `TINYFISH_API_KEY` from the process environment/Hermes env loading path.

## Machine dependencies for Atlas/private repo work

The `atlas` toolset is a dependency checklist, not an LLM tool bundle. It documents host commands useful or expected for repo work:

- `git`
- `eza` or `exa`
- `rg`
- `fd` or `fdfind`
- `jq`
- `gh`

These commands are machine dependencies checked by `hermes doctor`; they are not Python tool schemas and are not exposed as model-callable functions.

## Doctor/setup reporting

`hermes doctor` reports:

- Atlas repo dependency install status using `PATH` probes.
- TinyFish SDK availability.
- TinyFish configuration status without printing the API key.

`hermes tools` / `hermes setup tools` lists both `tinyfish` and `atlas` so the distinction is visible during setup: TinyFish configures a real Hermes API-backed toolset; Atlas describes private repo host dependencies.
