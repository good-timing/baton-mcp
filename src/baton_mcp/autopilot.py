"""``start_autopilot``: the steps for running a Baton Autopilot experiment.

baton-mcp runs remotely and cannot start ``baton-eval`` on the developer's
machine, so the tool returns steps for the calling agent to follow there.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from baton_mcp.config import ISSUE_RE, SERVER_RE, api_base_url

BATON_EVAL = "baton-eval@0.3.0"

STEPS = """\
Follow these steps on the developer's machine. Ask before each command that \
changes files or spends money.

1. Check the server is ready for Autopilot:
   - It reads its DSN from the BATON_DSN environment variable. A DSN written \
in the code wins over the variable and sends test traffic to production.
   - It installs Baton with settings="console".
   - Its Baton SDK understands test changes and tags each test event with \
its task: Python 1.3.2 or later, TypeScript 1.2.1 or later. A fix is tested \
only on the tasks that hit the issue, which needs the tags.
   If any of these fails, show the developer what to change and stop.

2. Tasks. If baton-eval.toml exists and its server is "{vendor_id}", use \
its task file: change any check's "reply_contains" to "answer" (same path), \
then skip to step 4. If it names another server, ask the developer which one \
they mean. Otherwise draft evals/tasks.jsonl with the developer: one JSON \
object per line, for example
   {{"id": "<short-id>", "prompt": "<what a user would ask>", "check": \
{{"tool": "<one of the server's tools>", "args": {{"<arg>": "<value>"}}, "answer": \
"<where the answer is in that tool's result, e.g. rows[0].label>"}}}}
   "check" is the call baton-eval makes after the agent stops; a judge in \
the Console grades the agent's reply against that call's result. "answer" is \
optional; if it finds nothing or a blank value, the run counts as short. A \
prompt over 4,000 characters is refused. Show the developer every task and \
wait for them to confirm.

3. Test key. The developer makes a test key for this server on its Autopilot \
tab in the Baton Console ({console}). If the Console says Autopilot isn't open \
in this workspace yet, tell the developer Autopilot is in early access and stop. \
Never ask for the key, read it, or pass it to a tool. Ask the developer to run init in their own terminal, with the \
key in BATON_EVAL_DSN or pasted when asked:
   npx -y {baton_eval} init --server {vendor_id} --tasks evals/tasks.jsonl \
--model <model> -- <command that starts the server>
   If no task had "held_out", init marks some "held_out": true and logs \
which; show the developer. They can change the pick, but any "held_out", even \
false, counts as theirs, and with none true the Console can't confirm a fix.

4. Before every run. Tell the developer what the Baton Console stores: each \
task's prompt, the agent's final reply, and the check's arguments and result, \
each cut to 20,000 characters. Read budget_sessions (400 if unset) and \
[agent] max_budget_usd from baton-eval.toml, and tell them the run can use up \
to budget_sessions agent sessions at up to max_budget_usd dollars each, \
and wait for their yes.

Every run goes in the background, its log in baton-eval.log. The log starts \
with "experiment <id>: N tasks, budget B sessions" and "page <url>"; give the \
developer both. It ends with a line starting "experiment <id>: N steps, P \
pass, F fail, S short", sometimes followed by "; stopped: <why>". If it \
stopped for the budget before anything was judged, there is no find or fix \
line: say the budget ran out and nothing was decided. If a run fails, it \
exits with code 1 and the log has a line "baton-eval: <message>"; show the \
developer that message and its hint. If the message says reading the result \
failed, call get_experiment with the experiment id and server "{vendor_id}" \
instead of running again: the runs are done and paid for.

5. Find. If the developer pastes an issue id, don't put it in a command \
yourself: call start_autopilot again with it as "issue", which checks it. If \
these steps came with an issue, skip to step 7. Otherwise run:
   npx -y {baton_eval} run 2> baton-eval.log
   When it finishes, the log has "experiment <id>: found N issues" and one \
line per issue:
   issue <rank>. <id> <text|code|none> tool=<tool> prod_sessions=<n> \
tasks=<ids|-> below_bar=<yes|no> page=<url|->: <error>
   Go on to step 6. If it has "found no issues" or "find ended (<reason>)" \
instead, report that and stop.

6. Pick. List the issues in rank order, in plain words: what goes wrong with \
the tool, how many real sessions hit it (prod_sessions), and which tasks hit \
it ("-" means none yet). "text" means Baton can draft a text fix. "code" \
means the fix is likely in the tool's code, and "none" means Baton has \
nothing to draft from; for either, the developer can first use "Write a \
fix" on the issue's page. For below_bar=yes, say it fails rarely and ask whether it is a \
real problem or too strict a check. Ask which issue to fix.

7. Fix. <id> is an issue id from the find's log, or the issue these steps \
came with. Repeat step 4, then run:
   npx -y {baton_eval} run --issue <id> 2> baton-eval.log
   If the Console refuses the issue, the run fails before spending anything \
with "baton-eval: POST <path>: <status> <code> <message>": show the \
message. For not_text_fixable or nothing_to_draft, the developer can write \
the fix with "Write a fix" on the issue's page, then run this step again. \
If it fails with a message saying "pass --fresh", the last run's tasks can't be \
reused: running them all again costs more, so repeat step 4 and run with \
--fresh. When it finishes, the log has a line:
   experiment <id>: fix <id>: <verdict>; targets <passed>/<runs> -> \
<passed>/<runs>; error <hit>/<runs> -> <hit>/<runs>; guard \
<held|dropped|none>; held-out <held|didn't hold|none>
   "targets" counts passing runs on the tasks that hit the issue, before -> \
after. "error", only sometimes there, counts runs where the issue's error \
came up. "guard" is the other tasks; "held-out" the tasks kept for last; \
"none" means there were none to check. Report it in plain words with the \
numbers, e.g. "Helped: the error went from 13 of 20 runs to 0, and tasks \
passing stayed 20 of 20." Only claim what the line shows was checked.
   - helped: more target runs passed or the error clearly dropped, and \
nothing checked got worse. The developer approves it on the page.
   - no_better, worse, hurt_held_out: say which.
   - no verdict: the try was judged, but the budget ran out before the \
experiment finished; report the numbers.
   - ended (no_task_hits): go to step 8.
   - ended (nothing_to_draft): Baton has no fix to try for this issue.
   - ended (no_room): the tool's text is too long to add a fix to.
   - ended (doesnt_compose): the server's text no longer has what the fix edits.
   - ended (not_loaded): the server didn't load the change; check step 1.
   - ended (abandoned): the run stopped partway (baton-eval was closed or \
crashed). Start it again.
   Then tell the developer they can choose "Draft another fix" or "Edit the \
text" on the issue's page, linked from the experiment page.

8. No task hits the issue. Call get_issue with the issue id and server \
"{vendor_id}". Draft one task from what it returns, in the check format it \
gives. Rewrite the example requests: never copy a name, id or value from them, \
and don't save them anywhere. Show the developer the task and why it is \
needed, and add it to the task file, without "held_out", only if they say \
yes. Then repeat step 7: only the new task runs before the fix. If it ends \
no_task_hits again, tell the developer the new task didn't hit the issue \
either, and stop.
"""


def autopilot_steps(vendor_id: str, issue: str | None = None) -> str:
    steps = STEPS.format(vendor_id=vendor_id, console=api_base_url(), baton_eval=BATON_EVAL)
    return f"These steps come with issue {issue}.\n\n{steps}" if issue else steps


def add_autopilot(mcp: FastMCP) -> None:
    @mcp.tool
    def start_autopilot(
        # Pasted into a shell command the developer runs (test_tool_refuses_anything_but_a_server_id).
        vendor_id: Annotated[str, Field(pattern=SERVER_RE.pattern)],
        # Also pasted into a shell command (test_tool_refuses_anything_but_an_issue_id).
        issue: Annotated[str | None, Field(pattern=ISSUE_RE.pattern)] = None,
    ) -> str:
        """Find and fix your server's issues with Baton Autopilot. Real agents run your server's tasks, Baton ranks the issues they hit, and it tests a text fix for the one the developer picks.

        Call it when the developer asks Baton to improve their server or to fix an issue (they may paste its id). It returns the steps to follow on the developer's machine and runs nothing itself.

        vendor_id: the server's id, the last part of its DSN.
        issue: an issue id the developer pasted, to fix that issue without a find first.
        """
        return autopilot_steps(vendor_id, issue)
