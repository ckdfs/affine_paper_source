# MZM manuscript review and revision log

Date: 2026-07-10
Target: JLT/Q1 photonics journal
Baseline commit: `b44661c`

## Round 1 editorial result

The five-reviewer panel returned one Reject and four Major Revision decisions.
The common reason was not the affine identity itself, but a mismatch between the
claimed end-to-end self-calibrating experiment and the recorded bench procedure.
The headline controller used `phase-ref` regression, the recalibration code used
a 121-point full-period sweep, RF states were recalibrated separately, and the
reported experiments had no independent repetitions or equal-information strong
baseline.

## Revision roadmap

### P1: claim and method integrity

- [x] Add the full-rank condition for full-cycle phase inversion.
- [x] Generalize the DC gauge equation to arbitrary periodic pilot waveforms.
- [x] Separate condition number from absolute weak-axis noise gain.
- [x] State the orthogonal/gauge-rotation blind spot of the circle residual.
- [x] Rename the implemented control update as an incremental integral update.
- [x] Replace the claimed micro-arc bench recalibration with the actual full-period scan.
- [x] Disclose that the hardware headline uses phase-reference regression and that
      the ellipse-only path is an offline diagnostic.
- [x] Report both available lock-error truth conventions (246 and 342 mrad) and
      limit the H1 result to a qualitative branch-loss comparison.
- [x] Limit the 3 h, drift-step, and RF results to their actual single-run/static-state scope.

### P2: field positioning and evidence

- [x] Add the 2014, 2018, 2022, 2023, and 2025 nearest-neighbor literature.
- [x] Add a capability/evidence comparison table and stop treating all prior
      arbitrary-point methods as single-amplitude readers.
- [x] State explicitly that the H1 baseline is not a state-of-the-art benchmark.
- [x] Add a data/code availability statement and a reproducibility-gap disclosure.
- [x] Add interleaved five-fold sensitivity analysis for both phase-reference and
      ellipse calibration paths, while identifying the shared-scan limitation.
- [x] Add a favorable equal-information diagonal 2-D baseline in simulation.
- [x] Add a processed-data manifest, provenance notes, checksums, and a read-only
      reanalysis script.
- [ ] Run the ellipse+DC-gauge controller in hardware with no phase labels.
- [ ] Add an equal-information published arbitrary-point baseline.
- [ ] Repeat independent calibration/lock runs with randomized order and uncertainty.
- [ ] Test fixed-calibration RF switching and record application-level RF metrics.

### P3: artifact quality

- [x] Fix CJK embedding so Poppler renders and maps all Chinese text.
- [x] Increase the experimental composite-figure label and legend sizes.
- [x] Compile and visually inspect the 10-page PDF.
- [x] Pass the manuscript number, citation, figure, and experiment contracts.
- [ ] Replace author/date/funding placeholders with final submission metadata.

## Evidence boundary after Round 1 (historical; superseded by Round 6)

The revised paper is now internally honest and reproducible from the committed
processed data. It is not yet an acceptance-grade experimental validation of the
ellipse self-calibrating controller. Closing that gap requires new bench runs;
it cannot be repaired by prose or reanalysis of the existing lock data.

## Round 2 result

The second review round no longer found a fatal mathematical inconsistency or a
misrepresentation of the recorded bench procedure.  The remaining Major
Revision decisions converge on evidence that does not exist in the current
dataset: a label-free ellipse+DC-gauge hardware loop, an equal-information
hardware baseline, independent randomized repeats, and final submission
metadata/English preparation.  The diagonal 2-D simulation baseline and
same-scan cross-validation improve diagnosis but do not satisfy those hardware
requirements.

## Round 3 acceptance gate (historical; superseded by Round 6)

Three focused reviewers independently returned Major Revision.  They found no
remaining fatal mathematical inconsistency, procedure misrepresentation,
number-contract failure, or PDF rendering defect.  The manuscript was therefore
repositioned explicitly as an exact structural/identifiability framework with a
supervised hardware feasibility study: the contribution list no longer presents
the phase-reference experiment as end-to-end validation of the label-free path,
the simulation advantage is labeled a model stress test, and full-cycle
identifiability is stated as a necessary-and-sufficient proposition.  The table
label for kappa(A) was also changed from a noise-floor claim to observation
anisotropy.

The acceptance gate remains closed for reasons that cannot be repaired from the
current dataset: no label-free ellipse+DC-gauge hardware loop, no
equal-information hardware baseline, and no independent randomized repeats.
English conversion, author/funding metadata, and acquisition-package metadata
also require author input or missing artifacts.  Stopping textual revision at
this boundary prevents unsupported claims or fabricated evidence.

## Round 4: acceptance experiment readiness

A new Zotero audit found the directly relevant 2026 DLA2C paper (DOI
`10.3788/COL202624.011201`).  The manuscript now positions it as a complementary
data-driven arbitrary-point method: DLA2C avoids independent H2 detection using
multidimensional features, DNN coarse positioning and PSO refinement, whereas
the present method uses explicit H1/H2 affine identifiability and closed-form
inference.  No cross-paper accuracy superiority is claimed.

The previously missing experiment is now preregistered in
`reviews/mzm_acceptance_experiment_protocol.md`.  `measure_bench.py acceptance`
implements fresh label-free calibration blocks, balanced controller/start-side
order, opposite-side initial conditions, a calibrated H1/H2 equal-information
baseline, immutable per-session artifacts and checksums.  The read-only
`analyze_mzm_acceptance.py` treats calibration blocks as the independent unit and
performs session/repetition/target clustered bootstrap analysis.  Two simulated
sessions with six calibration blocks passed every controller/tooling gate, while
the deliberately unavailable independent optical truth kept
the then-named `paper_acceptance_ready=false`.  These simulations validate orchestration only;
they are excluded from the paper and do not replace the required live bench runs.

## Round 5: adversarial self-verification

The final main-agent re-review found and corrected two evidence-pipeline defects.
First, an interrupted repetition previously stopped acquisition and could later
be lost through complete-case aggregation; every attempted block now receives a
manifest, failed blocks remain immutable, and any incomplete block forces the
controller-evidence gate false.  Second, the analysis previously treated the
existence of `truth_prepost.npz` plus a channel identifier as independent truth.
Because isolated-channel acquisition, temporal interpolation and blind scoring
are not yet implemented, file presence is now explicitly insufficient and the
paper-acceptance gate is hard-coded false.

The bibliography was also reordered to match first citation, and a final build,
number/citation/experiment reconciliation, PDF text extraction and visual page
inspection found no new blocking manuscript defect.  The current paper is
therefore internally honest and mechanically submission-clean, but it is not an
acceptance-ready evidence package: that status still requires live label-free
runs in at least two sessions, six complete calibration blocks, a genuinely
isolated optical truth path with frozen blind scoring, and real author/funding/
submission metadata.  These items require new physical measurements or author
input and cannot be resolved by further textual iteration.

## Round 6: field-norm recalibration of evidence requirements

A paper-by-paper audit of Wang--Kowalczyk (three representative points), Tao
et al. (four points), Li et al. (several representative bias settings),
Svarny--Chladek (quadrature only), DLA2C (Q/NULL long runs), and Weller et al.
(NULL/quadrature plus disturbances) showed that the earlier two-session,
six-block, full-grid, isolated-truth gate exceeded normal experimental practice
for MZM bias-control papers.  It is a useful optional robustness protocol, not a
condition for submitting or accepting the present scoped hardware demonstration.

The current manuscript already reports a broader single-device test matrix than
many close precedents: 16 full-cycle targets, an H1 comparison, pilot-depth
conditioning, a 3 h run, residual-triggered recalibration, and multiple RF-load
states.  The paper does not claim global capture, cross-device failure rates,
hardware-isolated non-diagonal gain, or end-to-end label-free control.  Therefore
opposite-side starts, a calibrated H1/H2 hardware ablation, cross-day repeats and
a second optical truth path are optional extensions rather than missing evidence.

Round 6 supersedes the "acceptance gate" interpretation in Rounds 3--5.  The
legacy `acceptance` script remains available as an enhanced-evidence stress test,
and its output key is renamed `enhanced_evidence_ready` so that tooling cannot be
mistaken for a journal decision rule.

## Round 7: post-recalibration independent re-review

Three independent reviewers examined commit `061e811`.  The methodology and
domain reviewers returned Minor Revision / near Accept and agreed that no new
sessions, initial-condition sweeps, second optical path or additional controller
were required.  The Devil's Advocate identified a narrower causal-attribution
risk: the hardware text had not quantified whether non-diagonal correction, as
opposed to merely using two channels, mattered in the measured chain.

The existing calibration scan closes that question without new acquisition.  A
five-fold interleaved, equal-information ablation now fits the same supervised
training points and center, then compares the full inverse with an inverse formed
after zeroing `A12/A21`.  Held-out RMS is 53.7 mrad for the full decoder and
60.3 mrad for the diagonal decoder; the mean off-diagonal Frobenius-norm
fraction is only 0.85%.
The paper therefore states the correct result: this bench chain is nearly
diagonal and does not demonstrate a large cross-correction gain, while the
strong-mixing simulation isolates the mechanism when those terms are larger.

Round 7 also fixes the calibration pseudocode's previously undefined/tautological
model self-check, replacing it with pullback-radial and DC-gauge residual checks;
states scan coverage/stationarity conditions; records the measured loop gain,
iterations, averaging and steady-state definition; labels target points as
coverage samples rather than independent repetitions; and reports the measured
errors in degrees alongside mrad.  The final editorial synthesis is Accept/Minor
for scientific content, with author metadata and venue-specific English
preparation remaining as submission-package work rather than experimental gaps.

## Round 8: final adversarial closure

The final EIC and Devil's Advocate reviews isolated three residual risks: the
scope of the arbitrary-linear-chain theorem, the uniqueness of the contribution
relative to generic ellipse correction, and whether the 16-point hardware data
show target response rather than merely bounded error.  The theorem now absorbs
the deterministic response of an arbitrary linear functional to constant optical
power into `b`, treats a stable chain with memory as a settled composite
functional, and limits the scalar-readout minimality claim to memoryless
instantaneous static observations.  The introduction now states the specific
novelty as the necessary-and-sufficient full-cycle identifiability condition:
apart from the center, the ellipse determines only `AA^T`, so the `O(2)` gauge
must be fixed separately.

No new acquisition was needed to close the target-response question.  Reanalysis
of the saved 16-point sweep unwraps measured phase in target order.  Local-DMM
and wide-scan truth maps give slopes 1.052/1.039, R2 values 0.986/0.980, 14 of 15
adjacent steps in the expected direction, and 16 of 16 absolute errors below
pi/4.  The paper labels the latter as a descriptive magnitude, not a success
threshold.  It also maps every strong-mixing simulation parameter to a physical
nonideality and states that the stress case is stronger than the measured,
nearly diagonal chain.

After these changes, the methodology reviewer returned Accept, the EIC returned
Accept for scientific content, and the second Devil's Advocate review reduced
all former Major concerns to Minor/editorial judgment.  All reviewers agreed
that no second controller, initial-condition sweep, cross-day repetition or
additional target points are required for the paper's scoped claims.
