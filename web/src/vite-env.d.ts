/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

interface ImportMetaEnv {
  /** Base URL of the live API; default "/api" (same origin). */
  readonly VITE_API_BASE?: string
  /** "1": read the sample fixtures instead of the API (fallback flag). */
  readonly VITE_FIXTURES?: string
}
interface ImportMeta { readonly env: ImportMetaEnv }
