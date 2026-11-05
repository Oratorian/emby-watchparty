# French language pack test files

- [french-good.zip](french-good.zip) is a valid partial French pack. It translates the landing page, language selector, login labels, and selected party/library controls. Other messages fall back to English. Select **Français (test)** after installation.
- [french-faulty.zip](french-faulty.zip) is identical except for one deliberate placeholder error: `core.request_failed` uses `{etat}` where English requires `{status}`.

Install the good pack first, then upload the faulty one. Both declare locale `fr`, so the second upload tests a rejected replacement. Expect `Translation placeholders do not match English for core.request_failed.` The installed French pack should remain unchanged. On an instance without French installed, the faulty upload should add no language.

The readable source for the good pack is in [french-example](french-example/). These are test fixtures, not a complete French translation. Neither ZIP is installed automatically.
