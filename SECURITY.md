# Security policy

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose microphone audio,
transcripts, provider credentials, local files, or command execution.

Use the repository's **Security → Report a vulnerability** flow on GitHub. Include:

- affected OpenFlow version and commit
- operating system and Python version
- minimal reproduction steps
- expected and observed security boundary
- whether credentials, audio, transcripts, or local files were exposed

Do not include real credentials, cookies, recordings, transcripts, or proprietary asar files
in the report. Use synthetic data and redact local usernames and paths.

## Supported versions

Security fixes target the latest commit on `main` and the latest tagged release. Older
releases may require upgrading rather than a backport.

## Threat model and safe deployment

OpenFlow is a single-user desktop tool. Its HTTP API is intended only for loopback use.

- Keep `WISPR_GROK_HOST=127.0.0.1` unless you are actively developing in an isolated
  environment.
- Never port-forward or reverse-proxy port `18765`.
- OpenFlow rejects arbitrary browser origins, but CORS is not a substitute for host or network
  isolation.
- Provider credentials remain in their providers' local stores. Never copy those files into
  the OpenFlow install directory.
- Failed-audio retention is off by default. Files written through the explicit
  `WISPR_GROK_DEBUG_AUDIO` option are the user's responsibility and should be deleted after
  diagnosis.
- Provider fallbacks are explicit because changing providers can change where speech data is
  processed.

The desktop patch command modifies a third-party application already installed by the user.
Run it deliberately, keep the stock backup, and use `python -m openflow restore` to return to
the original asar.
