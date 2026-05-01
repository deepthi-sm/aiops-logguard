/// <reference types="vite/client" />

/**
 * Project-specific env var augmentation. Add a line per `VITE_*` var so the
 * compiler catches typos at the call site (`import.meta.env.VITE_USE_MOCK`
 * is now string|undefined, not `any`).
 *
 * Vite exposes all values as strings — the runtime conversion to bool/number
 * is the caller's responsibility.
 */
interface ImportMetaEnv {
  /** "true" | "false" | undefined. See `src/api/client.ts` for the
   *  default behaviour (mock mode unless explicitly disabled). */
  readonly VITE_USE_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
