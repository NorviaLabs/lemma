# Security

## Reporting a problem

Email **contact@openlemma.org** with what you found, how to reproduce it, and what someone could do with it. Please don't open a public issue or share details until it's fixed. We'll reply as soon as we can and tell you when a fix is live.

## Testing responsibly

You're welcome to test your own copy of OpenLemma (see [README.md](README.md)). On openlemma.org, please:

- use only your own account, and never read, change or delete anyone else's data;
- don't send floods of requests, run denial-of-service tests, or try social engineering;
- stop and tell us if you reach other people's data, and don't keep a copy.

## What matters most

OpenLemma holds people's accounts, their saved lessons and the sources they bring, and it fetches links on the server. Problems we especially want to hear about include reading or changing another account's data, getting the server to fetch private or internal addresses, script running in a lesson or a downloaded lesson, and any way an AI provider key or session could leak. Learners' AI keys stay in their browsers and are sent only with each request; the server never stores them.
