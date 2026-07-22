# Local Whisper mode

OpenFlow can send transcription audio to an OpenAI-compatible Whisper server on the user's
machine or private network. This changes only the speech provider; it does not bypass login,
subscription, or access controls in the desktop shell.

## Configure

Start the shim and open the local setup UI:

```bash
python -m openflow serve
```

Open <http://127.0.0.1:18765/>, choose **Local**, and set:

- URL, for example `http://127.0.0.1:8080/v1/audio/transcriptions`
- model, default `whisper-1`
- optional endpoint API key

Settings are written to `%APPDATA%\\OpenFlow\\config.json` on Windows. The endpoint key is
local configuration and must never be committed.

## Privacy behavior

- Local is the only transcription destination when it is selected and `fallback` is empty.
- OpenFlow does not silently fail over from Local to a cloud provider.
- Failed audio is not retained unless `WISPR_GROK_DEBUG_AUDIO` is explicitly set.
- Deterministic cleanup runs locally.
- The optional `WISPR_GROK_LLM_FORMAT=true` pass sends transcript text to Grok; leave it off
  for a fully local pipeline.

## Endpoint contract

OpenFlow sends multipart WAV audio to an OpenAI-compatible
`/v1/audio/transcriptions` endpoint. The response must include a `text` field. Provider status
probes the configured URL and reports connection failures honestly in `/health`.

The desktop application is still governed by its own account and feature access. OpenFlow's
public patch changes transcription routing and timeouts only.
