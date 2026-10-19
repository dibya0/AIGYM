# RL training report

Brief §9 deliverable #7 and Phase 07. **Part A was written and committed before any training run** (pre-registration); Part B is filled from committed result files after training.

---

## Part A: pre-registration (written before training, 2026-10-18)

### A1. Algorithm and objective actually implemented
GRPO with the **Dr. GRPO** loss, via TRL 1.14.1 `GRPOTrainer` (`train/grpo_train.py`). For a prompt *q* with a group of *G* = 8 sampled completions *o₁…o_G*:

```
r_i      = PayGym rubric total for o_i  (paygym.rubric; judge weight 0 in training)
A_i      = r_i − mean(r_1..r_G)          # scale_rewards="none": NOT divided by std(r)
ρ_i,t    = π_θ(o_i,t | q, o_i,<t) / π_θ_old(o_i,t | q, o_i,<t)
J(θ)     = 1/(G·L_max) Σ_i Σ_t  min(ρ_i,t A_i , clip(ρ_i,t, 1−ε, 1+ε) A_i)  −  β · KL̂(π_θ ‖ π_ref)
KL̂       = per-token k3 estimator:  exp(log π_ref − log π_θ) − (log π_ref − log π_θ) − 1
```
- **`loss_type="dr_grpo"`** normalises by the constant `L_max` (max completion length), not each completion's own length. Per-sequence length normalisation creates a length bias (a policy can game it by changing answer length); the brief lists length hacking as an edge case.
- **`scale_rewards="none"`.** Dividing by the group std rescales every group to unit variance, which silently replaces the rubric's designed magnitudes (e.g. −1 for answering a trap vs 0.05 for refusing a determinable task) and can push towards blanket refusal (arXiv 2608.00301). The Dr. GRPO paper also recommends no std scaling.
- **π_ref** = the base model with the LoRA adapter disabled: a frozen copy of the initial policy at no extra memory (TRL does this automatically for PEFT models when β ≠ 0).
- **Why GRPO:** group-relative advantage needs no value network, so it is the cheapest credible on-policy method on one 16 GB GPU, and the advantage is transparent (each completion compared with its siblings).

### A2. Configuration
| Item | Value |
|---|---|
| Policy | `Qwen/Qwen2.5-0.5B-Instruct` + LoRA r=16, α=32, all linear layers, bf16 |
| Hardware | 1 × RTX 5070 Ti 16 GB (local), $0 |
| Data | `train` split (seeds 0–10k; no retrieval tasks), difficulty preset chosen by the pilot (A4) |
| Group size G | 8 (brief: ≥ 4) |
| Prompts / step | 4 (32 completions per step) |
| Max completion | 384 tokens |
| LR | 2e-5 |
| LR schedule | constant, no warmup (amended 2026-10-19, before any training run; see A9) |
| Steps | ≤ 150 (≈ 3 passes over ~200 tasks) |
| Checkpoints | every 25 steps |
| Reward | Phase 04 rubric, programmatic components; judge weight 0 |

### A2b. Why each hyperparameter has its value (and what is tuned)
| Hyperparameter | Value | Reasoning | Tuned? |
|---|---|---|---|
| Algorithm | GRPO (Dr. GRPO loss) | **Rewards:** our rewards are verifiable and per-completion, so a group of samples gives a baseline for free. **Alternatives:** PPO needs a value network (2× memory, plus critic instability on a 0.5B); RLOO is equivalent in spirit but less supported in TRL; DPO/SFT need preference or gold traces and do not optimise our actual rubric; REINFORCE without a group baseline has high variance. | No: chosen by argument |
| Group size G | 8 | The brief's minimum is 4. With binary-ish rewards and pass rates ≈ 0.2–0.6, G = 8 makes an all-identical group unlikely (≈ 0.6⁸ + 0.4⁸ ≈ 2% at p = 0.4) while fitting memory. | No (G = 4 only in the smoke test) |
| Prompts per step | 4 (32 completions) | A stable advantage estimate per step that still fits ~150 steps in ~45 min | No |
| Learning rate | 2e-5 (LoRA) | LoRA adapters need ~10× the full fine-tune LR; 1e-5 to 5e-5 is the usual LoRA GRPO range | No (the A8 probe was cancelled in A10, before training) |
| LoRA rank / α | 16 / 32 | Enough capacity to change output format and decision behaviour on 0.5B; α = 2r is the common default | No |
| β (KL) | 0.001 vs 0.04 | Required sweep, one deliberately too low; β = 0 logs no KL in TRL | **Yes: the sweep** |
| Clip ε | 0.2 (TRL default) | Standard PPO/GRPO trust region; not a lever the brief asks about | No |
| Loss / reward scaling | `dr_grpo`, `scale_rewards="none"` | Removes length bias; keeps the rubric's designed magnitudes (A1) | No: chosen by argument |
| Temperature | 1.0 | Exploration: lower temperatures increase identical groups (no gradient) | No |
| Max completion | 384 tokens | A full payslip JSON plus a short explanation is ~250 tokens; the cap limits length hacking and memory | No |
| Training difficulty | default / easy / easier | Picked by the pilot so the base policy is neither ~0% nor ~100% | **Yes: the pilot (A4)** |

### A3. KL sweep
Two runs, identical except β: **β = 0.001** (deliberately too low; the reference still loads, so KL is logged every step) and **β = 0.04**. β = 0 is not used because TRL skips the reference model entirely at β = 0 and logs no KL, which would make the "too low" run unmeasurable.

### A4. Difficulty pilot (before training)
Base policy, G = 8 on ~50 training tasks (`scripts/pilot_report.py`). Target: Tier-2 pass rate ≈ 0.2–0.6 and a low fraction of all-identical groups. If base 0.5B is near 0 %, the **training tasks** are made easier (`--knobs easy`, then `easier`); the model stays 0.5B and eval/held-out keep full difficulty.

### A5. Stop rules (pre-registered)
A run stops at the first of:
1. **Budget:** 150 steps.
2. **Validation plateau:** every 25 steps the policy is scored greedily on the *validation* split; stop if the best score has not improved by ≥ 0.02 over 3 consecutive checks.
3. **Safety stop:** rolling mean over the last 5 logged steps of: per-token KL > 1.0, entropy < 0.05, twin refusal rate > 0.5, modal net-pay share > 0.5.

A safety stop is not a failure: it is the trigger to read transcripts for reward gaming (A7).

### A6. Model selection and held-out evaluation
- **The final model is the best-validation checkpoint.** It is scored **once** on the held-out split (seeds 1M+; content-disjoint from train, tested) with the same eval harness and environment as the leaderboard, 3 rollouts. The base model is scored on the same held-out tasks.
- **Report:** before vs after with a paired bootstrap 95 % CI, per tier, twin score and trap-answered rate.
- The held-out split is never used to choose anything. Choosing by held-out score would turn it into training signal (brief p.12).

### A7. Reward-gaming hunt
At each checkpoint, read ≥ 20 completions (`log_completions` samples plus validation outputs) and the monitors. Candidate exploits, each with its monitor:
- **Refuse everything** (the collapse law): `monitor/twin_refusal_rate`.
- **Compute traps anyway:** `monitor/trap_answer_rate`.
- **One modal answer for every prompt:** `monitor/modal_net_share`.
- **Length padding:** `monitor/len_reward_corr`, `completions/mean_length`.
- **Valid JSON with garbage:** the gap between `format_valid` and `net_pay_exact`.
- **Lines that sum consistently but are wrong:** first-wrong-line clauses in transcripts.

If one is found: transcript evidence → rubric fix (version bump) → rerun → before/after table. If none is found: document what was checked and why the gates held.

### A8. Learning-rate probe (pre-registered, cheap)
- **Runs:** three 30-step runs at LR ∈ {1e-5, 2e-5, 5e-5}, β = 0.04, same train file and seed, validation every 10 steps (~10 min each).
- **Selection rule (fixed in advance):** pick the LR with the highest validation reward at step 30, **excluding** any run that triggered a safety stop or whose rolling KL exceeded 0.5; ties go to the lower LR.
- **Use:** the chosen LR is used for both β runs.
- **Discipline:** selection uses the validation split only; held-out stays untouched. The probe is reported in full (B1b), including the losing settings.
- **Not tuned, and why:** with a ~1–2 h GPU budget, tuning everything would mean many short noisy runs, and choosing the best of many noisy runs is itself a form of overfitting. We tune the one knob that most often breaks small-model GRPO (LR), the one the brief requires (β), and the data difficulty. Everything else is set by the reasoning in A2b.

### A9. Amendments before training (logged, not hidden)
- **2026-10-19, after the smoke test (reward = format only, so not a result):** the LR schedule is now **constant** with no warmup. The smoke run showed TRL's default linear decay (2e-5 → 2e-6 over 10 steps). With decay, the effective LR depends on `max_steps`, so a 30-step probe (A8) would not transfer to a 150-step run, and a plateau stop would compare checkpoints trained at different LRs. No training result had been seen when this was changed.
- **Measured cost:** smoke config (2 prompts × G = 4 = 8 completions/step, HF generation) ran at ≈ 24 s/step on the RTX 5070 Ti. The real config is 32 completions/step; Step 17 measures it before the runs are sized.

- **2026-10-19, A10 (before any training run): scope reduced to the brief's minimum**, at the user's request to show the full flow quickly. Brief p.12: "A working loop on a 0.5B model over 30 training tasks, with real curves and an honest held-out comparison, scores far better than an ambitious run that did not converge."
  - **Training set:** 30 tasks (first 30 of the train file chosen by the pilot), not ~200.
  - **Steps:** 60 per run (was ≤ 150); G = 8; 2 prompts per step (16 completions/step); ≈ 4 passes over the 30 tasks.
  - **Validation and checkpoints:** every 20 steps (was 25), so a run has 3 checks plus step 0. The plateau rule (3 checks without +0.02) can therefore only fire at the end; the safety stops are unchanged.
  - **LR probe (A8) cancelled.** It is not a brief requirement. LR stays at 2e-5 for the reasons in A2b, and A2b's "Tuned?" column now reads "no" for LR. Reported as a limitation: the LR was not tuned.
  - **Pilot:** 30 train tasks × 4 samples (brief's G minimum), same rule as A4.
  - **Unchanged:** algorithm, loss, β ∈ {0.001, 0.04}, stop rules, model selection on validation only, held-out scored once (109 tasks × 3 rollouts).

- **2026-10-19, A11 (after the pilot, before any training run): preset choice when no preset meets the A4 target.**
  - **Pilot** (base Qwen-0.5B, 30 train tasks × 4 samples, temperature 1.0, 384 tokens): **Tier-2 exact pass rate 0 % on every preset** (default / easy / easier). A4's target (≈ 0.2–0.6) is unreachable without changing the model, and the model is fixed at 0.5B by the user's scope.
  - **Signal measured per preset:**

    | Preset | Groups with reward spread | Trap refused | Twin refused | Valid JSON | Line accuracy |
    |---|---|---|---|---|---|
    | default | 20% | 22% | 12% | 62% | 0.12 |
    | easy | **30%** | **44%** | 25% | **76%** | 0.13 |
    | easier | 20% | 3% | 25% | 63% | 0.14 |
  - **Rule applied (set now, before training):** choose the preset with the highest fraction of groups with reward spread, i.e. the most non-zero advantages. That is **`easy`** (`tasks/generated/train_easy.jsonl`, first 30 tasks).
  - **Expectation, stated in advance:** the policy can learn **format** (unparseable 16 % → lower), **trap decisions and reason codes** (answered traps → refusals with the right code), and partial line credit. It is **not** expected to learn exact payroll arithmetic (exact net pay stays ≈ 0). If trap refusals rise, the twins' refusal rate and `monitor/twin_refusal_rate` are the check against learning "refuse everything".
  - **If validation does not improve by step 40 on either β run,** the documented next step (not run without the user's decision) is Qwen2.5-1.5B-Instruct, inside the brief's 0.5–2B band.

- **2026-10-19, A12 (after two runs stopped at steps 6–7, before the runs reported in Part B): two implementation fixes.**
  1. **Sampler parity.**
     - **Before:** training sampled with TRL's defaults (top_p 1.0, top_k off, repetition 1.0), while the pilot (vLLM) used the model's own `generation_config` (top_p 0.8, top_k 20, repetition 1.1). The pilot had measured a different, sharper policy than the one being trained.
     - **Symptoms:** broken JSON up to 69 % in training vs 16–38 % in the pilot; a twin refused 6/8 at step 2, after two near-zero updates (KL 0.0006), against 0/4 for the same task in the pilot.
     - **Fix:** training now samples with the model's settings (temperature 1.0, top_p 0.8, top_k 20, repetition 1.1), recorded in `config.json`.
  2. **Collapse stops relative to the start.**
     - **Before:** each logged twin-refusal / modal-answer value comes from one or two prompt groups, and the base model already refuses some twins 4/4, so the absolute threshold (rolling mean > 0.5) fired on noise at steps 6–7, before any learning.
     - **Fix:** these two stops now also require a rise of ≥ 0.25 over the policy's own first 5 logged values.
     - KL and entropy stops are unchanged.
  - The four stopped runs are kept as evidence (`results/train/v1.0-*`, `results/train/v1.1-trlsampler-*`). None is used for model selection or held-out results.

- **2026-10-19, A13 (before any reported run; no learning result seen): measure where the policy trains, and a faster LR.**
  1. **In-distribution validation and held-out.**
     - **Problem:** training uses the `easy` preset (A11), while `val.jsonl` / `heldout.jsonl` are full difficulty, where the base 0.5B scores 0 on payslips. Learning on the trained distribution could be invisible there.
     - **New sets:** `val_easy.jsonl` (47 tasks, seeds 500000–500035) and `heldout_easy.jsonl` (124 tasks, seeds 1000000–1000094), generated with the training preset from the never-trained seed ranges. Checked: 0 content and 0 seed overlap with `train_easy.jsonl`.
     - **Checkpoint selection** uses `val_easy` (validation only).
     - **Held-out is reported twice, each scored once:**
       - `heldout_easy`: did the gym teach the policy something, on tasks it never saw?
       - `heldout`, full difficulty: does it transfer?
       - Neither is used to choose anything.
  2. **Learning rate 2e-5 → 5e-5.**
     - **Why:** the first 7 steps at 2e-5 moved the policy by KL ≈ 0.004 with grad norm ≈ 0.01. With 60 steps, that is too slow to show learning.
     - **Range:** 5e-5 is the top of the range A2b / A8 named as normal for LoRA GRPO; the KL safety stop (1.0) still applies. The LR remains untuned (A10) and is reported as such.
  - **Unchanged:** everything else (β sweep, G, steps, rubric v1.1, sampler, stop rules).

- **2026-10-19, A14 (before the v1.2 runs): rubric v1.2 and success criteria for the rerun.**
  - **Trigger:** the v1.1 run `grpo-b0.001` learned to refuse everything (validation step 20: 47/47 refused, val reward −0.063 → +0.081; B6).
  - **Change (rubric 1.2):** refusing a determinable task scores −1, exactly like computing a trap, so both wrong compute/refuse decisions cost the same.
  - **Checked offline first, on that run's real outputs:** refuse-everything −0.685 (worst), base −0.063, refuse-only-traps +0.166 (best).
  - **Runs under v1.2:** `grpo-b0.04` (starts automatically after the v1.1 run) and a v1.2 β = 0.001 run (`v12-grpo-b0.001`), so the β sweep is within one rubric. The v1.1 run is kept as the gaming evidence and is not used for held-out results.
  - **Selection:** checkpoints are chosen on `val_easy` scored under v1.2, so a refuse-all checkpoint can no longer win selection.
  - **Success criteria, fixed now:**
    1. **Must:** no refuse-everything collapse. At every validation step, refusals of payable payslips on `val_easy` stay ≤ 25 % (base: 0/36).
    2. **Hope:** best `val_easy` reward > base (−0.063), via fewer broken JSONs and more correct trap refusals.
    3. **Report either way:** if (1) holds but (2) does not, the result is "exploit closed; a 0.5B gains little skill in 60 steps", stated as such.

- **2026-10-19, A15 (before the v1.3 run): the second learned exploit, and rubric v1.3.**
  - **Trigger:** the first v1.2 run (`results/train/v1.2-grpo-b0.04`) learned to write **unparseable JSON for 47/47 validation tasks** by step 20 (arithmetic inside JSON values, e.g. `"net_pay": 4950.0 + 60.0 - 0 …`). `parse_fail_rate` was 1.0 for six training steps.
  - **Why it paid:** with both wrong decisions at −1, "no usable answer" (0) was the only option that never hit −1.
  - **Rubric 1.3:** an unparseable answer scores −1 on every tier.
  - **Checked offline first,** on the real outputs of all three runs:
    - broken-everywhere −1.000 and refuse-everything −0.685 are the two worst policies, both below the base model (−0.319);
    - fixing the base model's JSON alone gives −0.140; refusing only traps gives −0.004;
    - the score is monotone in competence.
  - **Run:** one v1.3 run at β = 0.04, and, if time allows, β = 0.001 for the sweep within v1.3.
  - **Success criteria, fixed now:**
    1. **Must:** no collapse at any validation step: unparseable ≤ 25 % and refused payable payslips ≤ 25 % (base: 12/47 unparseable, 0/36 refused).
    2. **Hope:** best `val_easy` > the base under v1.3 (−0.319).
  - **Also fixed today, eval side (not training):**
    - the bare-JSON parser bug, which had scored valid unfenced gpt-oss answers unparseable;
    - empty timeouts are now infrastructure errors, not answers.
  - **Method lesson for the report:** each rubric fix closed one harbour and the optimiser found the next cheapest one within 20 steps. Hand-written baselines (5) found neither. The fixes were verified offline against real policy outputs, not by retraining blindly.

- **2026-10-19, A16 (during the v1.3 β = 0.001 run, before any held-out scoring): third learned exploit, rubric v1.4.**
  - **Found by the β = 0.001 run:** `"decision": "reject"` (neither answer nor refuse) with a payslip attached. On traps it fell into the refusal branch (+0.3); on payslips it scored 0.0 instead of −1. It was in 197/272 (72 %) of saved training samples and 47/47 validation tasks at step 20, val +0.070.
  - **Rubric 1.4:** no valid decision = unparseable (−1) on every tier.
  - **Verified offline:**
    - β = 0.001 step 20: +0.070 → **−1.000**;
    - β = 0.04 unchanged at every step: it never produced a bad decision on validation (0/188, 5/480 training samples);
    - no eval run changed.
  - **Consequences:**
    - the β = 0.04 v1.3 run is the selected policy (best `checkpoint-60`), and its training signal differed from v1.4 on ~1 % of samples;
    - β = 0.001 is reported as the deliberately-too-low setting that found the exploit;
    - it is not retrained under v1.4 (time; stated as a limitation).

---

## Part B: results (filled after training from committed files)

- B1. Pilot result and preset chosen: see A11 (all presets 0 % Tier-2 exact; `easy` chosen for the most within-group reward spread).
- B2. Curves (reward, KL, entropy, completion length, per-tier pass rate, plus degenerate-group fraction and the collapse monitors):
  - every step, in `results/train/<run>/metrics.csv`; plotted on the dashboard §RL for the four reported runs;
  - the validation curve (`validation.csv`, `val_easy`, greedy) is plotted alongside, because that is what checkpoint selection sees.

  | run (rubric) | steps | KL max / final | entropy first → last | mean length first → last | s/step |
  |---|---|---|---|---|---|
  | `grpo-b0.04` (1.3) | 60 | 0.022 / 0.008 | 0.49 → 0.36 | 189 → 179 | 34 |
  | `grpo-b0.001` (1.3) | 60 | **0.151 / 0.111** | 0.49 → 0.39 | 189 → 186 | 33 |

  No length hacking: mean length is flat, and the length–reward correlation is weak and mostly negative.
- B3. KL sweep: what happened at β = 0.001 vs 0.04, and where we would set β and why:
  - **Same rubric (1.3 for training; validation re-scored under 1.4), same data, seed, LR, steps.**

    | | β = 0.001 (deliberately too low) | β = 0.04 |
    |---|---|---|
    | KL drift from the reference | **0.15 max, 7× higher** | 0.02 max |
    | what the policy learned | the invalid-decision exploit (`"decision": "reject"`) in 72 % of training samples, 47/47 validation tasks from step 20 | valid payslip JSON (unparseable 8/36 → 0/36 on validation); no exploit (0/188 validation outputs) |
    | `val_easy` (v1.4) | −0.319 → **−1.000** | −0.319 → **−0.129** |
  - **Shape:** this is the shape the brief predicts. The low-β policy walked away from the reference into degenerate output that the reward (until 1.4) paid for; the higher β kept it close to the base model and it improved only by doing the task better.
  - **Where we would set β: 0.04,** or somewhat higher. At 0.04 KL stayed under 0.03 and learning was still visible within 20 steps. We did not test above 0.04, so "barely learns at high β" is not demonstrated here; a third value (e.g. 0.1) is the first thing we would add.
  - **Caveats:** one seed per β; both trained under 1.3 and compared under 1.4 (they differ on ~1 % of β = 0.04's training samples and on none of its validation outputs).
- B4. Stop reasons (`stop_reason.json`) and best checkpoints (`best_checkpoint.json`):
  - **Reported runs:** both ran the full 60 steps (no safety or plateau stop).
    - β = 0.04: best `checkpoint-60` (val −0.129), the selected policy.
    - β = 0.001: best `checkpoint-20` under 1.3 (+0.070), which is the exploit and is −1.000 under 1.4. Not taken to held-out.
  - **Stops along the way, each documented in PROGRESS.md:**
    - v1.0 β = 0.001, step 6: false-positive `modal_net_share` stop, a monitor bug, fixed;
    - v1.1 (TRL sampler) β = 0.001, step 7: twin-refusal stop on noise, which led to the relative stops (A12);
    - three crashes at step 14 from an attention-kernel fallback (equal-length prompts, float32, grouped heads, no mask), fixed with an exact chunked fallback, and resumed from `checkpoint-10`.
- B5. Held-out before/after (`results/train/rl_summary_heldout_easy.json`, `rl_summary_heldout.json`):
  - **Setup:** each set scored **once**, never used for any choice. Base Qwen2.5-0.5B vs the selected policy (β = 0.04, `checkpoint-60`), with the same harness, sampler (model `generation_config` via vLLM), 384 max tokens, 3 rollouts, rubric 1.4.

    | held-out set | base | trained | Δ [95 % paired-bootstrap CI] |
    |---|---|---|---|
    | `heldout_easy` (124 tasks, training preset, seeds 1M+) | −0.514 | **−0.176** | **+0.338 [+0.232, +0.442]** |
    | `heldout` (109 tasks, full difficulty) | −0.616 | **−0.312** | **+0.304 [+0.201, +0.411]** |

    | component (easy / full) | base | trained |
    |---|---|---|
    | Tier 2 payslips | −0.416 / −0.463 | **+0.075 / +0.071** |
    | twins (payable look-alikes of traps) | −0.332 / −0.480 | **+0.068 / −0.009** |
    | Tier 3 traps | −0.836 / −0.798 | **−1.000 / −1.000** |
    | traps answered | 56 % / 49 % | **100 % / 100 %** |
    | Tier 1 retrieval (full only; never trained) | −1.000 | −1.000 |
    | run SD | 0.031 / 0.013 | 0.0002 / 0.0002 |
  - **What was learned, and that it transfers:**
    - RL taught the 0.5B to emit **valid, usable payslips and to stop refusing payable work**;
    - the gain holds on full-difficulty tasks it never saw (+0.30, CI excludes 0), so it is not memorisation of the 30 training tasks.
  - **What got worse:**
    - it now **answers every trap** (56 % → 100 %), so Tier 3 went from −0.84 to −1.00;
    - the policy traded its occasional (mostly accidental) trap refusals for always computing, which the rubric pays for overall because payslips are ~3/4 of tasks;
    - this is the limit stated in advance (A11, A14): with almost no within-group variation in the refuse/answer decision, a 0.5B gets little gradient for trap discrimination.
  - **Determinism:** run-to-run SD fell from 0.01–0.03 to 0.0002, so the trained policy is nearly deterministic at temperature 1 with the model's top-p/top-k. That is consistent with the entropy drop (0.49 → 0.36), but not a collapse: answers still differ across tasks and parse fine.
  - **Verdict against A15 / A16:** *must* (no collapse) and *hope* (beat the base) are both met on held-out as on validation. The trap-discrimination gap is the main open finding.
- B6. Reward gaming found (transcripts, fix, rerun) or what was searched:

  **Found: an exploitable incentive in rubric v1.0 (the abstention harbour); corrected after verification, see the note at the end of this item.**
  - **Evidence** (`results/train/v1.0-grpo-b0.001/`, `metrics.csv` + `train_samples.jsonl`, 8 saved completions per step):
    - refusals of *determinable* payslips went from 1/8 (step 0) and 0/8 (step 1) to **5/8, 6/8 and 5/8** at steps 2, 4 and 5;
    - `monitor/twin_refusal_rate` rose 0.50 → 0.625 → 0.75 → 0.625;
    - mean reward rose from −0.08 to +0.04, mostly from no longer answering traps and from refusing.
    - **Example, step 5, `gen-easy-0000005-twin`, a payable payslip:** `{"decision": "refuse", "reason_code": "NO_APPLICABLE_TABLE", "lines": {…a payslip anyway…}}`, scored **0.05**.
    - The `β = 0.04` run (`v1.0-grpo-b0.04`) showed 5/8 at its step 2 before it was stopped.
  - **Why it pays:**
    - in v1.0 a refusal of a determinable payslip kept the 0.05 format credit, a *guaranteed* 0.05;
    - the base policy's alternatives were broken JSON (0.00, 16–38 % of outputs) or a wrong answer (≈ 0.05–0.12, high variance);
    - GRPO's group-relative advantage favours the low-variance option whenever the group contains broken JSON.
    - The always-abstain *baseline* stayed under its floor (refusing every trap and twin averages out), but a policy that refuses only payslips it would otherwise botch is a sharper exploit than any hand-written baseline found. This is the brief's point (p.12): "a trained policy attacks your reward far harder than you can by hand."
  - **Honest limits:** 6 steps, 8 saved samples per step, and each step samples different tasks. It is a consistent early signal plus a verified incentive, not a long collapse curve.
  - **Fix: rubric v1.1** (`paygym/rubric.py`): a refused determinable payslip scores **0.00**, the bottom of the wrong-answer range. That is strictly below any valid-format wrong answer, and the same as a refused Tier-1 retrieval already scored in v1.0, so v1.0 was internally inconsistent.
    - Tests: `test_refusing_a_determinable_payslip_scores_like_a_wrong_answer` (now strict); baseline floors unchanged and passing.
    - Every saved eval run was re-scored under v1.1 with `paygym rescore` (saved completions, no model calls), so no leaderboard row mixes rubric versions.
  - **A second finding from the same run, a broken monitor, not gaming:** the safety stop at step 6 (`modal_net_share` 0.57 > 0.5) was a false positive. The monitor counted completions, so with mostly refusals one or two answers read as "100 % identical", and eight agreeing answers to one task looked like the modal-answer exploit. Fixed: one vote per distinct task, logged only with ≥ 2 tasks answered (`test_modal_net_monitor_counts_distinct_tasks_only`).
  - **Correction after verification (same day, A12).** The refusal counts above are **not** evidence that the policy *learned* the exploit:
    - the v1.1 rerun, where refusing pays nothing, shows the same 6/8 refusals on the same twin at step 2;
    - KL at step 2 was 0.0006, so the policy was still essentially the base model;
    - those refusals were base behaviour under the mismatched training sampler (A12).
  - **What stands:**
    - the v1.0 incentive itself (a guaranteed 0.05 for refusing a payable payslip vs 0.00 for broken JSON), shown by the rubric's arithmetic;
    - the inconsistency with Tier 1;
    - the fix (v1.1).
  - **What does not stand:** "the policy learned it in 5 steps".
  - We report the incentive as found *with the optimiser's help* (its first steps made the refusal path's payoff visible in the logs), and the learning claim as unproven.
  - **A further design finding from the v1.1 rerun:**
    - for a policy that cannot compute payslips, v1.1 still costs little for over-refusal (twin: refuse 0.00 vs broken JSON 0.00 vs wrong answer ≈ 0.05), while under-refusal on a trap costs −1;
    - the calibration reward only deters blanket refusal once the policy can earn credit by answering;
    - this is why A11's fallback (a 1.5B policy) exists.
  - **Rerun under v1.1 with A12 + A13: the exploit is learned for real** (`results/train/v1.1-grpo-b0.001`, β = 0.001, 60 steps):

    | `val_easy` step | 0 | 20 | 40 | 60 |
    |---|---|---|---|---|
    | val reward | −0.063 | **+0.081** | +0.081 | +0.081 |
    | payable payslips refused | 0/36 | **36/36** | 36/36 | 36/36 |
    | traps refused (right reason) | 0/11 | 11/11 (1) | 11/11 (1) | 11/11 (1) |
    | training entropy | 0.49 | 0.37 | 0.45 | **0.16** |

    - **The policy locked into "refuse everything" by step 20.** The validation reward rose by refusing, while competence fell to nothing, which matches the `always_abstain` baseline (0.089 on eval under v1.1). Entropy then collapsed (0.49 → 0.16) at low KL (0.02–0.03): small drift, all of it in the wrong direction.
    - **Model selection by validation reward would have picked this checkpoint** (best_step 20). This is why selection is now scored under v1.2 (A14).
    - **Response:** rubric 1.2 (A14), a symmetric compute/refuse decision. Checked offline on these exact outputs: refuse-all −0.685 under 1.2.
    - This run is evidence only; it is not scored on held-out.
- B7. Degenerate groups (`frac_reward_zero_std`) and what we would change about the taskset:
  - **Mean fraction of groups with identical rewards** (no gradient): **0.68** (β = 0.04), **0.74** (β = 0.001); G = 8, 2 prompts per step. Two thirds of each batch carried no learning signal.
  - **Why:** the 0.5B's refuse/answer decision rarely varies *within* a task's group, and exact payslips are ~0 %, so most groups are uniformly wrong. This is also why trap refusal was not learned (A11, A14).
  - **What we would change:**
    1. a stronger base policy (Qwen2.5-1.5B, inside the brief's band), so that some samples in a group get payslips right;
    2. more prompts per step (4–8), so each step has some groups with spread;
    3. curriculum: start from single-rule payslips (no ceilings, one jurisdiction) and add rules as pass rates rise;
    4. over-sample trap/twin pairs, the only tasks where the decision itself varies.
- B8. What we would do with two more days:
  1. **Qwen2.5-1.5B under rubric 1.4,** β ∈ {0.001, 0.04, 0.1}, 2 seeds each. This tests whether trap discrimination becomes learnable once some answers in a group are right, and completes the β sweep's high end.
  2. **Rerun β = 0.001 under 1.4,** to see whether the too-low β finds a fourth harbour. Every rubric fix so far closed one and exposed the next.
  3. **Put the exploits into the adversarial baselines:** "refuse everything" exists; add "broken JSON everywhere" and "invalid decision word", so future rubric changes are tested against what the optimiser found, not only what we guessed.
  4. **Group construction for GRPO:** sample trap and twin in the same step, and more prompts per step, to cut the 68–74 % degenerate groups.
  5. **Multi-turn tool RL,** the gym supports it in eval but training was single-turn only (TRADEOFFS #3).
