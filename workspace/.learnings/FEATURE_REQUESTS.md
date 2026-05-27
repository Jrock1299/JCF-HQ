## [FEAT-20260304-001] oracle_sports_picks_autolog

**Logged**: 2026-03-04T08:27:00Z
**Priority**: high
**Status**: pending
**Area**: ops

### Requested Capability
Auto-funnel sports picks sent by Jase to Oracle; auto-log results daily at 9AM; write results into HQ under Oracle Intelligence by capper; auto-add missing capper entries.

### User Context
Jase wants a consistent, automated workflow for tracking capper picks and results without manual follow-up.

### Complexity Estimate
medium

### Suggested Implementation
Create intake schema for picks; persist in a tracking file/db; schedule a daily job at 9AM to resolve results and write to HQ; add capper if not present.

### Metadata
- Frequency: recurring
- Related Features: morning_report

---
