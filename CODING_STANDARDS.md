# Code rules

The reviewer reads this, not the worker. A mechanical rule (a forbidden API, an import form, a file location) is a
check in the linter or in `checks`, not a line here. Here are only the rules that need judgement.

The general rules of work (one source of truth, only what the task asks, one reason to change) come to the worker and
the reviewer from Antagor in the brief: the rubric «Rules of the work», items C3–C5. Here are the rules of this project on top of it. A rule true for
any project does not go here: send it to Antagor as a precedent (`antagor idea add --for antagor`), so it reaches every project.

<!-- - **Rule.** Why. -->

- **A simple solution is better than a clever one (KISS).** Why: agents edit the code in parts; a clever trick does not fit into their context.
- **No noodle code.** A file of thousands of lines is a sign of mixed duties: cut it by meaning. The gate `[docstring] max_file_lines` checks the file length, not only the reviewer.
- **One capability, one module, not a mix in one file.** A new capability lives in its own file; the shared file gets one line that connects it (a call, a command registration, an event subscription). A file that almost every task edits (the CLI, the main docs) is cut by topic. Why: parallel agents do not share files — a shared file puts them in a queue and gives merge conflicts; a small module fits into the agent's context and is checked on its own.
- **Every code file starts with a description that has one complete meaning** (a module docstring, a leading comment). What is in the file and why, in one paragraph. When the code changes, the description changes. Why: an agent reads the file from the start and decides by the description if it came to the right place; a stale description sends it the wrong way. For Python and JS/TS the gate `[docstring]` checks it, not only the reviewer.
