# Anthropic policy audit for employee deployment

Audit date: 2026-07-27

Verdict: `BLOCKED_REGION_VERIFICATION`

This is a release-safety review of `claude-base-v2`, not legal advice and not a
finding about any specific suspended account. The exact suspension reason can
only be established by Anthropic through its review or appeal process.

## Official sources reviewed

- Usage Policy: https://www.anthropic.com/legal/aup
- Consumer Terms of Service:
  https://www.anthropic.com/legal/consumer-terms
- Supported countries and regions:
  https://www.anthropic.com/supported-countries
- Safeguards warnings and appeals:
  https://support.claude.com/en/articles/8241253-safeguards-warnings-and-appeals

These pages are live policy sources and must be checked again immediately
before an employee release.

## Findings

1. Russian-language construction documents are not prohibited merely because
   they are written in Russian or concern Russian engineering standards.
   Submitted documents still require lawful processing rights and must not
   contain unlawfully disclosed personal, confidential, or proprietary data.
2. Russia is not listed in Anthropic's current supported-country lists for
   either commercial API access or Claude.ai. This does not establish the
   reason for a past account action, but it prevents a blanket employee
   rollout until each user's physical-location, residence, organization, and
   account eligibility have been verified against the current policy.
3. Anthropic's Usage Policy prohibits facilitating access that violates the
   Supported Regions Policy, circumventing a ban through another account, and
   bypassing product restrictions or guardrails.
4. Anthropic's Consumer Terms prohibit sharing account credentials. The
   deployment model therefore requires one eligible account per employee.
5. The Consumer Terms also restrict automated or non-human access except
   through an API key or where Anthropic explicitly permits it. Official
   interactive Claude Code use must remain within the applicable account and
   product terms; unattended automation requires separately confirmed
   permission or an appropriate commercial/API agreement.
6. Anthropic's safeguards guidance names repeated policy violations, account
   creation from an unsupported location, and Terms violations as possible ban
   reasons. It also says an organization may be put on hold for unusual
   activity. These are possible categories, not proof of what happened in any
   supplied screenshot.

## Mandatory deployment controls

- Direct, VPN, HTTP, HTTPS, and SOCKS5 are connection transports only. They
  must not be used to bypass a supported-region restriction, an account ban,
  a product control, or a safety guardrail.
- Do not create replacement accounts for a suspended user and do not share a
  hub/developer account with employees.
- Require one eligible account per employee and verify the employee's location
  and organization eligibility against the live Supported Regions Policy.
- Keep authentication outside the installer package. The installer must not
  collect, export, log, or distribute account credentials.
- Use only the official client and an accepted client version. Do not automate
  account creation or run unattended consumer-account bots.
- Confirm that the organization has rights to upload each document and apply
  human review to legal, financial, employment, or other high-risk outputs.
- A suspended account must use Anthropic's appeal flow. The installer must not
  offer or document a technical workaround.

## Release effect

`POLICY_AUDIT` may not become `PASS` from this document alone. It remains
`BLOCKED_REGION_VERIFICATION` until the owner records a current, supportable
employee deployment model covering:

- the countries and physical locations from which employees will access
  Claude;
- the account or organization product used by each employee;
- confirmation that no proxy or VPN is being used for region or ban
  circumvention;
- the permitted boundary for interactive use and any automation.

Until that evidence exists, `FULL_RELEASE_CLAUDE` stays `NOT_PASS`.
