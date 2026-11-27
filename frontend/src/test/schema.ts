import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/**
 * A small JSON Schema checker for the parts of openapi.json our request bodies use
 * ($ref, anyOf, oneOf, type, enum, const, required, properties, additionalProperties,
 * items, min/maxItems, minimum, maximum, exclusiveMinimum, min/maxLength). It reads the
 * same openapi.json the types are generated from, so the stored profile is checked
 * against the API's own rules, not a copy of them.
 */
type Schema = Record<string, unknown>;

const spec = JSON.parse(readFileSync(resolve(__dirname, "../../openapi.json"), "utf8")) as {
  components: { schemas: Record<string, Schema> };
};

export function schemaFor(name: string): Schema {
  const schema = spec.components.schemas[name];
  if (!schema) throw new Error(`no schema ${name}`);
  return schema;
}

function deref(schema: Schema): Schema {
  const ref = schema.$ref as string | undefined;
  return ref ? schemaFor(ref.split("/").pop()!) : schema;
}

function typeOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  return typeof value;
}

/** Problems found, as "path: what"; empty when the value fits. */
export function check(value: unknown, input: Schema, path = "$"): string[] {
  const schema = deref(input);
  const options = (schema.anyOf ?? schema.oneOf) as Schema[] | undefined;
  if (options) {
    const results = options.map((option) => check(value, option, path));
    return results.some((r) => r.length === 0) ? [] : [`${path}: matches none of the allowed shapes (${results.flat().join("; ")})`];
  }
  const problems: string[] = [];
  const type = schema.type as string | undefined;
  const actual = typeOf(value);
  if (type && !(actual === type || (type === "number" && actual === "integer"))) return [`${path}: expected ${type}, got ${actual}`];
  if (schema.enum && !(schema.enum as unknown[]).includes(value)) problems.push(`${path}: ${String(value)} not in enum`);
  if ("const" in schema && schema.const !== value) problems.push(`${path}: expected ${String(schema.const)}`);
  if (typeof value === "number") {
    if (typeof schema.minimum === "number" && value < schema.minimum) problems.push(`${path}: below minimum`);
    if (typeof schema.maximum === "number" && value > schema.maximum) problems.push(`${path}: above maximum`);
    if (typeof schema.exclusiveMinimum === "number" && value <= schema.exclusiveMinimum) problems.push(`${path}: not above ${schema.exclusiveMinimum}`);
  }
  if (typeof value === "string") {
    if (typeof schema.minLength === "number" && value.length < schema.minLength) problems.push(`${path}: too short`);
    if (typeof schema.maxLength === "number" && value.length > schema.maxLength) problems.push(`${path}: too long`);
  }
  if (Array.isArray(value)) {
    if (typeof schema.minItems === "number" && value.length < schema.minItems) problems.push(`${path}: too few items`);
    if (typeof schema.maxItems === "number" && value.length > schema.maxItems) problems.push(`${path}: too many items`);
    if (schema.items) value.forEach((item, i) => problems.push(...check(item, schema.items as Schema, `${path}[${i}]`)));
  }
  if (actual === "object") {
    const obj = value as Record<string, unknown>;
    const props = (schema.properties ?? {}) as Record<string, Schema>;
    for (const key of (schema.required ?? []) as string[]) if (!(key in obj)) problems.push(`${path}.${key}: required`);
    for (const [key, v] of Object.entries(obj)) {
      if (props[key]) problems.push(...check(v, props[key], `${path}.${key}`));
      else if (schema.additionalProperties === false) problems.push(`${path}.${key}: not allowed`);
    }
  }
  return problems;
}

/** The schema of one item of SearchRequest.rules, so a rule is checked against all kinds. */
export function rulesItemSchema(): Schema {
  const rules = (schemaFor("SearchRequest").properties as Record<string, Schema>).rules!;
  return rules.items as Schema;
}
