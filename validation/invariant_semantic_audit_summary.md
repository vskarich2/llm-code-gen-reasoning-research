# Invariant Semantic Audit Summary

**STRONG: 12 | WEAK: 1 | FAKE: 1**


| Invariant | Positive | Adv. Negative | Classification | Reason |
|-----------|----------|---------------|----------------|--------|
| atomicity | PASS | CAUGHT | **STRONG** | Both cases correct. Failure reason is semantically relevant: atomicity violated: |
| boundary_condition | PASS | CAUGHT | **STRONG** | Both cases correct. Failure reason is semantically relevant: boundary_condition  |
| branch_coverage | PASS | CAUGHT | **STRONG** | Both cases correct. Failure reason is semantically relevant: branch_coverage vio |
| consistency | PASS | CAUGHT | **STRONG** | Both cases correct. Failure reason is semantically relevant: consistency violate |
| field_sync | PASS | CAUGHT | **STRONG** | Both cases correct. Failure reason is semantically relevant: field_sync violated |
| idempotence | PASS | CAUGHT | **STRONG** | Both cases correct. Failure reason is semantically relevant: idempotence violate |
| independence | PASS | CAUGHT | **STRONG** | Both cases correct. Failure reason is semantically relevant: independence violat |
| lifecycle | PASS | MISSED | **WEAK** | Both cases matched expectations, but failure reason may be a proxy:  |
| no_exception | PASS | CAUGHT | **STRONG** | Both cases correct. Failure reason is semantically relevant: no_exception violat |
| no_silent_fallback | PASS | CAUGHT | **STRONG** | Both cases correct. Failure reason is semantically relevant: no_silent_fallback  |
| ordering | PASS | CAUGHT | **STRONG** | Both cases correct. Failure reason is semantically relevant: ordering violated:  |
| side_effect_count | FAIL | CAUGHT | **FAKE** | Positive case wrong: expected pass=True, got False |
| state_conservation | PASS | CAUGHT | **STRONG** | Both cases correct. Failure reason is semantically relevant: state_conservation  |
| structure_alignment | PASS | CAUGHT | **STRONG** | Both cases correct. Failure reason is semantically relevant: structure_alignment |

## Strongest

- **atomicity**: Both cases correct. Failure reason is semantically relevant: atomicity violated: invariant broken af
- **boundary_condition**: Both cases correct. Failure reason is semantically relevant: boundary_condition violated: case 0 got
- **branch_coverage**: Both cases correct. Failure reason is semantically relevant: branch_coverage violated: input 2 retur
- **consistency**: Both cases correct. Failure reason is semantically relevant: consistency violated: check returned Fa
- **field_sync**: Both cases correct. Failure reason is semantically relevant: field_sync violated: name changed but d
- **idempotence**: Both cases correct. Failure reason is semantically relevant: idempotence violated: results differ (1
- **independence**: Both cases correct. Failure reason is semantically relevant: independence violated: mutation leaked 
- **no_exception**: Both cases correct. Failure reason is semantically relevant: no_exception violated: AttributeError: 
- **no_silent_fallback**: Both cases correct. Failure reason is semantically relevant: no_silent_fallback violated: returned f
- **ordering**: Both cases correct. Failure reason is semantically relevant: ordering violated: final state check fa
- **state_conservation**: Both cases correct. Failure reason is semantically relevant: state_conservation violated: successive
- **structure_alignment**: Both cases correct. Failure reason is semantically relevant: structure_alignment violated: lengths d

## Weakest / Proxy-based

- **lifecycle**: Both cases matched expectations, but failure reason may be a proxy: 

## Fake / Must Redesign

- **side_effect_count**: Positive case wrong: expected pass=True, got False