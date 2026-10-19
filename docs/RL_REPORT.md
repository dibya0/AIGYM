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

---

## Part B: results (filled after training from committed files)

- B1. Pilot result and preset chosen: see A11 (all presets 0 % Tier-2 exact; `easy` chosen for the most within-group reward spread).
- B2. Curves (reward, KL, entropy, completion length, per-tier pass rate): dashboard §RL; `results/train/<run>/metrics.csv`
- B3. KL sweep: what happened at β = 0.001 vs 0.04, and where we would set β and why:
- B4. Stop reasons (`stop_reason.json`) and best checkpoints (`best_checkpoint.json`):
- B5. Held-out before/after (`results/train/rl_summary.json`):
- B6. Reward gaming found (transcripts, fix, rerun) or what was searched:
- B7. Degenerate groups (`frac_reward_zero_std`) and what we would change about the taskset:
- B8. What we would do with two more days:
