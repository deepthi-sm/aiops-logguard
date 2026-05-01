/**
 * className merge helper. Filters falsy values and joins with spaces.
 *
 * Tiny on purpose — we don't pull in `clsx` or `tailwind-merge` for this.
 * If we ever need conflict resolution between Tailwind classes, swap to
 * `tailwind-merge` then.
 */
type ClassValue = string | number | false | null | undefined;

export function cn(...parts: ClassValue[]): string {
  return parts.filter(Boolean).join(" ");
}
