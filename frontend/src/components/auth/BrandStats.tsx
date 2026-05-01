/**
 * Three-column stats row at the bottom of the auth left-pane. Each
 * column: big iris number on top, tertiary 11px label below, hairline
 * vertical dividers between.
 */
const STATS: { value: string; label: string }[] = [
  { value: "0.91", label: "F1 on held-out test" },
  { value: "12 min", label: "avg early warning" },
  { value: "100%", label: "on-prem, no cloud" },
];

export function BrandStats() {
  return (
    <div className="grid grid-cols-3 border-t-[0.5px] border-border-subtle pt-6">
      {STATS.map((s, i) => (
        <div
          key={s.label}
          className={
            i === 0
              ? ""
              : "border-l-[0.5px] border-border-subtle pl-5"
          }
        >
          <div className="font-mono text-[24px] font-medium leading-none tracking-[-0.02em] text-iris">
            {s.value}
          </div>
          <div className="mt-2 text-[11px] text-tertiary">{s.label}</div>
        </div>
      ))}
    </div>
  );
}
