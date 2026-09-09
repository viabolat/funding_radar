# Funding Radar — Commercial Contracts & Deal Structuring Guide

## Executive Summary

This document provides a framework for structuring enterprise sales, custom licensing deals, and flat-fee commercial contracts for **Funding Radar**. 

Based on software development rates in the Cluj-Napoca tech ecosystem (€40–€80+/hour), a custom build of this multi-tenant funding intelligence platform carries a market replacement value of **€15,000 to €25,000**. 

When selling to anchor clients, grant consultancies, or institutions via one-time flat fees (such as a **€7,500 anchor deal**), proper contract structuring is critical to capture immediate cash flow while preventing long-term maintenance liabilities ("scraper rot").

---

## 1. Market Valuation Benchmark (Cluj Ecosystem)

A custom agency implementation of Funding Radar involves five distinct technical components. The valuation benchmark below reflects standard Cluj agency rates (~€60/hour average):

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    DEVELOPMENT COST BENCHMARK (CLUJ)                        │
├────────────────────────────────────────┬───────────────────┬────────────────┤
│ Component                              │ Estimated Hours   │ Agency Value   │
├────────────────────────────────────────┼───────────────────┼────────────────┤
│ 1. Multi-Source Scraper Resilience     │ 60 – 80 hrs       │ €3,600 – €4,800│
│    (MIPE, ADR Nord-Vest, EU SEDIA)     │                   │                │
│ 2. AI Document Parsing Engine          │ 50 – 70 hrs       │ €3,000 – €4,200│
│    (Ghidul Solicitantului PDF parser)  │                   │                │
│ 3. Multi-Tenant DB & RLS Security      │ 40 – 60 hrs       │ €2,400 – €3,600│
│    (Supabase Postgres, Auth, RPCs)     │                   │                │
│ 4. React Dashboard & Triage System     │ 60 – 80 hrs       │ €3,600 – €4,800│
│    (Filters, team workflow, multi-role)│                   │                │
│ 5. Notification Engine & DevOps        │ 40 – 50 hrs       │ €2,400 – €3,000│
│    (Resend email, CI/CD, idempotency)  │                   │                │
├────────────────────────────────────────┼───────────────────┼────────────────┤
│ TOTAL DIRECT DEVELOPMENT               │ 250 – 340 hrs     │ €15,000–€20,400│
│ Project Management & QA (+20%)         │ 50 – 70 hrs       │ €3,000 – €4,600│
├────────────────────────────────────────┼───────────────────┼────────────────┤
│ FULL MARKET REPLACEMENT VALUE          │ 300 – 410 hrs     │ €18,000–€25,000│
└────────────────────────────────────────┴───────────────────┴────────────────┘
```

---

## 2. Strategic Audit: The €7,500 One-Time Flat Fee

Offering a **€7,500 flat fee** represents a **60%–70% discount** compared to a full custom build. This is an effective B2B sales mechanism for securing early anchor clients.

### Advantages
- **Immediate Capital**: Funds core server infrastructure, API budgets, and feature development without dilution.
- **Low Procurement Friction**: €7,500 falls within standard discretionary or innovation budget caps for mid-sized organizations without requiring complex corporate procurement loops.
- **Social Proof**: Secures a reference customer case study in the Cluj/Transylvania market.

### Operational Risks & Failure Modes

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            OPERATIONAL RISKS                                │
├──────────────────────────┬──────────────────────────────────────────────────┤
│ Risk Factor              │ Operational Consequence                          │
├──────────────────────────┼──────────────────────────────────────────────────┤
│ 1. Scraper Rot           │ Government portals (MIPE, ADRs, AFM) redesign    │
│                          │ HTML structures, breaking parsers periodically.   │
│ 2. API & Token Inflation │ Running AI LLM extraction on 80-page PDFs incurs │
│                          │ recurring monthly usage costs (OpenAI/Anthropic).│
│ 3. Capped Upside         │ High-revenue consultancies capture unlimited      │
│                          │ client value while paying zero recurring SaaS fees│
└──────────────────────────┴──────────────────────────────────────────────────┘
```

---

## 3. Recommended Contract Options & Deal Structures

To capture the benefits of upfront cash while eliminating maintenance risks, use one of the following three contract models:

### Model A: "Hybrid Upfront Setup + Recurring Managed SLA" (RECOMMENDED)
- **Single Organization (NGO / SME)**: **€7,500** Upfront Setup + **€199 / month** (or **€1,990 / year**) starting in Month 13.
- **Grant Consultancy (Multi-Client)**: **€15,000** Upfront Setup + **€399 / month** (or **€3,990 / year**) starting in Month 13 (includes multi-tenant client portfolio management up to 25 clients).
- **Covers**: Scraper maintenance when government sites change layout, AI PDF parsing API tokens, bug fixes, server infrastructure, and new core feature updates.

### Model B: "Perpetual License with 12-Month Support Cap"
- **Upfront Fee**: **€7,500** (Single Org) or **€15,000** (Consultancy) flat fee for perpetual use of the software version at delivery.
- **Support Term**: Includes 12 months of software updates and scraper maintenance.
- **Post-12-Month Terms**: Scraper maintenance and software updates after Month 12 require an annual maintenance renewal contract (**€1,500 – €3,500 / year**). If unrenewed, the client retains the software as-is, but scraper repair is billed at an hourly rate (€60–€80/hr) or pay-per-fix ticket (€300–€500/fix).

### Model C: "Enterprise White-Label Buyout"
- **Upfront Fee**: **€18,000 – €25,000** (Full custom enterprise license for large university networks or corporations).
- **Scope**: Dedicated isolated deployment, custom municipal scraper additions, full team training, and 24 months of priority support.
- **SLA**: **€499 / month** starting in Year 2 for hosting, infrastructure management, and multi-source maintenance.

---

## 4. Essential Contract Clauses for Funding Radar Deals

Every commercial agreement for Funding Radar must include these protective clauses:

### 1. Scope of Maintenance & Website Layout Changes ("Scraper Rot Clause")
> *"The Maintenance SLA covers repairs to existing data collection pipelines (scrapers) resulting from standard formatting modifications by public funding portals (MIPE, ADRs, EU SEDIA). The addition of new, uncontracted third-party funding websites or municipal portals shall be classified as Custom Development and quoted separately."*

### 2. Fair Use & AI API Token Allocations
> *"The contract includes an allocation of up to 500 AI-assisted document analyses (Ghidul Solicitantului extractions) per calendar month. Document processing exceeding this volume will be billed at €0.15 per additional parsed page or billed against the Client's dedicated API keys."*

### 3. Intellectual Property & Non-Exclusive License
> *"The Client is granted a non-exclusive, non-transferable license to use the Funding Radar platform for internal business operations and client advisory services. All underlying source code, database architectures, AI prompt libraries, and algorithm trade secrets remain the sole intellectual property of the Provider."*

### 4. Third-Party Data Disclaimer
> *"Funding Radar aggregates information from public Romanian and European Union funding sources. The Provider does not guarantee the accuracy, completeness, or timeliness of third-party public notices and shall not be held liable for missed application deadlines or rejected grant submissions."*

---

## 5. Negotiation & Sales Playbook

When presenting a **€7,500 offer** to a client in Cluj or Romania, structure the conversation using this script framework:

1. **Establish the Alternative Cost**: 
   > *"If you were to contract a local software agency in Cluj to build a system that scrapes MIPE, parses 80-page PDF guidelines with AI, and alerts your team in real time, you’d be looking at €18,000 to €25,000 in custom development costs plus 4 months of build time."*
2. **Present the Anchor Value**: 
   > *"We are offering a complete, market-tested platform deployed specifically for your team for a flat fee of €7,500. You get full enterprise functionality immediately without the 4-month development risk."*
3. **Secure the Recurring SLA**: 
   > *"To ensure your scrapers never break when MIPE or ADR updates their portals, the first 12 months of maintenance and AI processing are included. After Year 1, ongoing maintenance and updates are covered under a modest €199/month SLA."*

---

## 6. Anchor Client Rollout & Scarcity Strategy (The 3–5 Client Cap)

To maximize upfront revenue while building leverage for future recurring SaaS pricing, the **€7,500 flat fee must be strictly capped at 3 to 5 founding clients**.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     3–5 ANCHOR CLIENT ROLLOUT STRATEGY                      │
├───────────────────────┬─────────────────────────────────────────────────────┤
│ Strategy Metric       │ Operational Target                                  │
├───────────────────────┼─────────────────────────────────────────────────────┤
│ Target Client Cap     │ Strictly 3 to 5 Founding Partner organizations      │
│ Total Upfront Cash    │ €22,500 – €37,500 (6–12 months non-dilutive runway) │
│ Long-Term SLA Revenue │ €600 – €1,000 / month (Year 2 maintenance SLAs)     │
│ Sales Velocity Lever  │ Scarcity & FOMO ("Only 5 founding spots available") │
└───────────────────────┴─────────────────────────────────────────────────────┘
```

### 1. The 3-Phase Commercial Rollout Roadmap

```
  Phase 1: Founding Anchor Deals          Phase 2: Transition Phase           Phase 3: Standard SaaS Scale
      (Clients 1 through 5)                   (Clients 6 through 15)                  (Clients 16+)
┌────────────────────────────────┐      ┌────────────────────────────────┐      ┌────────────────────────────────┐
│ • €7,500 One-Time Setup Fee    │      │ • Close €7,500 Founding Program│      │ • €199 / mo Pro Tier           │
│ • 12 Months SLA Included       │ ───> │ • Transition 100% to Recurring │ ───> │ • €499 / mo Agency Tier        │
│ • €199 / mo SLA starting Yr 2  │      │ • Introduce €199–€499/mo SaaS  │      │ • Self-serve web signup flow   │
└────────────────────────────────┘      └────────────────────────────────┘      └────────────────────────────────┘
```

### 2. Recommended 5-Client Portfolio Mix
To establish maximum market credibility across Transylvania and Romania, target the 5 founding spots across distinct client archetypes:

- **2 Grant Writing Consultancies**: Provides high daily usage volume, multi-client testing, and agency feedback.
- **2 Mid-to-Large NGOs**: Provides social impact proof and non-profit sector validation (e.g., healthcare/education).
- **1 SME / Corporate Applicant**: Validates commercial business usefulness for PNRR, R&D, and regional operational grants.

### 3. The Scarcity Pitch (Closing Hook)
When presenting the €7,500 offer, use scarcity as the primary conversion driver:

> *"We are capping our Founding Partner Program at exactly 5 organizations across Transylvania. This grants your team full enterprise platform access and white-label customization for a one-time fee of €7,500 with 12 months of maintenance included. Once these 5 spots are filled, the program closes permanently, and all subsequent organizations will onboard at our standard €499/month subscription tier."*

---

## 7. Handling Maintenance SLA Declines ("No Updates" Clients)

When a client pays the upfront fee (€7,500 or €15,000) and subsequently asks: *"What if we don't want to pay the monthly SLA after Year 1 and just want to keep our current version?"*, the contract provides three explicit operational pathways:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                 MAINTENANCE SLA DECLINE OPTIONS & POLICIES                  │
├───────────────────────┬─────────────────────────────────────────────────────┤
│ Policy Option         │ Commercial & Technical Terms                        │
├───────────────────────┼─────────────────────────────────────────────────────┤
│ 1. Hosted Cloud SaaS  │ • €199/mo (SME) or €399/mo (Agency) starting Yr 2.  │
│    (Standard SLA)     │ • Includes cloud hosting, AI token costs, and       │
│                       │   immediate fix for any broken scraper layout.      │
├───────────────────────┼─────────────────────────────────────────────────────┤
│ 2. Pay-Per-Fix        │ • Client declines monthly SLA.                      │
│    (Hourly Tickets)   │ • Zero uptime guarantee. Scraper fixes billed at    │
│                       │   €60–€80/hr or €300–€500 per repair ticket.        │
├───────────────────────┼─────────────────────────────────────────────────────┤
│ 3. Self-Hosted        │ • Client receives code export / Docker container.   │
│    (Complete Hand-Off)│ • Client hosts on their own servers & API keys.     │
│                       │ • Zero updates provided; internal IT maintains code.│
└───────────────────────┴─────────────────────────────────────────────────────┘
```

### Technical Rationale & Scraper Rot Script

When clients question why a monthly SLA is necessary for software they already purchased, use this contractual explanation script:

> *"Funding Radar is a live intelligence engine connected to external government portals (MIPE, ADRs, EU SEDIA). Government ministries update their website HTML structures and guideline PDFs multiple times per year. When layout changes occur, unmaintained scrapers stop detecting new calls.*
> 
> *The monthly SLA covers cloud hosting, AI document extraction tokens, and guarantees that when a ministry modifies its portal or changes a guideline deadline, our engineers fix the parser immediately so your team never misses a funding call."*


