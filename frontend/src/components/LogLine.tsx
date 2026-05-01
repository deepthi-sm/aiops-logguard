import { cn } from "../lib/cn";

/**
 * Colorises the leading log level token (`ERROR`, `WARN`, `INFO`, …) so each
 * line is severity-scannable at a glance:
 *
 *   ERROR keystone-api Failed to authenticate user 'alice' from 192.168.1.42
 *   ────                                                                       ← coral
 *   WARN  keystone-api elevated auth-fail rate from /24
 *   ────                                                                       ← amber
 *   INFO  keystone-api auth request user=alice from 192.168.1.42
 *   ────                                                                       ← cyan
 *
 * If the line doesn't start with a recognised level token, renders unchanged.
 * `font-medium` on the level token makes it stand out without changing the
 * line's overall layout.
 */
const LEVEL_REGEX = /^(FATAL|ERROR|WARNING|WARN|INFO|DEBUG|TRACE)\s/;

export function LogLine({
  line,
  className,
}: {
  line: string;
  className?: string;
}) {
  const match = line.match(LEVEL_REGEX);
  if (!match) {
    return <span className={className}>{line}</span>;
  }
  const level = match[1];
  const rest = line.slice(match[0].length);
  return (
    <span className={className}>
      <span className={cn("font-medium", levelColor(level))}>{level}</span>
      {" " + rest}
    </span>
  );
}

function levelColor(level: string): string {
  switch (level) {
    case "ERROR":
    case "FATAL":
      return "text-critical";
    case "WARN":
    case "WARNING":
      return "text-warning";
    case "INFO":
      return "text-info";
    case "DEBUG":
    case "TRACE":
      return "text-tertiary";
    default:
      return "";
  }
}
