# Testing language packs

Use the [language-pack creator](https://oratorian.github.io/emby-watchparty/) to export a partial French pack with locale `fr` and at least one translated message. Install it through **Admin Panel → Manage language packs**, then choose French in the language selector.

To test a rejected replacement, make a copy of that ZIP and change the `core.request_failed` placeholder from `{status}` to `{etat}`. Keep the locale as `fr`. The upload should fail with `Translation placeholders do not match English for core.request_failed.` while preserving the working French pack. On an instance without French installed, the faulty upload should add no language.

Automated format, archive and backend-compatibility checks live in `language-pack-builder/format.test.mjs`. The browser workflow is covered in `frontend/e2e/language-packs.spec.ts` and `frontend/e2e/language-pack-builder.spec.ts`.
