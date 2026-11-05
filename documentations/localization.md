# UI localization

Watch Party uses [vue-i18n](https://vue-i18n.intlify.dev/guide/advanced/composition) for English (`en`) and German (`de`). The first supported language in the browser's preference list is selected automatically, with English as the fallback. The language control offers browser detection or an explicit choice. Explicit choices are saved locally under `watchparty-language`, independently for each viewer, and switching updates the UI without reloading or interrupting playback. Browser storage is optional; switching still works if it is blocked.

## Installing community translations

Open the admin panel and expand **Manage language packs**. Download the translation template, edit it, then choose the ZIP and select **Install language pack**. The new language appears in the language selector without rebuilding or restarting EWP. Uploading the same language code replaces its pack; failed validation or a failed write preserves the previous version. Removal has an inline confirmation.

The installing browser refreshes its choices immediately. Other open viewers check every 30 seconds while visible, and when returning to the tab. The selected catalog is fetched when needed; an updated selected pack refreshes without interrupting playback. Temporary network failures retain valid loaded translations and show a retry control. English and German remain available without the pack service.

Packs are stored under `data/languages/pack-<locale>.json`, inside the existing persistent data mount. Include this directory in backups. Restarting or replacing the container retains installed packs when the data volume is preserved. Removing an uploaded German pack restores the bundled German translation. English is the fallback and cannot be replaced by an upload.

## Creating a pack

Use the [online language-pack creator](https://oratorian.github.io/emby-watchparty/) to edit translations, check placeholders and download an installable ZIP. Drafts are saved in your browser; you can also download a draft or open an existing ZIP to continue translating. The creator uses the same English catalog and validation rules as EWP. Blank messages are omitted and fall back to English.

The downloaded ZIP contains `manifest.json` and the current English namespace files. Keep the files at the ZIP root. A manifest looks like this:

```json
{
  "format": 1,
  "locale": "fr",
  "name": "Français",
  "author": "Your name",
  "version": "1.0"
}
```

Set `locale` to a language code such as `fr`, `pt-BR` or `zh-Hant`, and `name` to the name shown in the selector. `author` and `version` are optional text. Translate the values in the namespace JSON files, retaining their nested structure and key names. You may omit untranslated files or keys; missing messages fall back to English. Keep at least one translated message. Use a fresh template when updating a pack for a newer EWP version, since renamed keys or changed placeholders require adjustment.

Preserve each message's named placeholders, including names used for formatted countdown values. For example, translate `"Welcome, {name}"` while keeping `{name}`. Pipe-separated vue-i18n plural forms are supported; message links, executable code and HTML are not. A literal at sign uses `{'@'}`, as in `you{'@'}example.com`.

Upload a standard, unencrypted ZIP using stored or deflate compression, no larger than 1 MiB; the expanded JSON files must fit within 2 MiB. Nested folders, duplicate names, unknown keys, mismatched placeholders and non-text values are rejected. EWP reads and validates archive members without extracting arbitrary filesystem paths. An instance can hold up to 32 community packs.

## Bundled catalogs

Bundled messages live in `frontend/src/locales/<language>/<namespace>.json`. The filename supplies the namespace, so a `title` key in `library.json` is addressed as `library.title`. Bundled English and German must contain matching keys and placeholders. Community packs register their languages dynamically; they do not require changes to the selector or a frontend rebuild.

Use the reactive shared composer in components, stores and composables:

```ts
import { t } from '@/i18n'

t('core.request_failed', { status: 503 })
```

Translate full sentences with named placeholders. Keep `{name}`, `{count}` and other parameter names identical across languages. Use vue-i18n's pipe-separated plural forms and pass a numeric `count` or a number as the second argument. Computed labels and option arrays must read `t()` inside a computed getter so changing language refreshes them. Translate accessibility labels, placeholders and recovery guidance as well as visible headings.

Render translated messages with Vue text interpolation or bound attributes. Do not use `v-html` for translations or interpolate user content into HTML. Translate complete sentences around provider names rather than choosing English articles or joining fragments.

## Backend data

The Python backend does not run vue-i18n. It returns provider-neutral control IDs, option values and default labels. The frontend maps known IDs and fixed values to translated display labels. Unknown controls retain their server-provided label. Library metadata such as movie titles, studios, tags and genre names comes from the media server and is preserved.

Never translate filter IDs, request values, sort fields, Socket.IO event names, configuration variables or media type identifiers. Backend and proxy error details may be English; unknown details remain visible rather than being replaced with a misleading translation. Server logs retain their original language for troubleshooting.

## Validation and credits

Run `npm run test:unit`, `npm run type-check`, `npm run lint` and `npm run build` in `frontend/`. Catalog tests check key parity, placeholder parity and message syntax. Component tests cover language switching and stable filter values. Check longer German labels at narrow screen widths when editing layouts.

After changing bundled English messages, run `python scripts/generate_language_catalog.py`. This packages the English schema in `backend/language-catalog.json` for validation and template downloads, including Docker images that do not contain the frontend source. CI checks for drift with `--check`. Backend pack tests cover authentication, archive bounds, malformed input, atomic replacement and restart persistence. The language API's response models are also included in the generated REST contract.

The initial German translations were supplied by [timokohlbrecher-collab in issue #87](https://github.com/Oratorian/emby-watchparty/issues/87), then adapted into full messages with interpolation and plural forms.
