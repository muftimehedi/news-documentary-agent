---
name: social-posts
description: Write platform-specific social texts within hard character limits, traceable to verified claims; post only after explicit user approval.
version: 1.0.0
---
# Social post procedure
1. Draft from verified claims only; record claim_ids per post.
2. Hard limits: x<=280 chars, facebook<=2000, hikmah<=20000. Never split a claim citation by truncation.
3. YouTube has no text-post API: generate title+description for MANUAL use only and mark connect_post=false with the reason.
4. Save posts.json (text, chars, claim_ids, connect_post, note per platform) in the job namespace.
5. The agent prepares text; it never approves or sends posts. Publishing needs an explicit user Review & Publish per destination, bound to the content hash.
6. One destination failing never erases other successes; retry only failed ones; duplicates skipped by logical keys.
