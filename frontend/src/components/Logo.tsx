/**
 * The LogGuard hexagon mark — variant A (energetic).
 *
 * The hexagon stroke uses `currentColor` so it inherits the parent's text
 * color (iris in normal use). The center dot is always the coral anomaly
 * accent — that's the visual "thing being detected" inside the system.
 */
export function Logo({ size = 24 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-label="LogGuard"
      role="img"
    >
      <path
        d="M16 4 L26 10 L26 22 L16 28 L6 22 L6 10 Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M16 4 L16 16 L26 22"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        opacity="0.5"
      />
      <path
        d="M16 16 L6 22 M16 16 L26 10 M16 16 L16 28"
        fill="none"
        stroke="currentColor"
        strokeWidth="1"
        opacity="0.3"
      />
      <circle cx="16" cy="16" r="2" fill="var(--anomaly)" />
    </svg>
  );
}
