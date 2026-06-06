# Buyer FAQ

This FAQ helps buyers, pilot teams, consultants, and reviewers evaluate ReconForge ERP honestly. It is not a sales contract, compliance claim, audit opinion, or production readiness statement.

## What Is ReconForge ERP?

ReconForge ERP is an open-source, local-first, export-based reconciliation and finance controls toolkit. It reads local CSV/XLSX exports, runs deterministic reconciliation and rule checks, and writes local reports, review state, evidence folders, and client handoff artifacts.

## What Is It Not?

- Not a SaaS platform.
- Not a hosted close-management suite.
- Not a direct ERP connector.
- Not an ERP writeback, sync, posting, or credential-handling system.
- Not a legal-signature or non-repudiation product.
- Not an audit firm, audit opinion workflow, or compliance certification service.
- Not a replacement for enterprise close, GRC, ERP, or audit platforms.

## How Does The Local-First Model Work?

Users export data from their ERP or operational systems, store it in local folders, run ReconForge commands locally, and review generated local outputs. Core workflows do not require cloud upload, telemetry, paid APIs, hosted storage, or a ReconForge account.

## Does ReconForge Have Direct ERP Connectors?

No. Current ERP profiles are export-based mapping aids. They help users map local CSV/XLSX exports into ReconForge's canonical files. They are not live connectors, certified vendor integrations, or sync workflows.

## Is ReconForge A SaaS Product?

No. ReconForge is currently local-first open-source tooling. Any future hosted or self-hosted service idea would need separate design, threat modeling, documentation, and implementation before it could be claimed.

## Does ReconForge Provide Audit Opinions Or Compliance Certification?

No. ReconForge can support local evidence preparation, exception review, checksum integrity aids, and workflow metadata. It does not issue audit opinions, certify compliance, provide legal sign-off, or guarantee regulatory outcomes.

## How Does It Compare Directionally To Enterprise Close Or Reconciliation Tools?

Enterprise close and reconciliation platforms often provide deep workflow orchestration, hosted collaboration, direct integrations, centralized administration, contractual support, and mature governance programs. ReconForge is intentionally lighter: it focuses on inspectable local workflows from exports, transparent rule packs, generated evidence folders, and pilot-friendly review artifacts.

ReconForge may help teams evaluate export-based control gaps before adopting or configuring larger platforms. It should not be described as feature-parity, a replacement, or a certified alternative to enterprise suites.

## Who Is It For?

- Finance controllers and accountants reviewing export-based reconciliations.
- Internal audit teams preparing local evidence and exception registers.
- ERP consultants checking mapping, valuation, WIP, and operational-control exports.
- Odoo, SAP, ERPNext, Dynamics, NetSuite, and Oracle users working from local exports.
- Maintainers and technical evaluators reviewing open-source finance-control workflows.

## Good Pilot Fit

- A defined local export set is available.
- The buyer can run Python tooling locally.
- The team wants transparent, deterministic checks and reviewable outputs.
- The pilot scope is narrow: one ERP/export pattern, one or two periods, and selected workflows.
- The data owner can approve local data handling rules.
- The team accepts that findings are review-preparation outputs, not audit conclusions.

## Poor Pilot Fit

- The buyer requires SaaS hosting, vendor-managed storage, or managed user administration today.
- The buyer requires direct ERP API connectivity or automated writeback today.
- The buyer needs formal SOC, ISO, SOX, GDPR, tax, or audit certification from the tool.
- The buyer expects a quantified ROI promise or customer-proven adoption evidence.
- The buyer cannot provide sanitized, anonymized, synthetic, or locally approved exports.
- The buyer needs a vendor replacement for enterprise close, GRC, ERP, or audit platforms.

## What Should Buyers Ask During Evaluation?

- Which exact workflows are implemented and tested?
- Which workflows are foundation-stage or roadmap only?
- What data will stay local, and who can access generated outputs?
- Which claims are explicitly not made?
- Which quality, security, and release checks passed for the version being evaluated?
- What support is best-effort open source versus draft paid service packaging?
