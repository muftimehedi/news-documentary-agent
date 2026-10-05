---
name: social-publishing
description: Publish via official APIs with approval binding, idempotency, reconciliation.
version: 1.0.0
---
# Publishing procedure
1. Require bound approval (video hash + script version + destinations).
2. Persist intent with UNIQUE logical key per job/destination/version before upload.
3. Official APIs only; reconcile ambiguous timeouts; resume without re-uploading successes.
4. YouTube real adapter; Facebook/Instagram are milestone-5 stubs until permissions verified.
