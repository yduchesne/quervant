# PR 15I-D3-C qualification traceability

Status: **T4 NOT FROZEN**. This table records the original §6.3 inventory against executed evidence. `GAP`/`PARTIAL` rows must not be counted as passed.

| ID | Prescribed behavior | Status | Executed test/evidence |
|---|---|---|---|
| V01 | 72-lane enumeration / missing-extra-K / shuffled / N-class count | GAP | No enumeration-mutation test; series tests cover fixture validity only |
| V02 | 72-lane enumeration / missing-extra-K / shuffled / N-class count | GAP | No enumeration-mutation test; series tests cover fixture validity only |
| V03 | 72-lane enumeration / missing-extra-K / shuffled / N-class count | GAP | No enumeration-mutation test; series tests cover fixture validity only |
| V04 | 72-lane enumeration / missing-extra-K / shuffled / N-class count | GAP | No enumeration-mutation test; series tests cover fixture validity only |
| V05 | 32-slot schedule / wrong arm / duplicate / missing slot | GAP | Verifier schedule exists; no direct adversarial test |
| V06 | 32-slot schedule / wrong arm / duplicate / missing slot | GAP | Verifier schedule exists; no direct adversarial test |
| V07 | 32-slot schedule / wrong arm / duplicate / missing slot | GAP | Verifier schedule exists; no direct adversarial test |
| V08 | 32-slot schedule / wrong arm / duplicate / missing slot | GAP | Verifier schedule exists; no direct adversarial test |
| V09 | 20/19/21 samples / bool-nonpositive / wrong ids or total | PARTIAL | test_verify.test_v08_sample_count (19 samples); oracle test_v09; 21/bool GAP |
| V10 | 20/19/21 samples / bool-nonpositive / wrong ids or total | PARTIAL | test_verify.test_v08_sample_count (19 samples); oracle test_v09; 21/bool GAP |
| V11 | 20/19/21 samples / bool-nonpositive / wrong ids or total | PARTIAL | test_verify.test_v08_sample_count (19 samples); oracle test_v09; 21/bool GAP |
| V12 | 20/19/21 samples / bool-nonpositive / wrong ids or total | PARTIAL | test_verify.test_v08_sample_count (19 samples); oracle test_v09; 21/bool GAP |
| V13 | A/A equality / compile paths / B feature / L-P-H binary | PARTIAL | test_verify.test_v03/v05; A/A equality in test_v01 series |
| V14 | A/A equality / compile paths / B feature / L-P-H binary | PARTIAL | test_verify.test_v03/v05; A/A equality in test_v01 series |
| V15 | A/A equality / compile paths / B feature / L-P-H binary | PARTIAL | test_verify.test_v03/v05; A/A equality in test_v01 series |
| V16 | A/A equality / compile paths / B feature / L-P-H binary | PARTIAL | test_verify.test_v03/v05; A/A equality in test_v01 series |
| V17 | correct/missing/duplicate/wrong marker / profile / BASE env | PARTIAL | replay wrong-marker; profile/BASE-env GAP |
| V18 | correct/missing/duplicate/wrong marker / profile / BASE env | PARTIAL | replay wrong-marker; profile/BASE-env GAP |
| V19 | correct/missing/duplicate/wrong marker / profile / BASE env | PARTIAL | replay wrong-marker; profile/BASE-env GAP |
| V20 | correct/missing/duplicate/wrong marker / profile / BASE env | PARTIAL | replay wrong-marker; profile/BASE-env GAP |
| V21 | correct/missing/duplicate/wrong marker / profile / BASE env | PARTIAL | replay wrong-marker; profile/BASE-env GAP |
| V22 | READY / busy / steal / missing counter / altered ticks | PARTIAL | test_verify.test_v06; altered tick GAP |
| V23 | READY / busy / steal / missing counter / altered ticks | PARTIAL | test_verify.test_v06; altered tick GAP |
| V24 | READY / busy / steal / missing counter / altered ticks | PARTIAL | test_verify.test_v06; altered tick GAP |
| V25 | READY / busy / steal / missing counter / altered ticks | PARTIAL | test_verify.test_v06; altered tick GAP |
| V26 | READY / busy / steal / missing counter / altered ticks | PARTIAL | test_verify.test_v06; altered tick GAP |
| V27 | 1.25/1.50 cap inclusive / over cap / malformed pair | GAP | Drift boundary verifier not directly tested |
| V28 | 1.25/1.50 cap inclusive / over cap / malformed pair | GAP | Drift boundary verifier not directly tested |
| V29 | 1.25/1.50 cap inclusive / over cap / malformed pair | GAP | Drift boundary verifier not directly tested |
| V30 | 1.25/1.50 cap inclusive / over cap / malformed pair | GAP | Drift boundary verifier not directly tested |
| V31 | K100 sentinel / index digest / corpus lock / query field | PARTIAL | replay index-digest; sentinel/corpus/query-field GAP |
| V32 | K100 sentinel / index digest / corpus lock / query field | PARTIAL | replay index-digest; sentinel/corpus/query-field GAP |
| V33 | K100 sentinel / index digest / corpus lock / query field | PARTIAL | replay index-digest; sentinel/corpus/query-field GAP |
| V34 | K100 sentinel / index digest / corpus lock / query field | PARTIAL | replay index-digest; sentinel/corpus/query-field GAP |
| V35 | compile-source root / symlink / nested / sealed dir | GAP | Only inventory baseline, no adversarial compile-source test |
| V36 | compile-source root / symlink / nested / sealed dir | GAP | Only inventory baseline, no adversarial compile-source test |
| V37 | compile-source root / symlink / nested / sealed dir | GAP | Only inventory baseline, no adversarial compile-source test |
| V38 | compile-source root / symlink / nested / sealed dir | GAP | Only inventory baseline, no adversarial compile-source test |
| V39 | hidden file / missing member / symlink / traversal / SHA | PARTIAL | test_run V41-V46: digest/member/extra/missing/substituted; traversal/symlink GAP |
| V40 | hidden file / missing member / symlink / traversal / SHA | PARTIAL | test_run V41-V46: digest/member/extra/missing/substituted; traversal/symlink GAP |
| V41 | hidden file / missing member / symlink / traversal / SHA | PARTIAL | test_run V41-V46: digest/member/extra/missing/substituted; traversal/symlink GAP |
| V42 | hidden file / missing member / symlink / traversal / SHA | PARTIAL | test_run V41-V46: digest/member/extra/missing/substituted; traversal/symlink GAP |
| V43 | hidden file / missing member / symlink / traversal / SHA | PARTIAL | test_run V41-V46: digest/member/extra/missing/substituted; traversal/symlink GAP |
| V44 | missing control / wrong control SHA / 02 before 01 / attempt 03 | PARTIAL | test_verify V02/V10; 02-before-01 and 03 GAP |
| V45 | missing control / wrong control SHA / 02 before 01 / attempt 03 | PARTIAL | test_verify V02/V10; 02-before-01 and 03 GAP |
| V46 | missing control / wrong control SHA / 02 before 01 / attempt 03 | PARTIAL | test_verify V02/V10; 02-before-01 and 03 GAP |
| V47 | missing control / wrong control SHA / 02 before 01 / attempt 03 | PARTIAL | test_verify V02/V10; 02-before-01 and 03 GAP |
| V48 | recomputed median/ratio / wrong sign / swapped A-L / forged summary | PARTIAL | replay summary and sample-median; swapped A-L GAP |
| V49 | recomputed median/ratio / wrong sign / swapped A-L / forged summary | PARTIAL | replay summary and sample-median; swapped A-L GAP |
| V50 | recomputed median/ratio / wrong sign / swapped A-L / forged summary | PARTIAL | replay summary and sample-median; swapped A-L GAP |
| V51 | recomputed median/ratio / wrong sign / swapped A-L / forged summary | PARTIAL | replay summary and sample-median; swapped A-L GAP |
| V52 | no mode env / mode env into build / different host CPU pair | PARTIAL | test_v04 host identity; env/build GAP |
| V53 | no mode env / mode env into build / different host CPU pair | PARTIAL | test_v04 host identity; env/build GAP |
| V54 | no mode env / mode env into build / different host CPU pair | PARTIAL | test_v04 host identity; env/build GAP |
| V55 | publish synthetic / without verification / second publish | PARTIAL | test_run V48-V50 status gate and synthetic refusal; second-publish GAP |
| V56 | publish synthetic / without verification / second publish | PARTIAL | test_run V48-V50 status gate and synthetic refusal; second-publish GAP |
| V57 | publish synthetic / without verification / second publish | PARTIAL | test_run V48-V50 status gate and synthetic refusal; second-publish GAP |
| V58 | broken historical SHA / old tooling diff / protocol drift | PARTIAL | protocol-sha replay; historical diffs command; broken-SHA GAP |
| V59 | broken historical SHA / old tooling diff / protocol drift | PARTIAL | protocol-sha replay; historical diffs command; broken-SHA GAP |
| V60 | broken historical SHA / old tooling diff / protocol drift | PARTIAL | protocol-sha replay; historical diffs command; broken-SHA GAP |
| RH01 | qualified synthetic A/A control | PASS | replay 3 positive cases |
| RH02 | qualified synthetic four-arm 01 | PASS | replay 3 positive cases |
| RH03 | independently verified synthetic four-arm 02 + pure policy | PASS | replay + policy PM12 |
| RH04 | safe rehearsal publication refusal | PASS | replay publish_guard; test_replay RH01/RH02 |
| RH05 | wrong mode marker | PASS | replay wrong-marker V_MODE |
| RH06 | wrong profile | GAP | No rehearsal mutation |
| RH07 | missing one lane | PASS | replay lane-count V_SLOT |
| RH08 | wrong K/term/oracle | PASS | replay oracle V_ORACLE |
| RH09 | tamper sealed raw tick | PARTIAL | tampered-slot V_SEAL; tick semantics not direct |
| RH10 | rescan wrong inventory | PASS | replay extra-file V_INVENTORY |
| RH11 | substitute BASE binary in P arm | PASS | replay binary-provenance V_BINARY |
| RH12 | change slot order | GAP | No slot-order mutation |
| RH13 | duplicate 02 | GAP | No duplicate campaign mutation |
| RH14 | policy with only 01 | GAP | No series-truncation policy test |
| RH15 | mark A/A unqualified | GAP | No unqualified status mutation |
| RH16 | historical hashes unchanged, no archive | PASS | T0-T3 diffs empty; rehearsal no archive |
| M01 | deterministic seed 0, nine K, four lengths, five traces | PARTIAL | test_micro M01 grid; seed not explicit |
| M02 | duplicate oracle | GAP | No micro duplicate-oracle test |
| M03 | evicted oracle | GAP | No micro evicted-oracle test |
| M04 | collision oracle | GAP | No micro collision-oracle test |
| M05 | timer negative/zero failure | GAP | No timer-failure test |
| M06 | five distinct rounds | PARTIAL | test_micro M05 round count; distinctness not asserted |
| M07 | exact-profile selection | PARTIAL | test_micro M01/M02; tie/none GAP |
| M08 | memory guards | PASS | test_micro M02/M08; test_policy PM01-PM08 |
| M09 | no fake resident-size claim | GAP | Not separately asserted |
| M10 | reject synthetic micro in official E2E | GAP | Not implemented |
| P01 | both valid qualified campaigns | PARTIAL | evaluate_arm/PM12 synthetic; official CLI requires series |
| P02 | one missing | GAP | No series truncation test |
| P03 | one drift-blocked | GAP | No drift-blocked campaign test |
| P04 | different source/host | GAP | No policy source/host test |
| P05 | P-only eligible | PASS | test_p13 |
| P06 | H-only eligible | PASS | test_p14 |
| P07 | both eligible, P tie <3% | PASS | test_p15 |
| P08 | exact 3% boundary non-tie | PASS | test_p16 |
| P09 | no eligible | PASS | test_p17 |
| P10 | false-positive/memory exclusion | PASS | test_p18 |
| P11 | one 100K lane fails 3% | PASS | test_p19 |
| P12 | 10K guard fails 10% | PASS | test_p20 |
| P13 | single block violates cap | PASS | test_p21 |
| P14 | S/L attribution fails | PASS | test_p22 |
| P15 | NaN/zero ratio | PASS | test_p23 and PM tests |
| P16 | unmeasured K fallback | GAP | No missing-K policy test |
| P17 | swapped arm | GAP | No swapped-arm policy test |
| P18 | missing eight-lane input | GAP | No missing-lane policy test |
| P19 | forged source digest | GAP | No forged-source policy test |
| P20 | archived-run identity mismatch | GAP | No archive identity policy test |
| P21 | invalid oracle | GAP | No invalid-oracle policy test |
| P22 | NO_SUPPORTED_POLICY success / selected-profile provenance | PARTIAL | choose_candidate no-candidate PASS; CLI NO_SUPPORTED not synthesized |
