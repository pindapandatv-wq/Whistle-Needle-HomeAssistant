# Contributing

Thanks for helping improve Whistle Assist.

## Before opening a pull request

- Describe the Home Assistant version and installation type used for testing.
- Include reproduction steps and sanitized logs; never post access tokens, secrets, transcripts containing personal data, or private home/location details.
- Keep device actions allowlisted. Do not introduce a generic arbitrary service-call tool.
- Re-check live entity exposure immediately before every action and validate model-provided arguments at execution time.
- For changes to schemas or device actions, add or update tests and document the new behavior in `README.md`.
- Run:

  ```sh
  python scripts/validate_repo.py
  python -m compileall -q custom_components/whistle_assist
  ```

GitHub Actions also runs Home Assistant Hassfest and HACS validation. A successful static check does not replace testing against a working Home Assistant instance.

## Pull request checklist

- [ ] No credentials or private data included.
- [ ] License and third-party notices remain intact.
- [ ] README and translations updated where applicable.
- [ ] Safety behavior preserved or explicitly reviewed.
- [ ] Tests/checks pass.
