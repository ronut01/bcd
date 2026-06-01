export type FrontmatterValue = string | string[] | number | boolean | undefined;
export type Frontmatter = Record<string, FrontmatterValue>;

export function stringifyFrontmatter(data: Frontmatter, body: string): string {
  const lines = ["---"];
  for (const [key, value] of Object.entries(data)) {
    if (value === undefined) {
      continue;
    }
    if (Array.isArray(value)) {
      lines.push(`${key}: ${JSON.stringify(value)}`);
      continue;
    }
    if (typeof value === "string") {
      lines.push(`${key}: ${JSON.stringify(value)}`);
      continue;
    }
    lines.push(`${key}: ${String(value)}`);
  }
  lines.push("---", body.trim(), "");
  return lines.join("\n");
}

export function parseFrontmatter(markdown: string): { data: Frontmatter; body: string } {
  const normalized = markdown.replace(/\r\n/g, "\n");
  if (!normalized.startsWith("---\n")) {
    return { data: {}, body: normalized };
  }

  const end = normalized.indexOf("\n---", 4);
  if (end === -1) {
    return { data: {}, body: normalized };
  }

  const raw = normalized.slice(4, end).split("\n");
  const body = normalized.slice(end + 5).replace(/^\n/, "");
  const data: Frontmatter = {};

  for (let index = 0; index < raw.length; index += 1) {
    const line = raw[index];
    if (!line.trim()) {
      continue;
    }
    const splitAt = line.indexOf(":");
    if (splitAt === -1) {
      continue;
    }
    const key = line.slice(0, splitAt).trim();
    const value = line.slice(splitAt + 1).trim();

    if (!value) {
      const values: string[] = [];
      while (raw[index + 1]?.trim().startsWith("- ")) {
        index += 1;
        values.push(raw[index].trim().slice(2).trim());
      }
      data[key] = values;
      continue;
    }

    data[key] = parseScalar(value);
  }

  return { data, body };
}

function parseScalar(value: string): FrontmatterValue {
  if (value === "true") {
    return true;
  }
  if (value === "false") {
    return false;
  }
  if (/^-?\d+(\.\d+)?$/.test(value)) {
    return Number(value);
  }
  if ((value.startsWith("[") && value.endsWith("]")) || (value.startsWith('"') && value.endsWith('"'))) {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        return parsed.map((entry) => String(entry));
      }
      return String(parsed);
    } catch {
      return value;
    }
  }
  return value;
}

export function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64) || "decision";
}

export function frontmatterString(value: FrontmatterValue): string | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  return String(value);
}

export function frontmatterArray(value: FrontmatterValue): string[] {
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry));
  }
  if (typeof value === "string" && value.trim()) {
    return value.split(",").map((entry) => entry.trim()).filter(Boolean);
  }
  return [];
}
