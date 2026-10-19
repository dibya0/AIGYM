# Loom script (target ≈ 10 min; brief: 8–12 min)

**Brief requirements:**
- narrate design decisions, not features;
- at least 3 minutes on reward design;
- at least 1 minute reading a real failure transcript aloud;
- show the sandbox scoring a live request.

**Before recording, open these tabs:**
1. the dashboard, https://aigym-alpha.vercel.app;
2. `ruleset/v1.0/RULESET.md` (GEN-§9);
3. `paygym/rubric.py` (the docstring's score levels and "Why v1.x");
4. `docs/RL_REPORT.md` B5/B6;
5. a terminal in the repo;
6. the dashboard transcript viewer on Flash-Lite `gen-2000005-twin` and on the trained 0.5B `gen-2000013-trap`.

---

## 0:00–0:45: what and why (45 s)

> "PayGym is a gym for agents doing gross-to-net payroll under a written rule set: three fictional jurisdictions, so no model can answer from memory. The rule book is prose with clause ids, and a reference calculator cites a clause for every step. That calculator is the verifier, so I can generate unlimited graded tasks with no labelling. Everything here ran for $0: free tiers plus my own GPU."

*Show:* the dashboard header and the verdict panel.

## 0:45–2:00: tasks, traps and twins (75 s)

> "There are three tiers. Retrieval. Payslips, where ceilings, proration, mid-month raises and FX interact. And traps, where the rules do *not* determine a payslip: a missing input, conflicting records, no rate table for that year, or an unsupported currency. Every trap has a twin that differs only in something that isn't an input, like a job title. The twin is what makes over-refusal measurable. Without it, a gym that rewards refusing looks careful."

*Show:* GEN-§9 in RULESET.md, especially the sentence "a disagreement about … a job title does not make the payslip undetermined".

## 2:00–5:30: reward design (3.5 min, the core)

1. **Score levels and gates (60 s).** "The total is gated, not a weighted sum. A wrong net pay is capped at 0.25 however many lines are right, because a payslip with the wrong pay is wrong. Weights are 0.70 net, 0.25 lines, 0.05 format. Line accuracy reports the first wrong line in computation order with its clause, so a failure points at a rule. The ranking doesn't move under four alternative weightings, τ = 1.0."
2. **Why every wrong decision is −1 (90 s): the story the trained policy taught me.**
   - "My first rubric gave a refusal of a payable payslip a little format credit. Then zero. Under zero, GRPO learned to refuse all 47 validation tasks within 20 steps, and the validation reward *went up*. Refusing was free; answering a trap cost −1.
   - So I made both wrong decisions cost −1. The policy then wrote broken JSON for every task, because 'no usable answer' still cost 0.
   - So unusable became −1. At the too-low β it found a third one: the word 'reject' in the decision field, which my scorer read as a refusal on traps and as a harmless answer on payslips.
   - Each time I checked the fix offline on the policy's real outputs before retraining. Under the final rubric, refuse-everything scores −0.69 and refusing only traps scores best."

   *Show:* rubric.py's "Why v1.2/1.3/1.4" docstring and the RL_REPORT B6 table.
3. **What the hand-written baselines missed (30 s).** "Five adversarial baselines stayed under their floors the whole time and found none of the three. That's the brief's point: an optimiser attacks your reward harder than you can by hand."
4. **The judge (30 s).** "The LLM judge only scores trap explanations, the one genuinely unverifiable part, worth 0.2 of a correct refusal. It uses a pinned model and a versioned prompt, its reliability is measured, and it is kept out of the RL reward."

## 5:30–7:00: reading a failure transcript aloud (90 s)

Read the trained 0.5B on `gen-2000013-trap` (Nordmark, January 2024, no 2024 rate table):
> "decision: answer… reason_code: NO_APPLICABLE_TABLE… explanation: there is no relevant rate table, the payslip cannot be determined."
>
> "It *knows* it's a trap: it names the right reason and explains it, and then it answers anyway. All 56 of its answered-trap rollouts look like this. RL pushed it to always answer, because payslips are three quarters of the reward, but it didn't erase the recognition. The scorer reads the decision field, so this is −1."

Then, briefly, Flash-Lite on `gen-2000005-twin`:
> "Gemini refuses a payable payslip because the HR record and contract give different job titles. The rule book says job title is not an input. 9 of its 22 wrong refusals are exactly this. The twin caught it."

## 7:00–8:15: what RL actually did (75 s)

> "GRPO on Qwen-0.5B with LoRA: Dr. GRPO loss, no std scaling so the −1s keep their size, and β 0.04 against 0.001.
>
> On held-out tasks it never trained on, scored once, it improved by 0.34 at the training difficulty and 0.30 at full difficulty, with confidence intervals well above zero. It learned to write valid payslips and to stop refusing payable work. It got worse on traps: it answers all of them. The 0.001 run drifted seven times further in KL and learned the 'reject' exploit; 0.04 never touched it. So I'd set β at 0.04 or higher."

*Show:* the dashboard RL section (validation curve, held-out tables).

## 8:15–9:15: live sandbox (60 s)

```bash
curl -s https://aigym-alpha.vercel.app/quickstart.py | python3 - https://aigym-alpha.vercel.app
```

> "No clone needed. This fetches five Tier 2 and 3 tasks, with no answers on the wire, which a fuzz test checks on every endpoint. It submits a trivial refuse-everything agent and prints a score per task with its breakdown and the clause behind it. It's the same rubric as the dashboard, and a parity test proves it. There's a run id carrying the rule-set version, seed and tier mix, a 50-task cap, and a per-caller rate limit in Redis. Interactive docs are at /docs."

*Show:* the output, then `/docs` in the browser.

## 9:15–10:00: what the gym says, and what's next (45 s)

> "The commercial answer the gym gives: no model here computes payroll reliably. Gemini Flash-Lite gets net pay exactly right on 6 of 210 payslips; a script that ignores ceilings gets 111. LLMs win on decisions and lose on arithmetic, so decide with the model and compute with a calculator. For small models, the cheapest scaffold, putting the rules in the prompt, gives most of the gain.
>
> Next: a 1.5B policy to see whether trap discrimination becomes learnable, and turning the three exploits into permanent baselines."

---

**Timing check:** reward design 2:00–5:30 = 3.5 min (≥ 3 ✅); transcript 5:30–7:00 = 1.5 min (≥ 1 ✅); live sandbox 8:15–9:15 ✅; total ≈ 10 min ✅.
