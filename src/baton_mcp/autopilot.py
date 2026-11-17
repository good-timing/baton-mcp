"""``start_autopilot``: the steps for running a Baton Autopilot experiment.

baton-mcp runs remotely and cannot start ``baton-eval`` on the developer's
machine, so the tool returns steps for the calling agent to follow there.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from baton_mcp.config import SERVER_RE, api_base_url

BATON_EVAL = "baton-eval@0.1.0"

STEPS = """\
Follow these steps on the developer's machine. Ask before each command that \
changes files or spends money.

1. Check the server is ready for Autopilot:
   - It reads its DSN from the BATON_DSN environment variable. A DSN written \
in the code wins over the variable and sends test traffic to production.
   - It installs Baton with settings="console".
   - Its Baton SDK understands test changes: Python 1.3.0 or later, \
TypeScript 1.2.0 or later.
   If any of these fails, show the developer what to change and stop.

2. Tasks. If baton-eval.toml exists and its server is "{vendor_id}", skip to \
step 4. If it names another server, ask the developer which one they mean. \
Otherwise draft evals/tasks.jsonl with the developer: one JSON object per line, for example
   {{"id": "<short-id>", "prompt": "<what a user would ask>", "check": \
{{"tool": "<one of the server's tools>", "args": {{"<arg>": "<value>"}}, "reply_contains": \
"<path to a value in that tool's result, e.g. rows[0].name>"}}}}
   "check" is the call baton-eval makes after the agent stops; the agent's \
reply must contain the value "reply_contains" points to. Only text with a \
letter in it is matched, so point at a name or label, not a number or date. Show the developer every task and wait for them to \
confirm.

3. Test key. The developer makes a test key for this server on its Autopilot \
tab in the Baton Console ({console}). Never ask for the key, read it, or pass \
it to a tool. Ask the developer to run init in their own terminal, with the \
key in BATON_EVAL_DSN or pasted when asked:
   npx -y {baton_eval} init --server {vendor_id} --tasks evals/tasks.jsonl \
--model <model> -- <command that starts the server>

4. Cost. Read budget_sessions (400 if unset) and [agent] max_budget_usd from \
baton-eval.toml. Tell the developer the run can use up to budget_sessions \
agent sessions at up to max_budget_usd dollars each, and wait for their yes.

5. Run, in the background, logging to a file:
   npx -y {baton_eval} run 2> baton-eval.log
   Once it starts, the log has a line "experiment <id>: N tasks, budget B \
sessions". Give the developer the \
experiment id, and tell them it is on the server's Autopilot tab in the \
Console. The run ends with a line like "experiment <id>: N steps, P pass, \
F fail, S short"; report it when it appears. Results and any fix to approve \
are on the experiment's page.
"""


def autopilot_steps(vendor_id: str) -> str:
    return STEPS.format(vendor_id=vendor_id, console=api_base_url(), baton_eval=BATON_EVAL)


def add_autopilot(mcp: FastMCP) -> None:
    @mcp.tool
    def start_autopilot(
        # Pasted into a shell command the developer runs (test_tool_refuses_anything_but_a_server_id).
        vendor_id: Annotated[str, Field(pattern=SERVER_RE.pattern)],
    ) -> str:
        """Start a Baton Autopilot experiment. Real agents run your server's tasks with and without text fixes, and the Console keeps the fixes that help.

        Call it when the developer asks Baton to improve their server. It returns the steps to follow on the developer's machine and runs nothing itself.

        vendor_id: the server's id, the last part of its DSN.
        """
        return autopilot_steps(vendor_id)
