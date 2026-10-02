# Tablekeeper Factory

## Scope

Build Tablekeeper Stages 1 and 2 sequentially from the official
specifications. Each stage has an independent Dockerfile and RUN.md.
The challenge harness remains separate from this repository.

## Seats

Three Codex seats used the gpt-6-luna model through BAND-owned
Codex app-server runtimes:

- Purrallel Planner: acceptance criteria, assignments, and coordination.
- Chris Builder: implementation, commits, and fixes.
- Purrallel Verifier: independent review and official harness verification.

Their generic instructions are stored in mandates/.

## Workflow

The initial task instructed the team to build fresh from the official
specifications without copying earlier development solutions.
The Planner delegated requirements, the Builder committed implementations,
and the Verifier reviewed committed revisions and ran the unchanged
official harness in isolated mode. Findings were returned for fixes
and verification was repeated.

Stage 1 was completed before copying it forward into stage-2/.
The completed stage-1/ was preserved.

## Recorded evidence

Stage 1 report revision: `d05dedc85791cae49d347e33827ed27d0cf785a9`.
Evidence: `evidence/stage-1-d05dedc/`.

Stage 2 report revision: `b646170cbd5feb41a37a36e1000706880c368b77`.
Evidence: `evidence/stage-2-b646170/`.

The Stage 2 report records 120 Stage 1 checks and 25 Stage 2 checks
passing, with zero failures, errors, or skips.

The reports record provenance as working-tree. Their revision fields
identify the recorded implementation; the reports alone do not establish
that every build input was committed.

## Infrastructure and human intervention

Approval policy was configured as never and tool access as
danger-full-access before task dispatch.

During the run, the owner stopped and reattached agents, restarted Docker,
and sent an infrastructure recovery instruction. The owner subsequently
copied verification artifacts into evidence/ and committed them.

This was an intended autonomous factory run with human infrastructure
recovery. It is not claimed as an uninterrupted run with no intervention.

Measured inference cost has not been recorded.

## Room and recording

Generation room: `78dfb711-01b3-4372-8823-758fb742f4e2`.

The complete room export is included at room.json (3,773 messages).
The submission video must include this actual BAND Desktop room and
a walkthrough of the resulting service. Video completion is pending.
