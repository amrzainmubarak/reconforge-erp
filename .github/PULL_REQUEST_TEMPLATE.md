## Summary

Describe the control, report, export profile, or code path changed.

## Validation

- [ ] `python -m ruff check .`
- [ ] `python -m mypy reconforge`
- [ ] `python -m pytest`
- [ ] `python -m bandit -q -r reconforge` when security-sensitive paths are touched
- [ ] Demo command exercised when relevant

## Data Safety

- [ ] No real customer, supplier, employee, vehicle, or financial data is included
- [ ] Sample data is synthetic or anonymized
- [ ] Local-first behavior is preserved; no cloud upload, SaaS flow, or live ERP credential handling is introduced

## Claim Boundaries

- [ ] No customer/adoption claims are added unless documented
- [ ] No audit opinion, legal, tax, compliance certification, or enterprise production-readiness claims are added
- [ ] No direct ERP connector or Docker runtime verification claims are added unless verified

## Maintainer Notes

List migration notes, config changes, or report output changes.
