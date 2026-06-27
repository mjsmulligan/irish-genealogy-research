# ⚠️ Phase 3 Critical Regression Analysis

**Date**: 2026-06-27  
**Status**: 🔴 REGRESSION DETECTED

---

## The Problem

Phase 3 v1.2 has **DECREASED linkage from 26% to ~9%** - a 66% regression.

| Metric | v1.1 | v1.2 | Change |
|--------|------|------|--------|
| Linkage | 26.0% | 9% | **-17pp** ⚠️ |
| Persons | 824 | 280 | **-544** ⚠️ |
| Avg Score | 0.50+ | 0.459 | **-0.04** ⚠️ |

---

## Critical Findings

**Real Measurements from Clean Test Run:**
- Recorded persons: 3,167 (full fixtures loaded)
- Linked persons: 280 (9% linkage)
- 52% of similarity pairs score <0.45 (too weak)

**v1.2 Score Distribution:**
- ≥0.65: 50 pairs (9.3%)
- 0.50-0.65: 124 pairs (23.2%)
- 0.45-0.50: 83 pairs (15.5%)
- <0.45: 278 pairs (52.0%)

---

## Root Cause Unknown

Possibilities:
1. Role comparison too restrictive
2. NullLevel broken for missing roles
3. Plausible transitions not working
4. EM weights miscalibrated
5. Role data quality issues

---

## Recommendation

❌ **DO NOT DEPLOY v1.2**

Immediate actions:
1. Investigate root cause
2. Fix regression
3. Retest for 26% linkage
4. Then redeploy

---

## Deployment Status

**BLOCKED**: Phase 3 requires fixes before production use.

