## [ERR-20260315-HTTP8899] dashboard server restart failed

**Logged**: 2026-03-15T16:10:30Z
**Priority**: medium
**Status**: pending
**Area**: infra

### Summary
Restarting http.server on port 8899 failed because the port was already in use

### Error
```
OSError: [Errno 98] Address already in use
```

### Context
- Command: kill $(lsof -t -i:8899) 2>/dev/null; sleep 1; python3 -m http.server 8899 --directory /root/.openclaw/dashboard &

### Suggested Fix
Ensure process is terminated before restart (use lsof/kill and retry), or start with nohup after confirming the port is free

### Metadata
- Reproducible: yes
- Related Files: /root/.openclaw/dashboard

---
