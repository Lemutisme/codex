You are improving how an autonomous agent works. Its method is the policy bundle in ./policy:

- executor.md: standing instructions the agent follows on every task;
- drafter.md, prober.md, reviewer.md: how its work is turned into a contract, probed by a sealed suite and reviewed;
- analyst.md, challenger.md, research.md: how it studies its own runs and changes itself.

Work like a careful experimenter.

1. Start from understanding. Read archive/knowledge/, which holds what the campaign has learned: mechanisms with their standing, refuted beliefs, task dossiers and proposals. Then read the latest archive/insight/*/ANALYSIS.md and CHALLENGE.md. Before you rely on a mechanism, open the trajectories it cites (archive/runs/*/trajectory.md) and see it yourself.

2. Choose one mechanism. Its evidence should be strong and its reachable failure mass large: archive/README.md sums the latest credit table (insight/*/hindsight.json) by how the information stood. Refuted beliefs are off the table. A cluster that no behavior can reach is not a target.

3. Find the lever: which file governs that behavior?
   - Restating what the agent already does changes nothing.
   - Instructions to keep notes or ledgers have not been followed.
   - The sealed suite shares the executor's blind spots, so prober.md is itself a lever.
   - If the right lever lies outside the bundle (the harness, the measurement), make the null experiment and say what the principal should change.

4. Make the smallest change that tests the hypothesis. Prefer rewriting or deleting text to adding it, and change one mechanism at a time. Every sentence of executor.md is read on every task. The task-shaping files (executor.md, drafter.md, prober.md, reviewer.md) must stay task-agnostic: never name a task, program or test. Qualification rejects names of tasks the campaign has evaluated.

5. Remember what evidence can show. The agent's own checks measure diligence. Only the hidden outcomes certify, and one run decides only where chance is quiet: items every stored run failed seldom pass by chance (archive/README.md gives the rate). So name, in ./prediction.json, the floor items your change will rescue: {"rescue": {"<task>": ["<item id>", ...]}}. The host registers the prediction before any run and settles it from the hidden outcomes. A version is put forward only when its prediction holds, the next analysis counts its signature in the trajectories, and its development score clears the gate.

6. Write ./EXPERIMENT.md with these sections:
   - Mechanism: the knowledge entry and archive pointers it rests on.
   - Hypothesis.
   - Change: what you edited and why.
   - Signature: the behavior the change must produce, stated so it can be counted in a trajectory.
   - Prediction: which items move and why, matching prediction.json, and what else should move, in which direction, compared with the task's noise.
   - Falsifier.
   - Risks.

A careful negative result is a valid outcome. If no small change is likely to work, or the evidence is too thin, leave the bundle unchanged and say why.
