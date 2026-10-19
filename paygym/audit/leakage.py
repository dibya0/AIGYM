"""Answer-leakage audit (brief p.7: "A task whose ground truth is recoverable from phrasing alone.
Write a check for this and report what it caught.").

Two checks:

1. **Literal leakage.** A ground-truth number (net pay, tax, contributions) or reason code
   appears verbatim in the prompt.
2. **Phrasing leakage.** A text-only classifier (TF-IDF n-grams + logistic regression) tries
   to predict the label (answer vs each refusal reason) from the prompt, without the rules.
   Accuracy is compared with the majority-class baseline. Some cues are legitimate *evidence*
   (a `GBP` salary really is unsupported; a 2027 period really has no table). Others would be
   template artifacts. The report lists the top-weighted n-grams per label so a human can tell
   which is which. Trap/twin pairs share their template, so a classifier that separates them
   must be using real differences.
"""

from __future__ import annotations

import re
from collections import Counter

from paygym.schema import Task

# gross_pay is excluded: for a full month with no extras it equals the stated salary (an input).
LITERAL_LINES = ("net_pay", "income_tax", "employee_social_insurance", "employee_pension")


def label(task: Task) -> str:
    gt = task.ground_truth
    return gt.reason_code if gt.kind == "refusal" else "ANSWER"


def _input_amounts(task: Task) -> set:
    amounts = set()
    for src in task.case.sources.values():
        for v in (src.monthly_salary, src.retro_pay, src.ytd_contributory_earnings):
            if v is not None:
                amounts |= {v, v * 12}
        if src.salary_change is not None:
            amounts |= {src.salary_change.monthly_salary, src.salary_change.monthly_salary * 12}
        amounts |= {a.amount for a in src.allowances or ()}
    return amounts


def literal_leaks(tasks: list[Task]) -> list[dict]:
    leaks = []
    for t in tasks:
        gt = t.ground_truth
        if gt.kind == "refusal":
            if gt.reason_code in t.prompt:
                leaks.append({"task": t.id, "leaked": gt.reason_code})
        elif gt.kind == "payslip":
            inputs = _input_amounts(t)
            for line in LITERAL_LINES:
                value = gt.lines[line]
                # Small numbers and values that equal one of the case's own input amounts
                # (e.g. a 350.00 allowance vs a capped 350 contribution) are coincidences, not leaks.
                if value < 100 or value in inputs:
                    continue
                forms = {f"{value:.2f}", f"{value:,.2f}", f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")}
                # Whole numbers only: "480,00" must not match inside "22.480,00" (a different input amount).
                hit = next((s for s in forms if re.search(r"(?<![\d.,])" + re.escape(s) + r"(?![\d])", t.prompt)), None)
                if hit:
                    leaks.append({"task": t.id, "line": line, "leaked": hit})
    return leaks


def classifier_leakage(tasks: list[Task], folds: int = 5, top_k: int = 8, seed: int = 0) -> dict:
    """Cross-validated accuracy of predicting the label from prompt text alone."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.pipeline import make_pipeline

    cases = [t for t in tasks if t.case is not None]  # Tiers 2–3: answer or refuse
    labels = [label(t) for t in cases]
    counts = Counter(labels)
    report: dict = {"n": len(cases), "labels": dict(counts)}
    if len(counts) < 2:
        report["verdict"] = "skipped: only one label present"
        return report
    usable_folds = min(folds, min(counts.values()))
    majority = max(counts.values()) / len(labels)
    report["majority_baseline"] = round(majority, 4)
    report["chance_balanced"] = round(1 / len(counts), 4)
    if usable_folds < 2:
        report["verdict"] = "skipped: too few examples of the rarest label for cross-validation"
        return report

    def model():
        # class_weight="balanced": with ~72% ANSWER labels an unweighted model just predicts the majority,
        # which says nothing about whether the rarer trap types are recognisable from wording alone.
        return make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True),
                             LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced"))

    texts = [t.prompt for t in cases]
    cv = StratifiedKFold(n_splits=usable_folds, shuffle=True, random_state=seed)
    scores = cross_val_score(model(), texts, labels, cv=cv, scoring="accuracy")
    balanced = cross_val_score(model(), texts, labels, cv=cv, scoring="balanced_accuracy")
    accuracy = float(scores.mean())
    report["cv_accuracy"] = round(accuracy, 4)
    report["cv_std"] = round(float(scores.std()), 4)
    report["lift_over_majority"] = round(accuracy - majority, 4)
    report["cv_balanced_accuracy"] = round(float(balanced.mean()), 4)
    report["lift_over_chance_balanced"] = round(float(balanced.mean()) - 1 / len(counts), 4)

    fitted = model().fit(texts, labels)
    vec, clf = fitted.named_steps["tfidfvectorizer"], fitted.named_steps["logisticregression"]
    vocab = vec.get_feature_names_out()
    top: dict[str, list[str]] = {}
    for i, cls in enumerate(clf.classes_):
        weights = clf.coef_[i] if len(clf.classes_) > 2 else (clf.coef_[0] if i == 1 else -clf.coef_[0])
        top[cls] = [str(vocab[j]) for j in weights.argsort()[::-1][:top_k]]
    report["top_ngrams_per_label"] = top
    report["verdict"] = (
        "wording predicts the label above chance: review top n-grams, they should be genuine evidence "
        "(currency codes, years, missing/conflicting fields), not template words"
        if report["lift_over_chance_balanced"] > 0.05 else "no phrasing signal beyond chance"
    )
    return report


def audit(tasks: list[Task]) -> dict:
    leaks = literal_leaks(tasks)
    return {"literal_leaks": leaks, "literal_leak_count": len(leaks), "classifier": classifier_leakage(tasks)}
