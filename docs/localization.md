# UI localization

Watch Party uses [vue-i18n](https://vue-i18n.intlify.dev/guide/advanced/composition) for English (`en`) and German (`de`). The first supported language in the browser's preference list is selected automatically, with English as the fallback. The language control offers browser detection or an explicit choice. Explicit choices are saved locally under `watchparty-language`, independently for each viewer, and switching updates the UI without reloading or interrupting playback. Browser storage is optional; switching still works if it is blocked.

## Catalogs

Messages live in `frontend/src/locales/<language>/<namespace>.json`. The filename supplies the namespace, so a `title` key in `library.json` is addressed as `library.title`. English and German must contain matching keys and placeholders. Additional languages require registering their locale in `frontend/src/i18n/index.ts` and adding an option to `LanguageSelector.vue`.

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

The initial German translations were supplied by [timokohlbrecher-collab in issue #87](https://github.com/Oratorian/emby-watchparty/issues/87), then adapted into full messages with interpolation and plural forms.
