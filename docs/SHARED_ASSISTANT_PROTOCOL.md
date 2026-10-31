# Shared Assistant Collaboration Protocol

**This file must be kept byte-for-byte identical in both repositories.**
Canonical path in each repository: `docs/SHARED_ASSISTANT_PROTOCOL.md`.

This protocol governs collaboration between AI assistants working with Mike across the Donegal Townlands and Grá repositories. It supplements, and never overrides, each repository's `AGENTS.md`, project documentation, source licences, privacy rules, or Mike's explicit instructions.

## 1. Shared source of truth

- Git repositories are the durable shared workspace. Chat histories, assistant memories, and private notes are not shared project state.
- Before work, read the current repository's `AGENTS.md` and this protocol.
- Then read relevant status and decision documents. In Grá, check `ROADMAP.md` before starting. In Donegal Townlands, check the relevant townland `STATUS.md` and `DECISIONS.md`.
- Follow deeper documentation only where the task requires it. Do not assume a previous assistant's summary is current.
- If repository state is unavailable or stale, say so. Never imply that a snapshot is the live repository.

## 2. Project boundaries and relationship

- **Grá is the research engine.** It owns source acquisition, evidence processing, record linkage, Irish genealogical rules, and the distinction between evidence and conclusions.
- **Donegal Townlands is a downstream publishing project.** It presents family-centred townland studies and must not independently reimplement Grá's fetching or record-linkage logic.
- Donegal Townlands is an important real-world use case that can inform Grá's research priorities and expose gaps. This does not make Grá dependent on the publishing repository or authorise automatic schema, scoring, or architecture changes.
- Data flows from Grá to Donegal Townlands through an explicitly agreed export contract. Changes to that contract require design discussion and Mike's approval before implementation.
- Preserve the evidence/conclusion boundary and all project-specific architecture rules. A presentation need must not weaken research integrity.

## 3. Start every task deliberately

Before editing:
1. Identify the requested outcome and the repository in which the change belongs.
2. Read applicable instructions, status, decisions, and (for Grá) the roadmap.
3. Search for existing implementations, open work, and prior decisions.
4. State the proposed scope, files likely to change, and validation approach.
5. If the task touches a protected boundary, schema, scoring, matching behaviour, export contract, privacy, licensing, or a material architectural decision, stop for design agreement rather than quietly implementing it.

Do not broaden a task because adjacent improvements seem attractive. Record follow-on ideas separately.

## 4. Make changes small and reviewable

- Prefer small, coherent changes that can be reviewed independently.
- Preserve source provenance and uncertainty. Never silently turn a hypothesis into a fact or a candidate match into a confirmed identity.
- Do not overwrite another assistant's unreviewed work. Inspect current diffs and repository state before editing or committing.
- Do not delete files, history, published material, or source data unless Mike explicitly asks.
- Check provenance and redistribution rights before adding data, using the relevant repository's source register.
- Follow all privacy and living-person restrictions in the relevant repository.
- Never commit credentials, tokens, private configuration, or other secrets.

## 5. Independent review is separate

- A change is not accepted merely because an assistant implemented it, tests pass, or it has been pushed.
- Where practical, ask a different assistant to review independently. The reviewer should inspect the diff and relevant context, not simply endorse the implementer's summary.
- Review correctness, scope, evidence quality, licensing, privacy, architectural boundaries, regressions, and fit to the request.
- Report specific findings, with file and line references where possible. Distinguish blocking defects from suggestions.
- The implementer should respond to each substantive finding. If assistants disagree, preserve the disagreement and present alternatives and consequences to Mike.
- Mike decides unresolved questions and whether a change is accepted. Assistant approval is not a substitute for his approval where required.

## 6. Tests and validation

- Run checks required by the repository's `AGENTS.md` and project documentation.
- Report exactly what was run and whether it passed. Do not claim checks that were not performed.
- If a check could not be run, explain why and identify the remaining risk.
- For Grá, run its required test suite. Changes affecting linkage thresholds or scoring also require the timing report and a note of material match-rate shifts.
- For Donegal Townlands, run `python tools/validate.py` before a commit and rebuild affected pages using the documented build command. Never hand-edit generated pages.

## 7. Handover for substantive work

At the end of substantive work, leave a concise handover in the repository's established status, changelog, or roadmap location. Do not create a competing log if one already exists.

A handover should state:
- **Outcome:** what changed and why.
- **Files:** important files changed.
- **Evidence and decisions:** sources used, assumptions, decisions required, and unresolved uncertainties.
- **Validation:** commands/checks run and results.
- **Review:** whether independent review occurred and open findings.
- **Git state:** branch and commit reference, if known; whether changes are committed or pushed.
- **Next step:** the smallest useful next action.

Keep durable project facts in repository documentation, not only in chat or assistant memory.

## 8. Coordinate safely across assistants

- Before editing, check whether another assistant has changed relevant files or recorded in-progress work.
- Use branches or clearly separated commits where possible. Avoid concurrent edits to the same files.
- If assistants work in parallel, agree file ownership and interfaces first.
- If a conflict occurs, do not silently choose a version. Preserve both proposals, explain the trade-off, and ask Mike.
- A push is a transfer of work, not proof of review or acceptance. Include a handover with every push intended for another assistant.
- Never assume assistants can see one another's conversations, private workspaces, or unpushed changes.

## 9. Keep this protocol identical

- The canonical relative path is `docs/SHARED_ASSISTANT_PROTOCOL.md` in both repositories.
- When changing it, edit one copy first, then copy the exact same content to the other repository in the same change cycle.
- Verify identity with a byte-for-byte comparison or matching SHA-256 hashes before considering the update complete.
- Update each `AGENTS.md` only to link to this protocol and explain that it supplements repository-specific rules. Do not fork or paraphrase the shared protocol in either file.
- If one repository cannot be updated at the same time, record the temporary mismatch and do not claim the copies are synchronised.

## 10. Authority and escalation

The order of authority is:
1. Mike's explicit instructions and decisions.
2. The current repository's project-specific rules and recorded decisions.
3. This shared collaboration protocol.
4. An assistant's proposed approach or preference.

When instructions conflict, stop and explain the conflict. Do not invent permission, infer approval from silence, or conceal uncertainty.
